"""把权威记忆变更转换为可恢复的语义索引 Outbox 任务。"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import MemoryOutboxTaskRow, MemoryRecordRow
from src.memory.contracts import (
    MEMORY_SCHEMA_VERSION,
    IndexDeletePayload,
    IndexUpsertPayload,
    MemoryValueKind,
    OutboxTaskKind,
    OutboxTaskStatus,
    build_index_delete_key,
    build_index_upsert_key,
)


async def enqueue_index_upsert(
    db: AsyncSession,
    row: MemoryRecordRow,
    *,
    trace_id: str | None = None,
) -> bool:
    """为一条可检索文本权威记录创建幂等 INDEX_UPSERT 任务。"""
    if row.kind != MemoryValueKind.TEXT.value or row.content is None:
        return False
    payload = IndexUpsertPayload(
        user_id=row.user_id,
        record_id=row.id,
        memory_version=row.version,
        kind=MemoryValueKind.TEXT,
        category=row.category,
        content=row.content,
        scope=_scope(row.scope),
        policy_version=row.policy_version,
        expires_at=row.expires_at,
    )
    key = build_index_upsert_key(row.id, row.version)
    existing = await db.scalar(
        select(MemoryOutboxTaskRow.id).where(
            MemoryOutboxTaskRow.user_id == row.user_id,
            MemoryOutboxTaskRow.idempotency_key == key,
        )
    )
    if existing is not None:
        return False
    db.add(
        MemoryOutboxTaskRow(
            user_id=row.user_id,
            aggregate_type="memory_record",
            aggregate_id=row.id,
            task_kind=OutboxTaskKind.INDEX_UPSERT.value,
            payload_json=_json_payload(payload),
            status=OutboxTaskStatus.PENDING.value,
            idempotency_key=key,
            schema_version=MEMORY_SCHEMA_VERSION,
            trace_id=trace_id,
        )
    )
    return True


async def enqueue_index_delete(
    db: AsyncSession,
    row: MemoryRecordRow,
    *,
    trace_id: str | None = None,
) -> bool:
    """为失效记录创建幂等 INDEX_DELETE 任务，保证立即从权威召回中消失。"""
    payload = IndexDeletePayload(
        user_id=row.user_id,
        record_id=row.id,
        memory_version=row.version,
    )
    key = build_index_delete_key(row.id, row.version)
    existing = await db.scalar(
        select(MemoryOutboxTaskRow.id).where(
            MemoryOutboxTaskRow.user_id == row.user_id,
            MemoryOutboxTaskRow.idempotency_key == key,
        )
    )
    if existing is not None:
        return False
    db.add(
        MemoryOutboxTaskRow(
            user_id=row.user_id,
            aggregate_type="memory_record",
            aggregate_id=row.id,
            task_kind=OutboxTaskKind.INDEX_DELETE.value,
            payload_json=_json_payload(payload),
            status=OutboxTaskStatus.PENDING.value,
            idempotency_key=key,
            schema_version=MEMORY_SCHEMA_VERSION,
            trace_id=trace_id,
        )
    )
    return True


def _json_payload(payload: IndexUpsertPayload | IndexDeletePayload) -> dict[str, object]:
    """把领域 payload 转换为 JSON，同时显式序列化枚举和时间。"""
    data = asdict(payload)
    for key, value in tuple(data.items()):
        if hasattr(value, "value"):
            data[key] = value.value
        elif hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data


def _scope(value: str):
    """解析持久化 scope，旧数据异常时拒绝静默扩大作用域。"""
    from src.memory.contracts import MemoryScope

    return MemoryScope(value)
