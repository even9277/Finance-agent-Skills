import asyncio
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session, SessionSummary
from backend.services.chat.constants import _STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES
from backend.services.stm_context_service import refresh_session_context_metrics
from backend.services.stm_summary_runtime import run_summary_compaction


_RECENT_MSG_LIMIT = int(settings.stm_keep_recent) + 2  # 保留最近 N+2 条消息作为上下文


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


async def get_or_create_session(
    db: AsyncSession, user_id: str, session_id: Optional[str]
) -> Session:
    """获取已有会话或为用户创建新会话。"""
    if session_id:
        result = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    session = Session(user_id=user_id, mode="chat")
    db.add(session)
    await db.flush()
    return session


async def get_sessions(db: AsyncSession, user_id: str) -> list[Session]:
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id, Session.mode == "chat")
        .order_by(Session.updated_at.desc())
    )
    sessions = list(result.scalars().all())
    metrics_changed = False
    for session in sessions:
        if session.context_updated_at is None:
            await refresh_session_context_metrics(db, session)
            metrics_changed = True
    if metrics_changed:
        await db.commit()
    return sessions


async def get_session_messages(
    db: AsyncSession, session_id: str, user_id: str
) -> list[Message]:
    """获取会话完整消息历史（含已压缩消息，用于前端"查看完整历史"）。"""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return []
    if session.context_updated_at is None:
        await refresh_session_context_metrics(db, session)
        await db.commit()
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, session_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return False
    await db.delete(session)
    await db.commit()
    return True


async def rename_session(
    db: AsyncSession, session_id: str, user_id: str, title: str
) -> bool:
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return False
    session.title = title
    await db.commit()
    return True


async def compress_if_needed(
    db: AsyncSession,
    session_id: str,
    *,
    trigger: str = "fallback_sync_compaction",
    force: bool = False,
) -> Optional[dict]:
    """
    Legacy STM 同步压缩入口。

    当前默认主链路已经切到：
      refresh metrics -> pre_compaction 判定 -> 同步 compaction / fallback

    本函数保留给以下场景使用：
      1. overflow fallback（上下文超限时的应急压缩）
      2. admin/debug repair
      3. emergency compaction

    Phase 2 起，本函数不再自己拼摘要 prompt，而是复用统一的
    `stm_summary_runtime.run_summary_compaction(...)`。
    """
    if not settings.enable_stm:
        return None  # ENABLE_STM=false 时跳过

    session_result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        return None

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.is_compressed == False)  # noqa: E712
        .order_by(Message.created_at)
    )
    uncompressed = list(result.scalars().all())

    if not force and len(uncompressed) < _STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES:
        return None  # 未达阈值，不压缩

    print(
        f"\n[STM-chat] 会话 {session_id[:8]}... 未压缩消息数={len(uncompressed)}，"
        f"触发压缩（fallback 条数阈值={_STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES} force={force}）"
    )
    _chat_service_facade().logger.info(
        "[STM-chat] 触发压缩: session=%s uncompressed_count=%s force=%s trigger=%s",
        session_id,
        len(uncompressed),
        force,
        trigger,
    )

    # Legacy fallback 模式也必须保住最新消息，避免应急压缩后丢掉当前用户问题。
    keep_recent = max(1, int(settings.stm_keep_recent or 0))
    if len(uncompressed) > keep_recent:
        msgs_to_compress = uncompressed[:-keep_recent]
    else:
        msgs_to_compress = uncompressed[:-1]
    if not msgs_to_compress:
        _chat_service_facade().logger.warning(
            "[STM-fallback] 无安全可压缩消息，跳过同步应急压缩: session=%s uncompressed=%s",
            session_id,
            len(uncompressed),
        )
        return None

    try:
        timeout_sec = max(1, int(settings.stm_fallback_compaction_timeout_sec))
        compaction_result = await asyncio.wait_for(
            run_summary_compaction(
                db=db,
                session=session,
                source_rows=msgs_to_compress,
                cutoff_message_id=msgs_to_compress[-1].id if msgs_to_compress else None,
                trigger=trigger,
            ),
            timeout=float(timeout_sec),
        )
    except Exception as exc:
        _chat_service_facade().logger.error(f"[STM-chat] 压缩失败（不影响主流程）: {exc}", exc_info=True)
        print(f"[STM-chat] 压缩失败（不影响主流程）: {exc}")
        return None

    if not compaction_result.compacted:
        _chat_service_facade().logger.warning(
            "[STM-chat] 统一压缩 runtime 未落盘: session=%s reason=%s",
            session_id,
            compaction_result.reason,
        )
        return None

    await db.refresh(session)
    print(
        f"[STM-chat] 压缩完成：{compaction_result.compressed_message_count} 条消息 → "
        f"摘要 {len(compaction_result.summary_text or '')} 字"
    )
    _chat_service_facade().logger.info(
        "[STM-chat] 压缩完成: session=%s compressed=%s/%s summary_len=%s strategy=%s summary_version=%s",
        session_id,
        compaction_result.compressed_message_count,
        compaction_result.total_message_count,
        len(compaction_result.summary_text or ""),
        compaction_result.final_strategy,
        compaction_result.summary_version_after,
    )
    percent = (
        int(round((compaction_result.compressed_message_count / compaction_result.total_message_count) * 100))
        if compaction_result.total_message_count
        else 100
    )
    return {
        "session_id": session_id,
        "summary": compaction_result.summary_text,
        "snapshot_id": None,
        "compressed_message_count": compaction_result.compressed_message_count,
        "total_message_count": compaction_result.total_message_count,
        "percent": max(0, min(100, percent)),
        "reason": compaction_result.reason,
        "final_strategy": compaction_result.final_strategy,
    }


