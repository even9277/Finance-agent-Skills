"""Context budget calculation and async STM compaction enqueue helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session, StmCompactionTask
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


async def has_active_compaction_task(db: AsyncSession, session_id: str) -> bool:
    result = await db.execute(
        select(StmCompactionTask.id).where(
            StmCompactionTask.session_id == session_id,
            StmCompactionTask.status.in_(["pending", "running"]),
        )
    )
    return result.first() is not None


async def maybe_enqueue_compaction(
    db: AsyncSession,
    session: Session,
    *,
    system_prompt: str,
    memory_system_prompt: str = "",
    user_message: str = "",
) -> tuple[ChatContextWindow, bool]:
    context_window = await refresh_session_context_metrics(db, session)
    if not settings.enable_stm:
        return context_window, False

    strategy = settings.stm_compression_strategy
    live_prompt_tokens, counting_mode = calculate_live_prompt_usage(
        session,
        system_prompt=system_prompt,
        memory_system_prompt=memory_system_prompt,
        user_message=user_message,
    )
    context_window = build_context_window_payload(session, counting_mode=counting_mode)

    should_queue = False
    if strategy == "legacy_count":
        uncompressed_count = await count_uncompressed_messages(db, session.id)
        should_queue = uncompressed_count >= int(settings.stm_legacy_count_threshold)
    else:
        budget_tokens = int(session.context_budget_tokens or detect_context_budget_tokens())
        target_tokens = int(round(budget_tokens * float(settings.stm_context_target_ratio)))
        hard_tokens = int(round(budget_tokens * float(settings.stm_context_hard_ratio)))
        should_queue = live_prompt_tokens >= target_tokens or session.context_token_count >= hard_tokens

    if not should_queue:
        session.compression_status = "idle"
        return context_window, False

    if session.compression_status in {"queued", "running"}:
        return build_context_window_payload(session, counting_mode=counting_mode), False

    if await has_active_compaction_task(db, session.id):
        session.compression_status = "queued"
        return build_context_window_payload(session, counting_mode=counting_mode), False

    cutoff_message_id = await choose_cutoff_message_id(db, session.id)
    if cutoff_message_id is None:
        return context_window, False

    session.compression_status = "queued"
    db.add(
        StmCompactionTask(
            session_id=session.id,
            status="pending",
            retry_count=0,
            cutoff_message_id=cutoff_message_id,
            summary_version_before=int(session.summary_version or 0),
            estimated_tokens_before=max(0, int(live_prompt_tokens)),
        )
    )
    return build_context_window_payload(session, counting_mode=counting_mode), True
