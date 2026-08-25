"""消费统一 Memory Outbox 的 Rolling Summary 后台 Worker。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.memory.summary import (
    SummaryDraft,
    SummaryModelPort,
    SummaryRequest,
    SummarySourceMessage,
    SummaryValidationError,
    validate_summary_draft,
)
from backend.application.memory.candidates import CANDIDATE_PROMPT_VERSION
from backend.config import settings
from backend.db.database import AsyncSessionFactory
from backend.db.models import (
    MemoryOutboxTaskRow,
    MemorySummaryMetadataRow,
    MemoryWorkingStateRow,
    Message,
    Session,
    SessionSummary,
)
from backend.services.stm_context_service import refresh_session_context_metrics
from backend.services.token_counter import count_text_tokens
from src.memory.contracts import (
    MEMORY_SCHEMA_VERSION,
    CandidateExtractPayload,
    MemoryErrorCode,
    OutboxTaskKind,
    OutboxTaskStatus,
    SummaryCompactPayload,
    SummaryStatus,
    build_candidate_outbox_key,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ClaimedTask:
    """携带一次领取独有的 fencing token；空 token 表示已清理耗尽任务。"""

    task_id: str
    lease_token: str
    trace_id: str | None


class _ApplyStatus(StrEnum):
    """区分摘要写入、版本过期和 lease 所有权丢失。"""

    APPLIED = "APPLIED"
    STALE = "STALE"
    LEASE_LOST = "LEASE_LOST"


class _SummaryProviderCallError(RuntimeError):
    """标记模型 Provider 调用失败，避免把数据库/编程错误错误归因给模型。"""


@dataclass(frozen=True, slots=True)
class _CompactionInput:
    """保存一次模型调用所需的冻结、脱离数据库会话的输入。"""

    task_id: str
    lease_token: str
    trace_id: str | None
    payload: SummaryCompactPayload
    previous_summary: str
    messages: tuple[SummarySourceMessage, ...]


class SummaryCompactionWorker:
    """以有限重试和版本门控执行单一 Rolling Summary 任务。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        model: SummaryModelPort,
        worker_id: str,
        max_attempts: int,
        lease_seconds: int = 60,
    ) -> None:
        if not worker_id.strip() or max_attempts < 1 or lease_seconds < 1:
            raise ValueError("worker_id, max_attempts and lease_seconds must be valid")
        self._session_factory = session_factory
        self._model = model
        self._worker_id = worker_id
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    async def process_next(self) -> bool:
        """领取并处理一个任务；队列为空时返回 `False`。"""
        claim = await self._claim_next()
        if claim is None:
            return False
        if not claim.lease_token:
            return True
        task_id = claim.task_id
        started = datetime.now(UTC)
        try:
            compaction_input = await self._load_input(task_id, claim.lease_token)
            if compaction_input is None:
                return True
            request = SummaryRequest(
                session_id=compaction_input.payload.session_id,
                previous_summary=compaction_input.previous_summary,
                messages=compaction_input.messages,
                source_start_message_id=compaction_input.payload.source_start_message_id,
                source_end_message_id=compaction_input.payload.source_end_message_id,
                prompt_version=compaction_input.payload.prompt_version,
            )
            try:
                draft = await self._model.summarize(request)
            except Exception as exc:
                raise _SummaryProviderCallError("summary provider call failed") from exc
            validate_summary_draft(
                draft,
                expected_start_message_id=request.source_start_message_id,
                expected_end_message_id=request.source_end_message_id,
                expected_message_count=len(request.messages),
                protected_tail_start_message_id=(
                    compaction_input.payload.protected_tail_start_message_id
                ),
            )
            apply_status = await self._apply_draft(compaction_input, draft)
            if apply_status is not _ApplyStatus.APPLIED:
                error_code = (
                    MemoryErrorCode.VERSION_CONFLICT
                    if apply_status is _ApplyStatus.STALE
                    else MemoryErrorCode.TASK_LEASE_CONFLICT
                )
                logger.info(
                    "memory.compact task_id=%s trace_id=%s stage=%s status=%s "
                    "elapsed_ms=%d error_code=%s",
                    task_id,
                    compaction_input.trace_id,
                    "memory.compact",
                    "SKIPPED",
                    int((datetime.now(UTC) - started).total_seconds() * 1000),
                    error_code.value,
                )
                return True
            logger.info(
                "memory.compact task_id=%s trace_id=%s stage=%s status=%s elapsed_ms=%d "
                "summary_version=%d source_message_count=%d",
                task_id,
                compaction_input.trace_id,
                "memory.compact",
                "SUCCEEDED",
                int((datetime.now(UTC) - started).total_seconds() * 1000),
                compaction_input.payload.expected_summary_version + 1,
                compaction_input.payload.source_message_count,
            )
        except Exception as exc:
            recorded = await self._record_failure(task_id, claim.lease_token, exc)
            logger.warning(
                "memory.compact task_id=%s trace_id=%s stage=%s status=%s elapsed_ms=%d "
                "error_code=%s error_type=%s",
                task_id,
                claim.trace_id,
                "memory.compact",
                "FAILED" if recorded else "SKIPPED",
                int((datetime.now(UTC) - started).total_seconds() * 1000),
                _error_code(exc).value,
                type(exc).__name__,
            )
        return True

    async def _claim_next(self) -> _ClaimedTask | None:
        """以数据库行锁领取一个到期的摘要任务。"""
        now = _utc_naive()
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.task_kind
                    == OutboxTaskKind.SUMMARY_COMPACT.value,
                    or_(
                        and_(
                            MemoryOutboxTaskRow.status.in_(
                                (
                                    OutboxTaskStatus.PENDING.value,
                                    OutboxTaskStatus.RETRY.value,
                                )
                            ),
                            MemoryOutboxTaskRow.available_at <= now,
                        ),
                        and_(
                            MemoryOutboxTaskRow.status
                            == OutboxTaskStatus.PROCESSING.value,
                            MemoryOutboxTaskRow.lease_expires_at.is_not(None),
                            MemoryOutboxTaskRow.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(MemoryOutboxTaskRow.created_at, MemoryOutboxTaskRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if task is None:
                return None
            if (
                task.status == OutboxTaskStatus.PROCESSING.value
                and int(task.attempt_count or 0) >= self._max_attempts
            ):
                task.status = OutboxTaskStatus.DEAD_LETTER.value
                task.last_error_code = MemoryErrorCode.TASK_LEASE_CONFLICT.value
                task.completed_at = now
                task.lease_owner = None
                task.lease_expires_at = None
                if task.session_id:
                    session = await db.get(Session, task.session_id)
                    if session is not None:
                        session.compression_status = "failed"
                await db.commit()
                logger.warning(
                    "memory.compact task_id=%s trace_id=%s stage=%s status=%s "
                    "error_code=%s",
                    task.id,
                    task.trace_id,
                    "memory.compact",
                    "FAILED",
                    MemoryErrorCode.TASK_LEASE_CONFLICT.value,
                )
                return _ClaimedTask(
                    task_id=task.id,
                    lease_token="",
                    trace_id=task.trace_id,
                )
            lease_token = f"{self._worker_id}:{uuid.uuid4().hex}"
            task.status = OutboxTaskStatus.PROCESSING.value
            task.attempt_count = int(task.attempt_count or 0) + 1
            task.lease_owner = lease_token
            task.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            if task.session_id:
                session = await db.get(Session, task.session_id)
                if session is not None:
                    session.compression_status = "running"
            await db.commit()
            return _ClaimedTask(
                task_id=task.id,
                lease_token=lease_token,
                trace_id=task.trace_id,
            )

    async def _load_input(
        self,
        task_id: str,
        lease_token: str,
    ) -> _CompactionInput | None:
        """校验任务归属、版本和冻结消息边界，然后释放数据库连接。"""
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.id == task_id,
                    MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                    MemoryOutboxTaskRow.lease_owner == lease_token,
                    MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
                )
                .with_for_update()
            )
            if task is None:
                return None
            payload = _summary_payload(task.payload_json)
            _validate_summary_task_identity(task, payload)
            session = await db.get(Session, payload.session_id)
            if session is None or session.user_id != task.user_id:
                raise SummaryValidationError("summary task session ownership is invalid")
            if int(session.summary_version or 0) != payload.expected_summary_version:
                await self._cancel_stale(db, task, session, lease_token)
                return None
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(
                            Message.session_id == payload.session_id,
                            Message.is_compressed.is_(False),
                            Message.id >= payload.source_start_message_id,
                            Message.id <= payload.source_end_message_id,
                        )
                        .order_by(Message.id)
                    )
                )
                .scalars()
                .all()
            )
            observed_ids = tuple(row.id for row in rows)
            if (
                len(rows) != payload.source_message_count
                or not observed_ids
                or observed_ids[0] != payload.source_start_message_id
                or observed_ids[-1] != payload.source_end_message_id
            ):
                raise SummaryValidationError("summary source messages no longer match task")
            protected_tail_start = await db.scalar(
                select(Message.id)
                .where(
                    Message.session_id == payload.session_id,
                    Message.is_compressed.is_(False),
                    Message.id > payload.source_end_message_id,
                )
                .order_by(Message.id)
                .limit(1)
            )
            if protected_tail_start != payload.protected_tail_start_message_id:
                raise SummaryValidationError(
                    "summary protected raw tail no longer matches task"
                )
            return _CompactionInput(
                task_id=task_id,
                lease_token=lease_token,
                trace_id=task.trace_id,
                payload=payload,
                previous_summary=session.running_summary or "",
                messages=tuple(
                    SummarySourceMessage(
                        message_id=row.id,
                        role=row.role,
                        content=row.content,
                    )
                    for row in rows
                ),
            )

    async def _apply_draft(
        self,
        compaction_input: _CompactionInput,
        draft: SummaryDraft,
    ) -> _ApplyStatus:
        """以摘要版本 CAS 写入结果，并用 lease token 阻断旧 Worker。"""
        payload = compaction_input.payload
        target_version = payload.expected_summary_version + 1
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.id == compaction_input.task_id,
                    MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                    MemoryOutboxTaskRow.lease_owner == compaction_input.lease_token,
                    MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
                )
                .with_for_update()
            )
            if task is None:
                return _ApplyStatus.LEASE_LOST
            _validate_summary_task_identity(task, payload)
            session = await db.get(Session, payload.session_id)
            if session is None:
                raise SummaryValidationError("summary task or session disappeared")
            if int(session.summary_version or 0) != payload.expected_summary_version:
                await self._cancel_stale(
                    db,
                    task,
                    session,
                    compaction_input.lease_token,
                )
                return _ApplyStatus.STALE
            rows = list(
                (
                    await db.execute(
                        select(Message)
                        .where(
                            Message.session_id == payload.session_id,
                            Message.is_compressed.is_(False),
                            Message.id >= payload.source_start_message_id,
                            Message.id <= payload.source_end_message_id,
                        )
                        .order_by(Message.id)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            if len(rows) != payload.source_message_count:
                raise SummaryValidationError("summary source changed before CAS write")
            protected_tail_start = await db.scalar(
                select(Message.id)
                .where(
                    Message.session_id == payload.session_id,
                    Message.is_compressed.is_(False),
                    Message.id > payload.source_end_message_id,
                )
                .order_by(Message.id)
                .limit(1)
                .with_for_update()
            )
            if protected_tail_start != payload.protected_tail_start_message_id:
                raise SummaryValidationError(
                    "summary protected raw tail changed before CAS write"
                )
            total_message_count = int(
                await db.scalar(
                    select(func.count(Message.id)).where(
                        Message.session_id == payload.session_id
                    )
                )
                or 0
            )
            snapshot = SessionSummary(
                session_id=payload.session_id,
                summary=draft.summary.strip(),
                compressed_message_count=len(rows),
                total_message_count=total_message_count,
                compressed_user_count=sum(row.role == "user" for row in rows),
                compressed_assistant_count=sum(row.role == "assistant" for row in rows),
                start_message_id=rows[0].id,
                end_message_id=rows[-1].id,
                start_created_at=rows[0].created_at,
                end_created_at=rows[-1].created_at,
            )
            db.add(snapshot)
            await db.flush()
            result = await db.execute(
                update(Session)
                .where(
                    Session.id == payload.session_id,
                    Session.summary_version == payload.expected_summary_version,
                )
                .values(
                    running_summary=draft.summary.strip(),
                    summary_version=target_version,
                    last_compress_at=_utc_naive(),
                    compression_status="idle",
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                await db.rollback()
                cancelled = await self._cancel_stale_after_rollback(
                    compaction_input.task_id,
                    compaction_input.lease_token,
                )
                return (
                    _ApplyStatus.STALE
                    if cancelled
                    else _ApplyStatus.LEASE_LOST
                )
            for row in rows:
                row.is_compressed = True
            output_tokens, _ = count_text_tokens(draft.summary)
            metadata = await db.scalar(
                select(MemorySummaryMetadataRow).where(
                    MemorySummaryMetadataRow.session_id == payload.session_id,
                    MemorySummaryMetadataRow.summary_version == target_version,
                )
            )
            if metadata is None:
                metadata = MemorySummaryMetadataRow(
                    session_id=payload.session_id,
                    summary_version=target_version,
                    status=SummaryStatus.SUCCEEDED.value,
                    schema_version=MEMORY_SCHEMA_VERSION,
                )
                db.add(metadata)
            metadata.summary_id = snapshot.id
            metadata.status = SummaryStatus.SUCCEEDED.value
            metadata.source_start_message_id = payload.source_start_message_id
            metadata.source_end_message_id = payload.source_end_message_id
            metadata.source_message_count = payload.source_message_count
            metadata.input_token_estimate = payload.input_token_estimate
            metadata.output_token_count = output_tokens
            metadata.prompt_version = payload.prompt_version
            if settings.enable_memory:
                state_version = int(
                    await db.scalar(
                        select(MemoryWorkingStateRow.state_version).where(
                            MemoryWorkingStateRow.session_id == payload.session_id
                        )
                    )
                    or 0
                )
                candidate_payload = CandidateExtractPayload(
                    session_id=payload.session_id,
                    expected_summary_version=target_version,
                    expected_state_version=state_version,
                    source_start_message_id=payload.source_start_message_id,
                    source_end_message_id=payload.source_end_message_id,
                    prompt_version=CANDIDATE_PROMPT_VERSION,
                )
                idempotency_key = build_candidate_outbox_key(
                    payload.session_id,
                    target_version,
                )
                existing_candidate_task = await db.scalar(
                    select(MemoryOutboxTaskRow.id).where(
                        MemoryOutboxTaskRow.user_id == task.user_id,
                        MemoryOutboxTaskRow.idempotency_key == idempotency_key,
                    )
                )
                if existing_candidate_task is None:
                    db.add(
                        MemoryOutboxTaskRow(
                            user_id=task.user_id,
                            session_id=payload.session_id,
                            aggregate_type="chat_summary",
                            aggregate_id=payload.session_id,
                            task_kind=OutboxTaskKind.CANDIDATE_EXTRACT.value,
                            payload_json=asdict(candidate_payload),
                            status=OutboxTaskStatus.PENDING.value,
                            idempotency_key=idempotency_key,
                            schema_version=MEMORY_SCHEMA_VERSION,
                            trace_id=task.trace_id,
                            attempt_count=0,
                        )
                    )
            task.status = OutboxTaskStatus.SUCCEEDED.value
            task.completed_at = _utc_naive()
            task.lease_owner = None
            task.lease_expires_at = None
            task.last_error_code = None
            await db.flush()
            await db.refresh(session)
            await refresh_session_context_metrics(db, session)
            await db.commit()
            # 摘要版本已权威提交后再失效派生尾窗；Redis 故障不得改变任务终态。
            from backend.infrastructure.memory.runtime import get_memory_cache

            cache = get_memory_cache()
            if cache is not None:
                try:
                    await cache.invalidate_context(task.user_id, payload.session_id)
                except Exception as exc:
                    logger.warning(
                        "memory_cache_invalidate_failed trace_id=%s stage=%s status=%s "
                        "error_code=%s error_type=%s",
                        compaction_input.trace_id,
                        "memory.cache.invalidate",
                        "DEGRADED",
                        "UNAVAILABLE",
                        type(exc).__name__,
                    )
            return _ApplyStatus.APPLIED

    async def _cancel_stale_after_rollback(
        self,
        task_id: str,
        lease_token: str,
    ) -> bool:
        """在摘要 CAS 回滚后使用新事务记录 stale 终态。"""
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.id == task_id,
                    MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                    MemoryOutboxTaskRow.lease_owner == lease_token,
                    MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
                )
                .with_for_update()
            )
            if task is None:
                return False
            payload = _summary_payload(task.payload_json)
            session = await db.get(Session, payload.session_id)
            if session is None:
                raise SummaryValidationError("stale summary session disappeared")
            await self._cancel_stale(db, task, session, lease_token)
            return True

    async def _cancel_stale(
        self,
        db: AsyncSession,
        task: MemoryOutboxTaskRow,
        session: Session,
        lease_token: str,
    ) -> None:
        """将落后任务标为取消，保留当前 last-good 摘要。"""
        if (
            task.status != OutboxTaskStatus.PROCESSING.value
            or task.lease_owner != lease_token
        ):
            raise SummaryValidationError("summary lease ownership changed")
        payload = _summary_payload(task.payload_json)
        target_version = payload.expected_summary_version + 1
        metadata = await db.scalar(
            select(MemorySummaryMetadataRow).where(
                MemorySummaryMetadataRow.session_id == payload.session_id,
                MemorySummaryMetadataRow.summary_version == target_version,
            )
        )
        if metadata is None:
            db.add(
                MemorySummaryMetadataRow(
                    session_id=payload.session_id,
                    summary_version=target_version,
                    status=SummaryStatus.STALE.value,
                    source_start_message_id=payload.source_start_message_id,
                    source_end_message_id=payload.source_end_message_id,
                    source_message_count=payload.source_message_count,
                    input_token_estimate=payload.input_token_estimate,
                    output_token_count=0,
                    prompt_version=payload.prompt_version,
                    schema_version=MEMORY_SCHEMA_VERSION,
                )
            )
        task.status = OutboxTaskStatus.CANCELLED.value
        task.last_error_code = MemoryErrorCode.VERSION_CONFLICT.value
        task.completed_at = _utc_naive()
        task.lease_owner = None
        task.lease_expires_at = None
        session.compression_status = "idle"
        await db.commit()

    async def _record_failure(
        self,
        task_id: str,
        lease_token: str,
        exc: Exception,
    ) -> bool:
        """记录有限重试或死信状态，不保存原始模型响应。"""
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.id == task_id,
                    MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                    MemoryOutboxTaskRow.lease_owner == lease_token,
                    MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
                )
                .with_for_update()
            )
            if task is None:
                return False
            payload: SummaryCompactPayload | None = None
            try:
                payload = _summary_payload(task.payload_json)
                _validate_summary_task_identity(task, payload)
            except SummaryValidationError:
                # 损坏的持久任务不可通过重试自愈，必须直接进入可检查终态。
                payload = None
            error_code = _error_code(exc)
            terminal = (
                error_code is MemoryErrorCode.INVALID_CONTRACT
                or int(task.attempt_count or 0) >= self._max_attempts
            )
            task.status = (
                OutboxTaskStatus.DEAD_LETTER.value
                if terminal
                else OutboxTaskStatus.RETRY.value
            )
            task.last_error_code = error_code.value
            task.lease_owner = None
            task.lease_expires_at = None
            task.available_at = _utc_naive() + timedelta(
                seconds=min(30, 2 ** int(task.attempt_count or 1))
            )
            task.completed_at = _utc_naive() if terminal else None
            session_id = payload.session_id if payload is not None else task.session_id
            session = await db.get(Session, session_id) if session_id else None
            if session is not None:
                session.compression_status = "failed" if terminal else "queued"
            if payload is None:
                await db.commit()
                return True
            target_version = payload.expected_summary_version + 1
            metadata = await db.scalar(
                select(MemorySummaryMetadataRow).where(
                    MemorySummaryMetadataRow.session_id == payload.session_id,
                    MemorySummaryMetadataRow.summary_version == target_version,
                )
            )
            if metadata is None:
                metadata = MemorySummaryMetadataRow(
                    session_id=payload.session_id,
                    summary_version=target_version,
                    status=SummaryStatus.FAILED.value,
                    source_start_message_id=payload.source_start_message_id,
                    source_end_message_id=payload.source_end_message_id,
                    source_message_count=payload.source_message_count,
                    input_token_estimate=payload.input_token_estimate,
                    output_token_count=0,
                    prompt_version=payload.prompt_version,
                    schema_version=MEMORY_SCHEMA_VERSION,
                )
                db.add(metadata)
            elif metadata.status != SummaryStatus.SUCCEEDED.value:
                metadata.status = SummaryStatus.FAILED.value
            await db.commit()
            return True


def _error_code(exc: Exception) -> MemoryErrorCode:
    if isinstance(exc, SummaryValidationError):
        return MemoryErrorCode.INVALID_CONTRACT
    if isinstance(exc, _SummaryProviderCallError):
        return MemoryErrorCode.PROVIDER_UNAVAILABLE
    return MemoryErrorCode.INTERNAL_ERROR


def _summary_payload(value: dict[str, object]) -> SummaryCompactPayload:
    """把 JSON 列恢复为强类型任务合同，并重新执行领域校验。"""
    try:
        return SummaryCompactPayload(
            session_id=_required_text(value, "session_id"),
            expected_summary_version=_required_int(
                value, "expected_summary_version"
            ),
            source_start_message_id=_required_int(value, "source_start_message_id"),
            source_end_message_id=_required_int(value, "source_end_message_id"),
            source_message_count=_required_int(value, "source_message_count"),
            protected_tail_start_message_id=_required_int(
                value, "protected_tail_start_message_id"
            ),
            input_token_estimate=_required_int(value, "input_token_estimate"),
            prompt_version=_required_text(value, "prompt_version"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SummaryValidationError("summary task payload is invalid") from exc


def _validate_summary_task_identity(
    task: MemoryOutboxTaskRow,
    payload: SummaryCompactPayload,
) -> None:
    """复核持久任务冗余标识，阻断损坏数据跨会话执行。"""
    if (
        task.task_kind != OutboxTaskKind.SUMMARY_COMPACT.value
        or task.aggregate_type != "chat_session"
        or task.session_id != payload.session_id
        or task.aggregate_id != payload.session_id
    ):
        raise SummaryValidationError("summary task persisted identity is inconsistent")


def _required_int(value: dict[str, object], field_name: str) -> int:
    """读取 JSON 整数字段，并拒绝布尔值及隐式字符串转换。"""
    field_value = value[field_name]
    if isinstance(field_value, bool) or not isinstance(field_value, int):
        raise TypeError(f"{field_name} must be an integer")
    return field_value


def _required_text(value: dict[str, object], field_name: str) -> str:
    """读取 JSON 文本字段，避免把错误类型静默字符串化。"""
    field_value = value[field_name]
    if not isinstance(field_value, str):
        raise TypeError(f"{field_name} must be text")
    return field_value


def _utc_naive() -> datetime:
    """返回与现有无时区数据库列兼容的 UTC 时间。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def stm_compaction_worker_loop(stop_event: asyncio.Event | None = None) -> None:
    """启动生产摘要 Worker，空队列时按配置间隔轮询。"""
    worker = build_stm_compaction_worker()
    await run_stm_compaction_worker(worker, stop_event)


def build_stm_compaction_worker() -> SummaryCompactionWorker:
    """同步构造生产 Worker，使 Provider 配置错误在启动阶段可见。"""
    from backend.infrastructure.memory.summary import build_summary_model_provider

    return SummaryCompactionWorker(
        session_factory=cast(async_sessionmaker[AsyncSession], AsyncSessionFactory),
        model=build_summary_model_provider(),
        worker_id="stm-worker",
        max_attempts=int(settings.stm_worker_max_retries),
        lease_seconds=int(settings.stm_worker_lease_sec),
    )


async def run_stm_compaction_worker(
    worker: SummaryCompactionWorker,
    stop_event: asyncio.Event | None = None,
) -> None:
    """轮询一个已完成依赖校验的 Worker，支持生命周期停止信号。"""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        processed = False
        try:
            for _ in range(max(1, int(settings.stm_worker_batch_size))):
                if not await worker.process_next():
                    break
                processed = True
        except Exception as exc:
            # 数据库滚动迁移或瞬时连接失败不应永久终止常驻 Worker。
            logger.warning(
                "memory.compact stage=%s status=%s error_code=%s error_type=%s",
                "memory.compact",
                "FAILED",
                MemoryErrorCode.INTERNAL_ERROR.value,
                type(exc).__name__,
            )
        if not processed:
            await asyncio.sleep(max(1, int(settings.stm_worker_interval_sec)))
