"""实现 Rolling Summary 的 OpenAI-compatible 与离线确定性适配器。"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from backend.application.memory.summary import (
    SummaryDraft,
    SummaryModelPort,
    SummaryRequest,
)
from backend.config import settings

_SUMMARY_SYSTEM_PROMPT = """
你是金融对话 Rolling Summary 组件。只总结输入中的用户与助手消息，不新增事实，
不把助手建议改写为用户偏好。保留对话主线、明确实体、用户约束和未完成事项。
仅输出 JSON：{"summary":"..."}，正文不超过 1200 个中文字符。
""".strip()


class OpenAICompatibleSummaryModelProvider:
    """通过统一 Settings 调用 OpenAI-compatible 摘要模型。"""

    def __init__(self) -> None:
        if not all(
            (
                settings.openai_compatible_model,
                settings.openai_compatible_api_key,
                settings.openai_compatible_base_url,
            )
        ):
            raise RuntimeError("summary model configuration is incomplete")
        self._model = ChatOpenAI(
            model=settings.openai_compatible_model,
            api_key=SecretStr(settings.openai_compatible_api_key),
            base_url=settings.openai_compatible_base_url,
            temperature=0.0,
            timeout=float(settings.stm_summary_timeout_sec),
            max_retries=0,
        )

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        """调用模型并把 JSON 输出收敛为冻结边界草稿。"""
        payload = {
            "previous_summary": request.previous_summary,
            "messages": [
                {
                    "message_id": item.message_id,
                    "role": item.role,
                    "content": item.content,
                }
                for item in request.messages
            ],
        }
        response = await self._model.ainvoke(
            (
                SystemMessage(content=_SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            )
        )
        data = json.loads(_response_text(response.content))
        return SummaryDraft(
            summary=str(data.get("summary") or "").strip(),
            source_start_message_id=request.source_start_message_id,
            source_end_message_id=request.source_end_message_id,
            source_message_count=len(request.messages),
            prompt_version=request.prompt_version,
        )


class DeterministicSummaryModelProvider:
    """为离线 CI 生成无网络、可复现且边界一致的摘要。"""

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        """按消息顺序拼接安全截断内容，避免任何外部 Provider 调用。"""
        parts = [request.previous_summary.strip()] if request.previous_summary.strip() else []
        parts.extend(
            f"{item.role}: {item.content.strip()}"
            for item in request.messages
            if item.content.strip()
        )
        return SummaryDraft(
            summary="；".join(parts)[:1_200],
            source_start_message_id=request.source_start_message_id,
            source_end_message_id=request.source_end_message_id,
            source_message_count=len(request.messages),
            prompt_version=request.prompt_version,
        )


def build_summary_model_provider() -> SummaryModelPort:
    """根据类型化配置构造唯一摘要模型端口。"""
    if settings.stm_summary_provider == "deterministic":
        return DeterministicSummaryModelProvider()
    return OpenAICompatibleSummaryModelProvider()


def _response_text(content: object) -> str:
    """归一化 LangChain 文本响应，并移除常见 JSON fence。"""
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
