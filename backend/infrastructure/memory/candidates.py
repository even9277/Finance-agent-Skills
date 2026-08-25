"""实现 REM 候选抽取的离线确定性与 OpenAI-compatible 适配器。"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from backend.application.memory.candidates import (
    CANDIDATE_EXTRACTOR_SCHEMA_VERSION,
    CandidateExtractionRequest,
    CandidateExtractorPort,
)
from backend.config import settings
from src.memory.contracts import (
    CandidateDraft,
    CandidateEvidence,
    MemoryContractError,
    MemoryValueKind,
    ProfileField,
)

_CANDIDATE_SYSTEM_PROMPT = """
你是金融 Agent 的 REM 候选抽取器。只允许依据输入中的 user_messages，
working_state_events 只能作为同一用户消息的辅助标签。assistant、tool、摘要文字都不是
用户事实。输出候选而不是有效记忆；不要决定晋升。高影响画像也只能输出建议。
仅输出 JSON：{"schema_version":"memory-candidate-output-v1","candidates":[...]}
每项字段：kind、category、normalized_key、confidence、message_ids、profile_field、value、
content、conflict_key。kind 只能 structured_profile/text；message_ids 必须来自输入。
""".strip()


class _ProviderCandidate(BaseModel):
    """严格校验模型返回的单条候选。"""

    model_config = ConfigDict(extra="forbid")

    kind: MemoryValueKind
    category: str = Field(min_length=1, max_length=64)
    normalized_key: str = Field(min_length=1, max_length=180)
    confidence: float = Field(ge=0.0, le=1.0)
    message_ids: list[int] = Field(min_length=1, max_length=12)
    profile_field: ProfileField | None = None
    value: str | float | list[str] | None = None
    content: str | None = Field(default=None, max_length=500)
    conflict_key: str | None = Field(default=None, max_length=180)


class _ProviderEnvelope(BaseModel):
    """冻结候选 Provider 的版本化 JSON 信封。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    candidates: list[_ProviderCandidate] = Field(max_length=12)


class DeterministicCandidateExtractor:
    """用有限规则从用户原话提取可复现候选，供默认 CI 与降级路径使用。"""

    async def extract(
        self,
        request: CandidateExtractionRequest,
    ) -> tuple[CandidateDraft, ...]:
        """识别稳定回答偏好、主题兴趣和需确认画像，不访问网络。"""
        grouped: dict[tuple[str, str], list[CandidateEvidence]] = defaultdict(list)
        drafts: dict[tuple[str, str], CandidateDraft] = {}
        for message in request.messages:
            evidence = _evidence(request, message.message_id)
            for draft in _extract_message_rules(message.content, evidence):
                key = (draft.category, draft.normalized_key)
                grouped[key].append(evidence)
                drafts[key] = draft
        return tuple(
            CandidateDraft(
                kind=draft.kind,
                category=draft.category,
                normalized_key=draft.normalized_key,
                confidence=max(item.confidence for item in grouped[key]),
                evidence=tuple(_unique_evidence(grouped[key])),
                profile_field=draft.profile_field,
                value=draft.value,
                content=draft.content,
                conflict_key=draft.conflict_key,
            )
            for key, draft in drafts.items()
        )


