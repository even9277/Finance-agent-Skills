"""消费 INDEX_UPSERT/INDEX_DELETE Outbox，维护可重建语义派生索引。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.memory.retrieval import SemanticMemoryProvider
from backend.application.memory.observability import (
    MemoryObservation,
    MemoryStage,
    MemoryStatus,
    emit_memory_observation,
)
from backend.config import settings
from backend.db.models import (
    MemoryOutboxTaskRow,
    MemoryProviderReferenceRow,
    MemoryRecordRow,
)
from src.memory.contracts import (
    IndexDeletePayload,
    IndexUpsertPayload,
    MemoryRecordStatus,
    OutboxTaskKind,
    OutboxTaskStatus,
    ProviderReferenceStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Claim:
    task_id: str
    lease_token: str


class SemanticIndexWorker:
    """以租约 fencing 和有限重试把权威记录同步到语义 Provider。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        provider: SemanticMemoryProvider,
        worker_id: str = "semantic-index-worker",
        max_attempts: int | None = None,
        lease_seconds: int | None = None,
        provider_timeout_sec: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._worker_id = worker_id
        self._max_attempts = max_attempts or settings.memory_index_worker_max_retries
        self._lease_seconds = lease_seconds or settings.memory_index_worker_lease_sec
        self._provider_timeout_sec = provider_timeout_sec or settings.memory_semantic_timeout_sec

    async def process_next(self) -> bool:
        """处理一条索引任务；队列为空时返回 ``False``。"""
        claim = await self._claim_next()
        if claim is None:
            return False
        try:
            await self._process_claim(claim)
            emit_memory_observation(
                MemoryObservation(
                    stage=MemoryStage.INDEX,
                    status=MemoryStatus.SUCCEEDED,
                    trace_id="",
                    run_id=claim.task_id,
                    reference=claim.task_id,
                )
            )
        except Exception as exc:
            await self._record_failure(claim, exc)
            logger.warning(
                "memory.index stage=memory.index status=FAILED error_code=%s error_type=%s",
                "PROVIDER_UNAVAILABLE",
                type(exc).__name__,
            )
            emit_memory_observation(
                MemoryObservation(
                    stage=MemoryStage.INDEX,
                    status=MemoryStatus.RETRY,
                    trace_id="",
                    run_id=claim.task_id,
                    reference=claim.task_id,
                    error_code=(
                        "INVALID_INDEX_PAYLOAD"
                        if isinstance(exc, ValueError) and str(exc) == "INVALID_INDEX_PAYLOAD"
                        else "PROVIDER_UNAVAILABLE"
                    ),
                )
            )
        return True

    async def run(self, stop_event: asyncio.Event) -> None:
        """持续轮询索引任务，停止信号到达后优雅退出。"""
        while not stop_event.is_set():
            processed_count = 0
            for _ in range(settings.memory_index_worker_batch_size):
                if not await self.process_next():
                    break
                processed_count += 1
            if processed_count == 0:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=settings.memory_index_worker_interval_sec
                    )
                except asyncio.TimeoutError:
                    continue

    async def _claim_next(self) -> _Claim | None:
        now = _utc_naive()
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.task_kind.in_(
                        (OutboxTaskKind.INDEX_UPSERT.value, OutboxTaskKind.INDEX_DELETE.value)
                    ),
                    or_(
                        and_(
                            MemoryOutboxTaskRow.status.in_(
                                (OutboxTaskStatus.PENDING.value, OutboxTaskStatus.RETRY.value)
                            ),
                            MemoryOutboxTaskRow.available_at <= now,
                        ),
                        and_(
                            MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
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
            lease = f"{self._worker_id}:{uuid.uuid4().hex}"
            task.status = OutboxTaskStatus.PROCESSING.value
            task.attempt_count = int(task.attempt_count or 0) + 1
            task.lease_owner = lease
            task.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            await db.commit()
            return _Claim(task.id, lease)

    async def _process_claim(self, claim: _Claim) -> None:
        async with self._session_factory() as db:
            task = await self._leased_task(db, claim)
            if task is None:
                return
            if task.task_kind == OutboxTaskKind.INDEX_UPSERT.value:
                payload = _parse_upsert(task.payload_json)
                record = await db.scalar(
                    select(MemoryRecordRow).where(
                        MemoryRecordRow.id == payload.record_id,
                        MemoryRecordRow.user_id == payload.user_id,
                    )
                )
                if (
                    record is None
                    or record.status != MemoryRecordStatus.ACTIVE.value
                    or record.version != payload.memory_version
                    or (record.expires_at is not None and record.expires_at <= _utc_naive())
                ):
                    task.status = OutboxTaskStatus.SUCCEEDED.value
                    task.completed_at = _utc_naive()
                    task.lease_owner = None
                    task.lease_expires_at = None
                    await db.commit()
                    return
                old_refs = list(
                    (
                        await db.execute(
                            select(MemoryProviderReferenceRow).where(
                                MemoryProviderReferenceRow.user_id == payload.user_id,
                                MemoryProviderReferenceRow.memory_record_id == payload.record_id,
                                MemoryProviderReferenceRow.provider == self._provider.name,
                                MemoryProviderReferenceRow.status
                                == ProviderReferenceStatus.ACTIVE.value,
                                MemoryProviderReferenceRow.memory_version < payload.memory_version,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for reference in old_refs:
                    await asyncio.wait_for(
                        self._provider.delete(
                            user_id=payload.user_id,
                            provider_record_id=reference.provider_record_id,
                        ),
                        timeout=self._provider_timeout_sec,
                    )
                    reference.status = ProviderReferenceStatus.STALE.value
                provider_id = await asyncio.wait_for(
                    self._provider.upsert(
                        user_id=payload.user_id,
                        record_id=payload.record_id,
                        memory_version=payload.memory_version,
                        category=payload.category,
                        content=payload.content,
                        metadata={
                            "memory_record_id": payload.record_id,
                            "memory_version": payload.memory_version,
                            "policy_version": payload.policy_version,
                        },
                    ),
                    timeout=self._provider_timeout_sec,
                )
                if not await self._lease_is_current(db, claim):
                    await db.rollback()
                    return
                reference = await db.scalar(
                    select(MemoryProviderReferenceRow).where(
                        MemoryProviderReferenceRow.user_id == payload.user_id,
                        MemoryProviderReferenceRow.provider == self._provider.name,
                        MemoryProviderReferenceRow.provider_record_id == provider_id,
                    )
                )
                if reference is None:
                    reference = MemoryProviderReferenceRow(
                        user_id=payload.user_id,
                        memory_record_id=payload.record_id,
                        provider=self._provider.name,
                        provider_record_id=provider_id,
                        memory_version=payload.memory_version,
                        status=ProviderReferenceStatus.ACTIVE.value,
                        schema_version=settings.memory_index_schema_version,
                        last_synced_at=_utc_naive(),
                    )
                    db.add(reference)
                else:
                    reference.memory_record_id = payload.record_id
                    reference.memory_version = payload.memory_version
                    reference.status = ProviderReferenceStatus.ACTIVE.value
                    reference.schema_version = settings.memory_index_schema_version
                    reference.last_synced_at = _utc_naive()
                    reference.last_error_code = None
            else:
                payload = _parse_delete(task.payload_json)
                references = list(
                    (
                        await db.execute(
                            select(MemoryProviderReferenceRow).where(
                                MemoryProviderReferenceRow.user_id == payload.user_id,
                                MemoryProviderReferenceRow.memory_record_id == payload.record_id,
                                MemoryProviderReferenceRow.provider == self._provider.name,
                                MemoryProviderReferenceRow.status.in_(
                                    (
                                        ProviderReferenceStatus.ACTIVE.value,
                                        ProviderReferenceStatus.DELETE_PENDING.value,
                                    )
                                ),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for reference in references:
                    reference.status = ProviderReferenceStatus.DELETE_PENDING.value
                    await asyncio.wait_for(
                        self._provider.delete(
                            user_id=payload.user_id,
                            provider_record_id=reference.provider_record_id,
                        ),
                        timeout=self._provider_timeout_sec,
                    )
                    if not await self._lease_is_current(db, claim):
                        await db.rollback()
                        return
                    reference.status = ProviderReferenceStatus.DELETED.value
                    reference.last_synced_at = _utc_naive()
            task.status = OutboxTaskStatus.SUCCEEDED.value
            task.completed_at = _utc_naive()
            task.lease_owner = None
            task.lease_expires_at = None
            task.last_error_code = None
            await db.commit()

    async def _record_failure(self, claim: _Claim, exc: Exception) -> None:
        async with self._session_factory() as db:
            task = await self._leased_task(db, claim)
            if task is None:
                return
            exhausted = int(task.attempt_count or 0) >= self._max_attempts
            task.status = (
                OutboxTaskStatus.DEAD_LETTER.value if exhausted else OutboxTaskStatus.RETRY.value
            )
            task.last_error_code = (
                "INVALID_INDEX_PAYLOAD"
                if isinstance(exc, ValueError) and str(exc) == "INVALID_INDEX_PAYLOAD"
                else "PROVIDER_UNAVAILABLE"
            )
            task.available_at = _utc_naive() + timedelta(
                seconds=min(60, 2 ** max(1, int(task.attempt_count or 1)))
            )
            task.completed_at = _utc_naive() if exhausted else None
            task.lease_owner = None
            task.lease_expires_at = None
            await db.commit()

    async def _leased_task(
        self,
        db: AsyncSession,
        claim: _Claim,
    ) -> MemoryOutboxTaskRow | None:
        return await db.scalar(
            select(MemoryOutboxTaskRow).where(
                MemoryOutboxTaskRow.id == claim.task_id,
                MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                MemoryOutboxTaskRow.lease_owner == claim.lease_token,
                MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
            )
        )

    async def _lease_is_current(self, db: AsyncSession, claim: _Claim) -> bool:
        """外部调用返回后再次核验租约，阻止过期 Worker 提交派生状态。"""
        task_id = await db.scalar(
            select(MemoryOutboxTaskRow.id).where(
                MemoryOutboxTaskRow.id == claim.task_id,
                MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                MemoryOutboxTaskRow.lease_owner == claim.lease_token,
                MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
            )
        )
        return task_id is not None


def _parse_upsert(payload: dict[str, object]) -> IndexUpsertPayload:
    """校验 Outbox JSON，拒绝缺字段或版本错配。"""
    from src.memory.contracts import MemoryScope, MemoryValueKind

    try:
        return IndexUpsertPayload(
            user_id=str(payload["user_id"]),
            record_id=str(payload["record_id"]),
            memory_version=int(str(payload["memory_version"])),
            kind=MemoryValueKind(str(payload["kind"])),
            category=str(payload["category"]),
            content=str(payload["content"]),
            scope=MemoryScope(str(payload["scope"])),
            policy_version=str(payload["policy_version"]),
            expires_at=_parse_datetime(payload.get("expires_at")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("INVALID_INDEX_PAYLOAD") from exc


def _parse_delete(payload: dict[str, object]) -> IndexDeletePayload:
    try:
        return IndexDeletePayload(
            user_id=str(payload["user_id"]),
            record_id=str(payload["record_id"]),
            memory_version=int(str(payload["memory_version"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("INVALID_INDEX_PAYLOAD") from exc


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


def _utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
