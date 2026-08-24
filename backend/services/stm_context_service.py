"""计算兼容 API 展示与压缩策略使用的会话 token 指标。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session
from backend.schemas.chat import ChatContextWindow
from backend.services.token_counter import (
    count_message_tokens,
    count_text_tokens,
    detect_context_budget_tokens,
    merge_counting_modes,
)


def build_context_window_payload(session: Session, *, counting_mode: str | None = None) -> ChatContextWindow:
    used_tokens = int(session.context_token_count or 0)
    budget_tokens = int(session.context_budget_tokens or detect_context_budget_tokens())
    usage_percent = int(round((used_tokens / budget_tokens) * 100)) if budget_tokens else 0
    return ChatContextWindow(
        used_tokens=max(0, used_tokens),
        budget_tokens=max(0, budget_tokens),
        usage_percent=max(0, min(100, usage_percent)),
        counting_mode=counting_mode or "estimated",
        compression_status=(session.compression_status or "idle"),
        strategy=settings.stm_compression_strategy,
        updated_at=session.context_updated_at,
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
    session.context_budget_tokens = detect_context_budget_tokens()
    session.context_updated_at = datetime.utcnow()
    return build_context_window_payload(session, counting_mode=merge_counting_modes(modes))


def calculate_live_prompt_usage(
    session: Session,
    *,
    system_prompt: str,
    memory_system_prompt: str = "",
    user_message: str = "",
) -> tuple[int, str]:
    total = int(session.context_token_count or 0)
    modes: list[str] = []

    for text in (system_prompt, memory_system_prompt, user_message):
        tokens, mode = count_text_tokens(text or "")
        total += tokens
        modes.append(mode)

    total += int(settings.stm_response_reserve_tokens or 0)
    total += int(settings.stm_memory_reserve_tokens or 0)
    return total, merge_counting_modes(modes)
