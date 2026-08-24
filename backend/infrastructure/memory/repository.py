"""通过 SQLAlchemy 实现 PostgreSQL 权威记忆与 Outbox 持久化。"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select, update as update_row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    MemoryOutboxTaskRow,
    MemoryStateEventRow,
    MemoryWorkingStateRow,
    Message,
    Session,
)
from src.memory.contracts import (
    DuplicateOutboxTaskError,
    MEMORY_SCHEMA_VERSION,
    MemoryErrorCode,
    MemoryScope,
    NewOutboxTask,
    OutboxTask,
    OutboxTaskKind,
    OutboxTaskStatus,
    TurnCommittedPayload,
    WorkingEntity,
    WorkingState,
    WorkingStateTransition,
    WorkingStateUpdate,
)
from src.memory.working_state import reduce_working_state


class MemoryRepositoryError(RuntimeError):
    """表示权威记忆存储拒绝了当前应用操作。"""

    def __init__(self, code: MemoryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class SqlAlchemyMemoryRepository:
    """复用调用方 AsyncSession，保证状态、消息与 Outbox 同事务。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load_or_create_working_state(
        self,
        *,
        user_id: str,
        session_id: str,
        source_message_id: int,
    ) -> WorkingState:
        """读取用户会话的 Working State，不存在时暂存初始快照。

        Args:
            user_id: 已认证用户标识，用于权威所有权过滤。
            session_id: 已在当前事务中存在的会话标识。
            source_message_id: 触发本轮读取或初始化的用户消息主键。

        Returns:
            强类型 Working State；初始状态版本为 0。

        Raises:
            MemoryRepositoryError: 会话不存在或不属于当前用户。
        """
        owned_session = await self._db.scalar(
            select(Session.id)
            .where(Session.id == session_id, Session.user_id == user_id)
            .with_for_update()
        )
        if owned_session is None:
            raise MemoryRepositoryError(
                MemoryErrorCode.SESSION_NOT_FOUND,
                "owned chat session is unavailable",
            )
        await self._assert_source_message_authority(
            user_id=user_id,
            session_id=session_id,
            source_message_id=source_message_id,
        )

        row = await self._db.scalar(
            select(MemoryWorkingStateRow)
            .where(MemoryWorkingStateRow.session_id == session_id)
            .with_for_update()
        )
        if row is None:
            row = MemoryWorkingStateRow(
                session_id=session_id,
                schema_version=MEMORY_SCHEMA_VERSION,
                state_version=0,
                active_entity=None,
                candidate_entities=[],
                constraints=[],
                reply_preference_hint="",
                scope=MemoryScope.SESSION_SEGMENT.value,
                source_message_id=source_message_id,
            )
            self._db.add(row)
            await self._db.flush()
        return self._to_working_state(row)

    async def apply_working_state(
        self,
        *,
        current: WorkingState,
        update: WorkingStateUpdate,
        session_id: str,
        source_message_id: int,
        trace_id: str | None,
    ) -> WorkingStateTransition:
        """以乐观版本更新快照，并在同一事务写入字段事件。

        Raises:
            MemoryRepositoryError: 当前快照已被并发轮次更新。
        """
        transition = reduce_working_state(
            current,
            update,
            session_id=session_id,
            source_message_id=source_message_id,
            trace_id=trace_id,
        )
        if not transition.events:
            return transition

        state = transition.state
        statement = (
            update_row(MemoryWorkingStateRow)
            .where(
                MemoryWorkingStateRow.session_id == session_id,
                MemoryWorkingStateRow.state_version == current.state_version,
            )
            .values(
                state_version=state.state_version,
                active_entity=_json_value(state.active_entity),
                candidate_entities=_json_value(state.candidate_entities),
                constraints=list(state.constraints),
                reply_preference_hint=state.reply_preference_hint,
                scope=state.scope.value,
                source_message_id=source_message_id,
            )
        )
        result = await self._db.execute(statement)
        if getattr(result, "rowcount", 0) != 1:
            raise MemoryRepositoryError(
                MemoryErrorCode.VERSION_CONFLICT,
                "working-state optimistic version is stale",
            )
        for event in transition.events:
            self._db.add(
                MemoryStateEventRow(
                    session_id=event.session_id,
                    message_id=event.message_id,
                    field_name=event.field.value,
                    operation=event.operation.value,
                    old_value=_json_value(event.old_value),
                    new_value=_json_value(event.new_value),
                    source=event.source.value,
                    confidence=event.confidence,
                    state_version=event.state_version,
                    schema_version=event.schema_version,
                    trace_id=event.trace_id,
                )
            )
        await self._db.flush()
        return transition

    async def enqueue_outbox(self, intent: NewOutboxTask) -> OutboxTask:
        """暂存 Outbox 任务并将唯一键冲突转换为稳定领域错误。

        Args:
            intent: 已校验、只包含安全行引用的任务意图。

        Returns:
            已分配任务标识但尚未提交的 Outbox 合同。

        Raises:
            DuplicateOutboxTaskError: 同一用户和幂等键已经存在。
        """
        await self._assert_turn_authority(intent)
        row = MemoryOutboxTaskRow(
            user_id=intent.user_id,
            session_id=intent.session_id,
            aggregate_type=intent.aggregate_type,
            aggregate_id=intent.aggregate_id,
            task_kind=intent.task_kind.value,
            payload_json=asdict(intent.payload),
            status=OutboxTaskStatus.PENDING.value,
            idempotency_key=intent.idempotency_key,
            schema_version=intent.schema_version,
            trace_id=intent.trace_id,
            attempt_count=0,
        )
        self._db.add(row)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            if self._is_idempotency_conflict(exc):
                raise DuplicateOutboxTaskError(
                    "duplicate memory outbox idempotency key"
                ) from exc
            raise MemoryRepositoryError(
                MemoryErrorCode.PERSISTENCE_CONSTRAINT_VIOLATION,
                "memory outbox integrity constraint rejected the write",
            ) from exc
        return OutboxTask(
            task_id=row.id,
            intent=intent,
            status=OutboxTaskStatus(row.status),
            attempt_count=row.attempt_count,
            available_at=row.available_at,
            created_at=row.created_at,
        )

    async def _assert_turn_authority(self, intent: NewOutboxTask) -> None:
        """验证 Outbox 中冗余标识都指向同一用户的真实对话轮次。"""
        if intent.task_kind not in {
            OutboxTaskKind.TURN_COMMITTED,
            OutboxTaskKind.SUMMARY_COMPACT,
        }:
            return
        assert intent.session_id is not None  # 已由 NewOutboxTask 合同验证。
        owner_id = await self._db.scalar(
            select(Session.user_id).where(Session.id == intent.session_id)
        )
        if owner_id is None:
            raise MemoryRepositoryError(
                MemoryErrorCode.SESSION_NOT_FOUND,
                "outbox session is unavailable",
            )
        if owner_id != intent.user_id:
            raise MemoryRepositoryError(
                MemoryErrorCode.OWNERSHIP_MISMATCH,
                "outbox user does not own the referenced session",
            )

        if intent.task_kind is not OutboxTaskKind.TURN_COMMITTED:
            return
        if not isinstance(intent.payload, TurnCommittedPayload):
            raise MemoryRepositoryError(
                MemoryErrorCode.INVALID_CONTRACT,
                "turn outbox payload type is invalid",
            )

        message_rows = (
            await self._db.execute(
                select(Message.id, Message.session_id, Message.role).where(
                    Message.id.in_(
                        (
                            intent.payload.user_message_id,
                            intent.payload.assistant_message_id,
                        )
                    )
                )
            )
        ).all()
        observed = {row.id: (row.session_id, row.role) for row in message_rows}
        expected = {
            intent.payload.user_message_id: (intent.session_id, "user"),
            intent.payload.assistant_message_id: (intent.session_id, "assistant"),
        }
        if observed != expected:
            raise MemoryRepositoryError(
                MemoryErrorCode.PERSISTENCE_CONSTRAINT_VIOLATION,
                "outbox messages do not form the referenced user/assistant turn",
            )

    async def _assert_source_message_authority(
        self,
        *,
        user_id: str,
        session_id: str,
        source_message_id: int,
    ) -> None:
        """验证 Working State 的来源是当前用户会话中的用户消息。"""
        message_authority = (
            await self._db.execute(
                select(Message.session_id, Message.role, Session.user_id)
                .join(Session, Session.id == Message.session_id)
                .where(Message.id == source_message_id)
            )
        ).one_or_none()
        expected = (session_id, "user", user_id)
        if message_authority is None or tuple(message_authority) != expected:
            raise MemoryRepositoryError(
                MemoryErrorCode.PERSISTENCE_CONSTRAINT_VIOLATION,
                "working-state source message is outside the owned user session",
            )

    @staticmethod
    def _is_idempotency_conflict(exc: IntegrityError) -> bool:
        """只识别 M2 Outbox 幂等唯一约束，不掩盖其他完整性失败。"""
        original = exc.orig
        cause = getattr(original, "__cause__", None)
        sqlstate = getattr(original, "sqlstate", None) or getattr(
            cause,
            "sqlstate",
            None,
        )
        constraint_name = getattr(original, "constraint_name", None) or getattr(
            cause,
            "constraint_name",
            None,
        )
        expected_name = "uq_memory_outbox_user_idempotency"
        if sqlstate == "23505":
            return constraint_name == expected_name or expected_name in str(original)
        sqlite_signature = (
            "UNIQUE constraint failed: memory_outbox_tasks.user_id, "
            "memory_outbox_tasks.idempotency_key"
        )
        return sqlite_signature in str(original)

    @staticmethod
    def _to_working_state(row: MemoryWorkingStateRow) -> WorkingState:
        entity = None
        if row.active_entity:
            entity = WorkingEntity(
                symbol=str(row.active_entity["symbol"]),
                name=str(row.active_entity["name"]),
                entity_type=str(row.active_entity["entity_type"]),
            )
        candidates = tuple(
            WorkingEntity(
                symbol=str(item["symbol"]),
                name=str(item["name"]),
                entity_type=str(item["entity_type"]),
            )
            for item in row.candidate_entities
        )
        return WorkingState(
            active_entity=entity,
            candidate_entities=candidates,
            constraints=tuple(row.constraints),
            reply_preference_hint=row.reply_preference_hint,
            scope=MemoryScope(row.scope),
            state_version=row.state_version,
            schema_version=row.schema_version,
            source_message_id=row.source_message_id,
            updated_at=row.updated_at,
        )


def _json_value(value: object) -> object:
    """把不可变领域值转换为 JSON 列可接受的安全结构。"""
    if isinstance(value, WorkingEntity):
        return asdict(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