class OpenAICompatibleCandidateExtractor:
    """调用统一 OpenAI-compatible 模型并在本地重建可信证据引用。"""

    def __init__(self) -> None:
        if not all(
            (
                settings.openai_compatible_model,
                settings.openai_compatible_api_key,
                settings.openai_compatible_base_url,
            )
        ):
            raise RuntimeError("candidate model configuration is incomplete")
        self._model = ChatOpenAI(
            model=settings.openai_compatible_model,
            api_key=SecretStr(settings.openai_compatible_api_key),
            base_url=settings.openai_compatible_base_url,
            temperature=0.0,
            timeout=float(settings.ltm_candidate_timeout_sec),
            max_retries=0,
        )

    async def extract(
        self,
        request: CandidateExtractionRequest,
    ) -> tuple[CandidateDraft, ...]:
        """发送去身份化行引用和必要正文，并严格拒绝畸形 JSON。"""
        payload = {
            "prompt_version": request.prompt_version,
            "schema_version": request.schema_version,
            "user_messages": [
                {"message_id": item.message_id, "content": item.content}
                for item in request.messages
            ],
            "working_state_events": [
                {
                    "event_id": item.event_id,
                    "message_id": item.message_id,
                    "field": item.field_name,
                    "operation": item.operation,
                    "value": item.value_text,
                    "confidence": item.confidence,
                }
                for item in request.state_signals
            ],
        }
        response = await self._model.ainvoke(
            (
                SystemMessage(content=_CANDIDATE_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            )
        )
        try:
            envelope = _ProviderEnvelope.model_validate_json(
                _response_text(response.content)
            )
        except (ValidationError, ValueError) as exc:
            raise MemoryContractError("candidate provider output is invalid") from exc
        if envelope.schema_version != CANDIDATE_EXTRACTOR_SCHEMA_VERSION:
            raise MemoryContractError("candidate provider schema version is unsupported")
        available = {item.message_id for item in request.messages}
        drafts: list[CandidateDraft] = []
        for item in envelope.candidates:
            if not set(item.message_ids).issubset(available):
                raise MemoryContractError("candidate provider cited an unknown message")
            raw_value = item.value
            if isinstance(raw_value, list):
                value: str | float | tuple[str, ...] | None = tuple(raw_value)
            elif isinstance(raw_value, (str, float)) or raw_value is None:
                value = raw_value
            else:
                raise MemoryContractError("candidate provider value has unsupported type")
            drafts.append(
                CandidateDraft(
                    kind=item.kind,
                    category=item.category,
                    normalized_key=item.normalized_key,
                    confidence=item.confidence,
                    evidence=tuple(
                        _evidence(request, message_id) for message_id in item.message_ids
                    ),
                    profile_field=item.profile_field,
                    value=value,
                    content=item.content,
                    conflict_key=item.conflict_key,
                )
            )
        return tuple(drafts)


def build_candidate_extractor() -> CandidateExtractorPort:
    """根据类型化配置构造唯一 REM 抽取端口。"""
    if settings.ltm_candidate_provider == "deterministic":
        return DeterministicCandidateExtractor()
    return OpenAICompatibleCandidateExtractor()


def _extract_message_rules(
    content: str,
    evidence: CandidateEvidence,
) -> tuple[CandidateDraft, ...]:
    """将有限中文表达映射为低风险文本或待确认画像候选。"""
    normalized = re.sub(r"\s+", "", content).lower()
    results: list[CandidateDraft] = []
    is_ephemeral = any(marker in normalized for marker in ("这次", "本次", "这一轮"))
    preference_rules = (
        (("先给结论", "结论前置"), "conclusion_first", "回答先给结论"),
        (("先讲风险", "风险优先"), "risk_first", "回答先讲主要风险"),
        (("简短", "简洁"), "concise", "回答保持简洁"),
        (("详细一点", "展开讲"), "detailed", "回答提供较完整细节"),
    )
    if not is_ephemeral:
        for markers, key, text in preference_rules:
            if any(marker in normalized for marker in markers):
                results.append(
                    CandidateDraft(
                        kind=MemoryValueKind.TEXT,
                        category="response_preference",
                        normalized_key=f"response_preference:{key}",
                        confidence=evidence.confidence,
                        evidence=(evidence,),
                        content=text,
                        conflict_key="response_preference:default",
                    )
                )
    if any(marker in normalized for marker in ("长期关注", "一直关注", "持续关注")):
        match = re.search(r"(?:长期|一直|持续)关注([a-z0-9\u4e00-\u9fff]{2,12})", normalized)
        if match:
            topic = match.group(1).rstrip("的了呢吗")
            results.append(
                CandidateDraft(
                    kind=MemoryValueKind.TEXT,
                    category="topic_interest",
                    normalized_key=f"topic_interest:{topic}",
                    confidence=evidence.confidence,
                    evidence=(evidence,),
                    content=f"用户持续关注{topic}",
                    conflict_key=f"topic_interest:{topic}",
                )
            )
    risk_map = {"保守": "conservative", "稳健": "moderate", "激进": "aggressive"}
    for marker, value in risk_map.items():
        if marker in normalized and any(term in normalized for term in ("风险", "偏好", "投资")):
            results.append(
                CandidateDraft(
                    kind=MemoryValueKind.STRUCTURED_PROFILE,
                    category="profile_suggestion",
                    normalized_key=f"profile:risk_level:{value}",
                    confidence=evidence.confidence,
                    evidence=(evidence,),
                    profile_field=ProfileField.RISK_LEVEL,
                    value=value,
                    conflict_key="profile:risk_level",
                )
            )
            break
    return tuple(results)


def _evidence(
    request: CandidateExtractionRequest,
    message_id: int,
) -> CandidateEvidence:
    """从冻结请求重建一条只引用用户消息的领域证据。"""
    message = next(item for item in request.messages if item.message_id == message_id)
    state_event = next(
        (item for item in request.state_signals if item.message_id == message_id),
        None,
    )
    return CandidateEvidence(
        session_id=request.session_id,
        message_id=message_id,
        source_role="user",
        query_hash=message.query_hash,
        observed_on=message.created_on,
        confidence=state_event.confidence if state_event is not None else 0.9,
        state_event_id=state_event.event_id if state_event is not None else None,
        state_version=request.state_version,
        summary_version=request.summary_version,
    )


def _unique_evidence(items: list[CandidateEvidence]) -> tuple[CandidateEvidence, ...]:
    """按消息和状态事件去除同一抽取请求内的重复证据。"""
    unique: dict[tuple[int, int | None], CandidateEvidence] = {}
    for item in items:
        unique[(item.message_id, item.state_event_id)] = item
    return tuple(unique.values())


def _response_text(content: object) -> str:
    """归一化 LangChain 响应并剥离常见 JSON fence。"""
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    else:
        text = str(content).strip()
    if text.startswith("```json") and text.endswith("```"):
        return text[7:-3].strip()
    if text.startswith("```") and text.endswith("```"):
        return text[3:-3].strip()
    return text
