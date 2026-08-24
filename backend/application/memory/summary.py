"""定义 Rolling Summary 的模型端口与结构化质量门控。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SUMMARY_PROMPT_VERSION = "rolling-summary-v1"


class SummaryValidationError(ValueError):
    """表示模型摘要不满足冻结来源边界或内容质量合同。"""


@dataclass(frozen=True, slots=True)
class SummarySourceMessage:
    """交给摘要模型的单条来源消息。"""

    message_id: int
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    """冻结一次摘要生成请求，不允许模型改写来源边界。"""

    session_id: str
    previous_summary: str
    messages: tuple[SummarySourceMessage, ...]
    source_start_message_id: int
    source_end_message_id: int
    prompt_version: str = SUMMARY_PROMPT_VERSION


@dataclass(frozen=True, slots=True)
class SummaryDraft:
    """摘要模型返回并等待应用层校验的结构化草稿。"""

    summary: str
    source_start_message_id: int
    source_end_message_id: int
    source_message_count: int
    prompt_version: str


class SummaryModelPort(Protocol):
    """隔离具体 LLM SDK 的 Rolling Summary 模型端口。"""

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        """生成结构化摘要；不得持久化或自行重试。"""
        ...


def validate_summary_draft(
    draft: SummaryDraft,
    *,
    expected_start_message_id: int,
    expected_end_message_id: int,
    expected_message_count: int,
    protected_tail_start_message_id: int,
) -> SummaryDraft:
    """校验摘要正文、Prompt 版本和不可跨越的来源边界。

    Raises:
        SummaryValidationError: 草稿为空、版本错误、漏项或越过 protected tail。
    """
    if not draft.summary.strip() or len(draft.summary) > 2_000:
        raise SummaryValidationError("summary text is empty or exceeds 2000 characters")
    if draft.prompt_version != SUMMARY_PROMPT_VERSION:
        raise SummaryValidationError("summary prompt version is unsupported")
    expected = (
        expected_start_message_id,
        expected_end_message_id,
        expected_message_count,
    )
    observed = (
        draft.source_start_message_id,
        draft.source_end_message_id,
        draft.source_message_count,
    )
    if observed != expected:
        if draft.source_end_message_id >= protected_tail_start_message_id:
            raise SummaryValidationError("summary source overlaps protected tail")
        raise SummaryValidationError("summary source boundary does not match the task")
    if draft.source_end_message_id >= protected_tail_start_message_id:
        raise SummaryValidationError("summary source overlaps protected tail")
    return draft
