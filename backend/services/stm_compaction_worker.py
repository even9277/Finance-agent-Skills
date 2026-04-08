"""Background worker for async STM compaction."""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import text

from backend.config import settings
from backend.db.database import AsyncSessionFactory
from backend.db.models import Message, Session, SessionSummary, StmCompactionTask
from backend.services.stm_context_service import refresh_session_context_metrics


async def _claim_next_task() -> int | None:
    async with AsyncSessionFactory() as db:
        if "postgresql" in settings.database_url:
            result = await db.execute(
                text(
                    """
                    WITH picked AS (
                        SELECT id
                        FROM stm_compaction_tasks
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE stm_compaction_tasks t
                    SET status = 'running', started_at = :started_at
                    FROM picked
                    WHERE t.id = picked.id
                    RETURNING t.id
                    """
                ),
                {"started_at": datetime.utcnow()},
            )
            row = result.first()
            if row:
                task = await db.get(StmCompactionTask, int(row[0]))
                if task:
                    session = await db.get(Session, task.session_id)
                    if session:
                        session.compression_status = "running"
            await db.commit()
            return int(row[0]) if row else None

        result = await db.execute(
            text(
                """
                SELECT id
                FROM stm_compaction_tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
        )
        row = result.first()
        if not row:
            return None
        task_id = int(row[0])
        await db.execute(
            text(
                """
                UPDATE stm_compaction_tasks
                SET status = 'running', started_at = :started_at
                WHERE id = :task_id AND status = 'pending'
                """
            ),
            {"task_id": task_id, "started_at": datetime.utcnow()},
        )
        task = await db.get(StmCompactionTask, task_id)
        if task:
            session = await db.get(Session, task.session_id)
            if session:
                session.compression_status = "running"
        await db.commit()
        return task_id


async def _finish_task(task_id: int, *, status: str, error_msg: str = "") -> None:
    async with AsyncSessionFactory() as db:
        task = await db.get(StmCompactionTask, task_id)
        if task:
            session = await db.get(Session, task.session_id)
            if session:
                session.compression_status = "idle" if status != "running" else "running"
        await db.execute(
            text(
                """
                UPDATE stm_compaction_tasks
                SET status = :status,
                    error_msg = :error_msg,
                    finished_at = :finished_at
                WHERE id = :task_id
                """
            ),
            {
                "task_id": task_id,
                "status": status,
                "error_msg": error_msg,
                "finished_at": datetime.utcnow(),
            },
        )
        await db.commit()


async def _retry_task(task_id: int, *, retry_count: int, error_msg: str = "") -> None:
    status = "failed" if retry_count >= int(settings.stm_worker_max_retries) else "pending"
    async with AsyncSessionFactory() as db:
        task = await db.get(StmCompactionTask, task_id)
        if task:
            session = await db.get(Session, task.session_id)
            if session:
                session.compression_status = "failed" if status == "failed" else "queued"
        await db.execute(
            text(
                """
                UPDATE stm_compaction_tasks
                SET status = :status,
                    retry_count = :retry_count,
                    error_msg = :error_msg,
                    finished_at = CASE WHEN :status = 'failed' THEN :finished_at ELSE finished_at END
                WHERE id = :task_id
                """
            ),
            {
                "task_id": task_id,
                "status": status,
                "retry_count": retry_count,
                "error_msg": error_msg,
                "finished_at": datetime.utcnow(),
            },
        )
        await db.commit()


async def _process_task(task_id: int) -> None:
    from backend.services import chat_service

    async with AsyncSessionFactory() as db:
        task = await db.get(StmCompactionTask, task_id)
        if not task:
            return

        session = await db.get(Session, task.session_id)
        if not session:
            await _finish_task(task_id, status="cancelled", error_msg="session_not_found")
            return

        if int(session.summary_version or 0) != int(task.summary_version_before or 0):
            session.compression_status = "idle"
            await db.commit()
            await _finish_task(task_id, status="cancelled", error_msg="summary_version_changed")
            return

        result = await db.execute(
            text(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE session_id = :session_id
                  AND is_compressed = false
                  AND (:cutoff_message_id IS NULL OR id <= :cutoff_message_id)
                ORDER BY created_at ASC
                """
            ),
            {"session_id": task.session_id, "cutoff_message_id": task.cutoff_message_id},
        )
        rows = result.fetchall()
        if not rows:
            session.compression_status = "idle"
            await db.commit()
            await _finish_task(task_id, status="done", error_msg="")
            return

        old_summary = session.running_summary or ""
        compress_parts: list[str] = []
        if old_summary.strip():
            compress_parts.append(f"【已有摘要】\n{old_summary}")
        for row in rows:
            compress_parts.append(f"[{row.role}]: {str(row.content)[:800]}")

        from langchain_core.messages import HumanMessage, SystemMessage

        llm = chat_service._get_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(content=chat_service._SUMMARIZE_CONVERSATION_PROMPT),
                HumanMessage(content=f"请压缩以下对话历史：\n\n{chr(10).join(compress_parts)}"),
            ]
        )
        new_summary = response.content.strip()

        compressed_user_count = sum(1 for row in rows if row.role == "user")
        compressed_assistant_count = sum(1 for row in rows if row.role == "assistant")
        start_message_id = min(int(row.id) for row in rows)
        end_message_id = max(int(row.id) for row in rows)
        start_created_at = rows[0].created_at
        end_created_at = rows[-1].created_at

        update_result = await db.execute(
            text(
                """
                UPDATE messages
                SET is_compressed = true
                WHERE session_id = :session_id
                  AND is_compressed = false
                  AND (:cutoff_message_id IS NULL OR id <= :cutoff_message_id)
                RETURNING id
                """
            ),
            {"session_id": task.session_id, "cutoff_message_id": task.cutoff_message_id},
        )
        compressed_ids = [int(row[0]) for row in update_result.fetchall()]
        total_result = await db.execute(
            text("SELECT COUNT(*) FROM messages WHERE session_id = :session_id"),
            {"session_id": task.session_id},
        )
        total_message_count = int(total_result.scalar() or 0)

        session.running_summary = new_summary
        session.last_compress_at = datetime.utcnow()
        session.summary_version = int(session.summary_version or 0) + 1
        session.compression_status = "idle"

        db.add(
            SessionSummary(
                session_id=task.session_id,
                summary=new_summary,
                compressed_message_count=len(compressed_ids),
                total_message_count=total_message_count,
                compressed_user_count=compressed_user_count,
                compressed_assistant_count=compressed_assistant_count,
                start_message_id=start_message_id,
                end_message_id=end_message_id,
                start_created_at=start_created_at,
                end_created_at=end_created_at,
            )
        )
        await refresh_session_context_metrics(db, session)
        await db.commit()
        if settings.enable_memory and session.user_id:
            await chat_service._extract_from_summary(
                session_id=task.session_id,
                user_id=session.user_id,
                summary=new_summary,
            )
        await _finish_task(task_id, status="done")


async def stm_compaction_worker_loop(stop_event: asyncio.Event | None = None) -> None:
    while True:
        if stop_event and stop_event.is_set():
            return
        try:
            for _ in range(int(settings.stm_worker_batch_size)):
                task_id = await _claim_next_task()
                if task_id is None:
                    break
                try:
                    await _process_task(task_id)
                except Exception as exc:  # pragma: no cover - defensive worker path
                    async with AsyncSessionFactory() as db:
                        task = await db.get(StmCompactionTask, task_id)
                        retry_count = int((task.retry_count or 0) + 1) if task else 1
                    await _retry_task(task_id, retry_count=retry_count, error_msg=str(exc)[:1000])
        except asyncio.CancelledError:
            raise
        await asyncio.sleep(int(settings.stm_worker_interval_sec))