async def get_session_summaries(db: AsyncSession, session_id: str, user_id: str) -> list[SessionSummary]:
    """获取会话的摘要历史（仅返回属于该 user 的会话）。"""
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    if not session_result.scalar_one_or_none():
        return []
    result = await db.execute(
        select(SessionSummary)
        .where(SessionSummary.session_id == session_id)
        .order_by(SessionSummary.created_at.desc())
    )
    return list(result.scalars().all())


async def _build_fallback_chat_messages(
    db: AsyncSession,
    session: Session,
    *,
    memory_system_prompt: str = "",
):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    chat_service = _chat_service_facade()
    lc_messages = [SystemMessage(content=chat_service._CHAT_SYSTEM_PROMPT)]

    if memory_system_prompt:
        lc_messages.append(SystemMessage(content=memory_system_prompt))
        chat_service.logger.info(
            "[LTM-chat] 注入 memory_context: session=%s len=%s",
            session.id[:8],
            len(memory_system_prompt),
        )

    _, _, answer_policy_context = chat_service._resolve_session_summary_contexts(session)
    if settings.enable_stm and answer_policy_context:
        lc_messages.append(SystemMessage(content=answer_policy_context))
        chat_service.logger.info(
            "[STM-chat] 注入 answer_policy_context: session=%s summary_len=%s",
            session.id[:8],
            len(answer_policy_context),
        )

    if settings.enable_stm:
        history_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id, Message.is_compressed == False)  # noqa: E712
            .order_by(Message.created_at.desc())
            .limit(_RECENT_MSG_LIMIT + 1)
        )
    else:
        history_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at.desc())
            .limit(_RECENT_MSG_LIMIT + 1)
        )
    recent_messages = list(reversed(history_result.scalars().all()))

    for msg in recent_messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            lc_messages.append(AIMessage(content=msg.content))

    return lc_messages


async def _force_overflow_recovery_compaction(
    db: AsyncSession,
    session: Session,
    *,
    user_message: str,
    exc: Exception,
) -> bool:
    if not settings.enable_stm:
        return False

    chat_service = _chat_service_facade()
    chat_service.logger.warning(
        "[STM-fallback] 检测到上下文超限，开始同步应急压缩: session=%s user_len=%s error=%s",
        session.id,
        len(user_message or ""),
        str(exc)[:300],
    )
    print(f"[STM-fallback] session={session.id[:8]} 检测到上下文超限，开始同步应急压缩")

    compressed = await chat_service.compress_if_needed(
        db,
        session.id,
        trigger="overflow_fallback_compaction",
        force=True,
    )
    if not compressed:
        try:
            await chat_service.refresh_session_context_metrics(db, session)
            await db.commit()
        except Exception:
            await db.rollback()
        chat_service.logger.warning(
            "[STM-fallback] 应急压缩未执行或无可压缩内容: session=%s",
            session.id,
        )
        return False

    await db.refresh(session)
    await chat_service.refresh_session_context_metrics(db, session)
    await db.commit()
    chat_service.logger.warning(
        "[STM-fallback] 应急压缩完成，准备重试: session=%s compressed=%s strategy=%s",
        session.id,
        compressed.get("compressed_message_count"),
        compressed.get("final_strategy"),
    )
    print(f"[STM-fallback] session={session.id[:8]} 应急压缩完成，准备重试")
    return True
