"""定义 REM 候选抽取端口以及不信任模型输出的应用边界。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from src.memory.contracts import CandidateDraft, MemoryContractError

CANDIDATE_PROMPT_VERSION = "memory-candidate-rem-v1"
CANDIDATE_EXTRACTOR_SCHEMA_VERSION = "memory-candidate-output-v1"


@dataclass(frozen=True, slots=True)
class CandidateSourceMessage:
    """保存仅供抽取器使用的用户消息及其稳定引用。"""

    message_id: int
    content: str
    created_on: date
    query_hash: str


@dataclass(frozen=True, slots=True)
class CandidateStateSignal:
    """保存由用户消息触发的 Working State 字段事件。"""

    event_id: int
    message_id: int
    field_name: str
    operation: str
    value_text: str
    confidence: float
    state_version: int


@dataclass(frozen=True, slots=True)
class CandidateExtractionRequest:
    """冻结一次 REM 抽取可见的用户证据和状态版本。"""

    session_id: str
    summary_version: int
    state_version: int
    messages: tuple[CandidateSourceMessage, ...]
    state_signals: tuple[CandidateStateSignal, ...] = ()
    prompt_version: str = CANDIDATE_PROMPT_VERSION
    schema_version: str = CANDIDATE_EXTRACTOR_SCHEMA_VERSION


class CandidateExtractorPort(Protocol):
    """隔离模型 SDK；实现只能返回候选草稿，不能写数据库。"""

    async def extract(
        self,
        request: CandidateExtractionRequest,
    ) -> tuple[CandidateDraft, ...]:
        """从用户侧证据生成强类型候选草稿。"""
        ...


@dataclass(frozen=True, slots=True)
class CandidateGovernanceResult:
    """汇总一次后台治理的安全计数，不包含候选正文或用户标识。"""

    extracted_count: int
    created_count: int
    promoted_count: int
    confirmation_required_count: int
    conflicted_count: int


class CandidateGovernanceRepository(Protocol):
    """声明候选证据、状态、权威记录和审计必须同事务提交。"""

    async def govern(
        self,
        *,
        user_id: str,
        drafts: tuple[CandidateDraft, ...],
        prompt_version: str,
        summary_version: int,
        state_version: int,
        trace_id: str | None,
    ) -> CandidateGovernanceResult:
        """聚合候选证据并执行确定性晋升，不自行提交事务。"""
        ...


class CandidateExtractionUseCase:
    """协调 REM 抽取及不信任 Provider 的输出校验。"""

    def __init__(
        self,
        *,
        extractor: CandidateExtractorPort,
    ) -> None:
        self._extractor = extractor

    async def execute(
        self,
        *,
        request: CandidateExtractionRequest,
    ) -> tuple[CandidateDraft, ...]:
        """抽取并校验候选；空输出是成功的无信号结果。

        Args:
            request: 从权威消息、状态事件和版本边界装载的请求。

        Returns:
            仅引用冻结用户消息的强类型候选草稿。

        Raises:
            MemoryContractError: Provider 输出引用非用户或越界证据。
        """
        return validate_candidate_drafts(
            request,
            await self._extractor.extract(request),
        )


def validate_candidate_drafts(
    request: CandidateExtractionRequest,
    drafts: tuple[CandidateDraft, ...],
) -> tuple[CandidateDraft, ...]:
    """拒绝越界消息、非用户来源、重复草稿和异常规模输出。

    Args:
        request: Worker 从权威数据库装载的冻结输入。
        drafts: Provider 或离线抽取器返回的结构化候选。

    Returns:
        可进入确定性治理的原顺序候选元组。

    Raises:
        MemoryContractError: 输出引用越界证据、重复候选或超过安全上限。
    """
    if request.prompt_version != CANDIDATE_PROMPT_VERSION:
        raise MemoryContractError("candidate prompt version is unsupported")
    if request.schema_version != CANDIDATE_EXTRACTOR_SCHEMA_VERSION:
        raise MemoryContractError("candidate extractor schema is unsupported")
    if len(drafts) > 12:
        raise MemoryContractError("candidate extractor returned too many drafts")
    allowed_message_ids = {item.message_id for item in request.messages}
    fingerprints: set[tuple[str, str, str]] = set()
    for draft in drafts:
        if any(item.message_id not in allowed_message_ids for item in draft.evidence):
            raise MemoryContractError("candidate evidence falls outside the frozen user input")
        fingerprint = (
            draft.kind.value,
            draft.category,
            draft.normalized_key,
        )
        if fingerprint in fingerprints:
            raise MemoryContractError("candidate extractor returned duplicate drafts")
        fingerprints.add(fingerprint)
    return drafts
