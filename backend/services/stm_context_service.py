"""STM context metrics (token estimate).

当前默认主链路保留：
1. token 预算驱动的 preflight summary compaction
2. overflow fallback compaction
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session
from backend.schemas.chat import ChatContextWindow
from backend.services.token_counter import (
    count_message_tokens,
    count_text_tokens,
    merge_counting_modes,
)
from src.utils.logging_config import setup_logger

logger = setup_logger("stm_context_service")


def _resolve_budget_baseline() -> tuple[int, int, int]:
    model_window_tokens = max(0, int(settings.chat_context_window_tokens or 0))
    reserved_output_tokens = max(0, int(settings.stm_summary_reserve_tokens_floor or 0))
    soft_threshold_tokens = max(0, int(settings.stm_summary_soft_threshold_tokens or 0))
    overhead_tokens = max(0, int(settings.stm_summary_overhead_tokens or 0))
    working_budget_tokens = max(
        0,
        model_window_tokens - reserved_output_tokens - soft_threshold_tokens - overhead_tokens,
    )
    return model_window_tokens, working_budget_tokens, reserved_output_tokens


def _resolve_budget_status(*, used_tokens: int, working_budget_tokens: int) -> str:
    if working_budget_tokens <= 0:
        return "critical" if used_tokens > 0 else "healthy"
    usage_percent = (used_tokens / working_budget_tokens) * 100
    if usage_percent >= 100:
        return "critical"
    if usage_percent >= 90:
        return "high"
    if usage_percent >= 75:
        return "moderate"
    return "healthy"


def build_context_window_payload(session: Session, *, counting_mode: str | None = None) -> ChatContextWindow:
    used_tokens = max(0, int(session.context_token_count or 0))
    model_window_tokens, working_budget_tokens, reserved_output_tokens = _resolve_budget_baseline()
    budget_tokens = max(0, working_budget_tokens - used_tokens)
    usage_percent = (
        int(round((used_tokens / working_budget_tokens) * 100))
        if working_budget_tokens > 0
        else (100 if used_tokens > 0 else 0)
    )
    mode = counting_mode or "estimated"
    return ChatContextWindow(
        used_tokens=used_tokens,
        budget_tokens=budget_tokens,
        usage_percent=usage_percent,
        counting_mode=mode,
        compression_status=(session.compression_status or "idle"),
        strategy="dynamic_budget",
        updated_at=session.context_updated_at,
        model_window_tokens=model_window_tokens,
        working_budget_tokens=working_budget_tokens,
        reserved_output_tokens=reserved_output_tokens,
        budget_status=_resolve_budget_status(
            used_tokens=used_tokens,
            working_budget_tokens=working_budget_tokens,
        ),
    )


async def refresh_session_context_metrics(db: AsyncSession, session: Session) -> ChatContextWindow:
    result = await db.execute(
        select(Message).where(
            Message.session_id == session.id,
            Message.is_compressed == False,  # noqa: E712
        )
    )
    messages = list(result.scalars().all())
    modes: list[str] = []
    total = 0
    for msg in messages:
        if msg.token_count is None:
            msg.token_count, mode = count_message_tokens(msg.role, msg.content)
            modes.append(mode)
        else:
            _, mode = count_message_tokens(msg.role, msg.content)
            modes.append(mode)
        total += int(msg.token_count or 0)

    summary_tokens, summary_mode = count_text_tokens(session.running_summary or "")
    modes.append(summary_mode)

    session.summary_token_count = summary_tokens
    session.context_token_count = total + summary_tokens
    _, working_budget_tokens, _ = _resolve_budget_baseline()
    session.context_budget_tokens = max(0, working_budget_tokens - int(session.context_token_count or 0))
    session.context_updated_at = datetime.utcnow()
    return build_context_window_payload(session, counting_mode=merge_counting_modes(modes))


async def count_uncompressed_messages(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        select(func.count(Message.id)).where(
            Message.session_id == session_id,
            Message.is_compressed == False,  # noqa: E712
        )
    )
    return int(result.scalar() or 0)


async def choose_cutoff_message_id(db: AsyncSession, session_id: str) -> int | None:
    keep_recent = int(settings.stm_keep_recent)
    result = await db.execute(
        select(Message.id)
        .where(Message.session_id == session_id, Message.is_compressed == False)  # noqa: E712
        .order_by(Message.created_at)
    )
    message_ids = [int(row[0]) for row in result.all()]
    compressible = len(message_ids) - keep_recent
    if compressible <= 0:
        return None
    return message_ids[compressible - 1]

