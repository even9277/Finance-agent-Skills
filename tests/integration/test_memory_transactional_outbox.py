"""验证聊天消息、Working State 与记忆 Outbox 的事务原子性。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.application.memory.cache import (  # noqa: E402
    CacheLookup,
    CacheLookupStatus,
    MemoryCacheConfig,
    MemoryHotCache,
)
from backend.db.database import Base  # noqa: E402
from backend.db.models import (  # noqa: E402
    MemoryOutboxTaskRow,
    MemoryStateEventRow,
    MemoryWorkingStateRow,
    Message,
    Session,
    User,
)
from backend.infrastructure.chat.repository import (  # noqa: E402
    SqlAlchemyConversationRepository,
)
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryTraceSink,
)
from backend.infrastructure.memory.repository import (  # noqa: E402
    MemoryRepositoryError,
    SqlAlchemyMemoryRepository,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.memory.contracts import (  # noqa: E402
    DuplicateOutboxTaskError,
    MEMORY_SCHEMA_VERSION,
    MemoryErrorCode,
    NewOutboxTask,
    OutboxTaskKind,
    TurnCommittedPayload,
    build_turn_outbox_key,
)


async def _create_session_factory(database_path: Path):
    """创建只服务于单个事务测试的 SQLite 数据库。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_user(session_factory, user_id: str) -> None:
    """为启用外键的隔离测试创建真实用户权威行。"""
    async with session_factory() as db:
        db.add(User(id=user_id, display_name="事务测试用户"))
        await db.commit()


class _FakePostgresConstraintError(Exception):
    """模拟 asyncpg 暴露的 SQLSTATE 与约束名。"""

    def __init__(self, sqlstate: str, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


@pytest.mark.integration
def test_integrity_error_classifier_only_accepts_outbox_idempotency_constraint() -> None:
    """确认外键或其他唯一失败不会被伪装成幂等冲突。"""
    duplicate = IntegrityError(
        "INSERT",
        {},
        _FakePostgresConstraintError(
            "23505",
            "uq_memory_outbox_user_idempotency",
        ),
    )
    foreign_key = IntegrityError(
        "INSERT",
        {},
        _FakePostgresConstraintError(
            "23503",
            "fk_memory_outbox_user",
        ),
    )
    other_unique = IntegrityError(
        "INSERT",
        {},
        _FakePostgresConstraintError("23505", "memory_outbox_tasks_pkey"),
    )

    assert SqlAlchemyMemoryRepository._is_idempotency_conflict(duplicate) is True
    assert SqlAlchemyMemoryRepository._is_idempotency_conflict(foreign_key) is False
    assert SqlAlchemyMemoryRepository._is_idempotency_conflict(other_unique) is False


def _workflow() -> ControlledConversationWorkflow:
    """构造完全离线但经过真实受控阶段的工作流。"""
    return ControlledConversationWorkflow(
        model=FakeModelProvider(),
        tool=FakeToolProvider(),
        trace=InMemoryTraceSink(),
    )


@pytest.mark.integration
def test_chat_turn_commits_messages_state_and_outbox_once(tmp_path: Path) -> None:
    """确认成功轮次在同一次提交中写入消息、初始状态和安全 Outbox。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "atomic-success.db")
        try:
            await _seed_user(session_factory, "fixture-user-memory")
            async with session_factory() as db:
                outcome = await ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(db),
                ).execute(
                    ChatCommand(
                        user_id="fixture-user-memory",
                        message="查询贵州茅台 600519.SH 的基础信息和近期行情",
                    )
                )

            async with session_factory() as verification:
                messages = list(
                    (
                        await verification.execute(
                            select(Message)
                            .where(Message.session_id == outcome.session_id)
                            .order_by(Message.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                state = await verification.get(MemoryWorkingStateRow, outcome.session_id)
                outbox = await verification.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.session_id == outcome.session_id
                    )
                )

            assert [message.role for message in messages] == ["user", "assistant"]
            assert state is not None
            assert state.state_version == 1
            assert state.source_message_id == messages[0].id
            assert outcome.working_state.schema_version == MEMORY_SCHEMA_VERSION
            assert outbox is not None
            assert outbox.task_kind == OutboxTaskKind.TURN_COMMITTED.value
            assert outbox.payload_json == {
                "session_id": outcome.session_id,
                "user_message_id": messages[0].id,
                "assistant_message_id": messages[1].id,
                "state_version": 1,
            }
            assert set(outbox.payload_json).isdisjoint(
                {"message", "content", "profile", "prompt"}
            )
            assert outbox.trace_id == outcome.context.trace_id
            async with session_factory() as verification:
                events = list(
                    (
                        await verification.execute(
                            select(MemoryStateEventRow).where(
                                MemoryStateEventRow.session_id == outcome.session_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            assert {event.field_name for event in events} == {
                "active_entity",
                "candidate_entities",
            }
            assert {event.state_version for event in events} == {1}
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_committed_turn_enqueues_one_summary_task_before_protected_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """达到阈值后只排队一个冻结边界的摘要任务，不压入最近原文。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "summary-queue.db")
        try:
            await _seed_user(session_factory, "fixture-user-memory")
            monkeypatch.setattr("backend.infrastructure.chat.repository.settings.enable_stm", True)
            monkeypatch.setattr(
                "backend.infrastructure.chat.repository.settings.stm_compression_strategy",
                "legacy_count",
            )
            monkeypatch.setattr(
                "backend.infrastructure.chat.repository.settings.stm_legacy_count_threshold",
                4,
            )
            monkeypatch.setattr(
                "backend.infrastructure.chat.repository.settings.stm_keep_recent",
                2,
            )
            session_id: str | None = None
            for query in (
                "查询贵州茅台 600519.SH 的近期走势",
                "它的基础信息怎么样",
            ):
                async with session_factory() as db:
                    outcome = await ControlledChatUseCase(
                        workflow=_workflow(),
                        repository=SqlAlchemyConversationRepository(db),
                    ).execute(
                        ChatCommand(
                            user_id="fixture-user-memory",
                            session_id=session_id,
                            message=query,
                        )
                    )
                    session_id = outcome.session_id

            assert session_id is not None
            async with session_factory() as verification:
                tasks = list(
                    (
                        await verification.execute(
                            select(MemoryOutboxTaskRow).where(
                                MemoryOutboxTaskRow.session_id == session_id,
                                MemoryOutboxTaskRow.task_kind
                                == OutboxTaskKind.SUMMARY_COMPACT.value,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                messages = list(
                    (
                        await verification.execute(
                            select(Message)
                            .where(Message.session_id == session_id)
                            .order_by(Message.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                session = await verification.get(Session, session_id)

            assert len(tasks) == 1
            payload = tasks[0].payload_json
            protected_ids = [message.id for message in messages[-2:]]
            source_end_message_id = payload["source_end_message_id"]
            assert isinstance(source_end_message_id, int)
            assert source_end_message_id < min(protected_ids)
            assert payload["protected_tail_start_message_id"] == min(protected_ids)
            assert payload["source_message_count"] == len(messages) - 2
            assert session is not None
            assert session.compression_status == "queued"
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_commit_failure_rolls_back_messages_state_and_outbox(tmp_path: Path) -> None:
    """确认提交失败不会留下权威数据，也不会发布未提交缓存快照。"""

    class FailingCommitSession(AsyncSession):
        """只在事务提交边界注入故障，保留生产 Repository 的排序逻辑。"""

        async def commit(self) -> None:
            """模拟数据库提交前的故障。"""
            raise RuntimeError("fixture commit failure")

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "atomic-rollback.db")
        try:
            await _seed_user(session_factory, "fixture-user-memory")
            failing_session_factory = async_sessionmaker(
                engine,
                class_=FailingCommitSession,
                expire_on_commit=False,
            )
            cache = Mock()
            cache.config = MemoryCacheConfig()
            cache.get_context = AsyncMock(
                return_value=CacheLookup(status=CacheLookupStatus.MISS)
            )
            cache.get_working_state = AsyncMock(
                return_value=CacheLookup(status=CacheLookupStatus.MISS)
            )
            cache.get_profile = AsyncMock(
                return_value=CacheLookup(status=CacheLookupStatus.MISS)
            )
            cache.acquire_fill_lease = AsyncMock(return_value=None)
            cache.release_fill_lease = AsyncMock()
            cache.set_context = AsyncMock()
            cache.set_working_state = AsyncMock()
            cache.set_profile = AsyncMock()
            async with failing_session_factory() as db:
                use_case = ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(
                        db,
                        cache=cast(MemoryHotCache, cache),
                    ),
                )
                with pytest.raises(RuntimeError, match="fixture commit failure"):
                    await use_case.execute(
                        ChatCommand(
                            user_id="fixture-user-memory",
                            message="查询贵州茅台 600519.SH 行情",
                        )
                    )

            async with session_factory() as verification:
                counts = {
                    "sessions": await verification.scalar(select(func.count(Session.id))),
                    "messages": await verification.scalar(select(func.count(Message.id))),
                    "states": await verification.scalar(
                        select(func.count(MemoryWorkingStateRow.session_id))
                    ),
                    "outbox": await verification.scalar(
                        select(func.count(MemoryOutboxTaskRow.id))
                    ),
                }
            assert counts == {"sessions": 0, "messages": 0, "states": 0, "outbox": 0}
            cache.set_context.assert_not_awaited()
            cache.set_working_state.assert_not_awaited()
            cache.set_profile.assert_not_awaited()
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_duplicate_outbox_idempotency_key_is_rejected(tmp_path: Path) -> None:
    """确认相同用户与幂等键只能持久化一条任务。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "outbox-dedupe.db")
        try:
            await _seed_user(session_factory, "fixture-user-memory")
            async with session_factory() as seed_db:
                seed_db.add(
                    Session(
                        id="fixture-session",
                        user_id="fixture-user-memory",
                        mode="chat",
                    )
                )
                user_message = Message(
                    session_id="fixture-session",
                    role="user",
                    content="虚拟用户消息",
                )
                assistant_message = Message(
                    session_id="fixture-session",
                    role="assistant",
                    content="虚拟助手消息",
                )
                seed_db.add_all((user_message, assistant_message))
                await seed_db.commit()
            intent = NewOutboxTask(
                user_id="fixture-user-memory",
                session_id="fixture-session",
                aggregate_type="chat_turn",
                aggregate_id="fixture-session",
                task_kind=OutboxTaskKind.TURN_COMMITTED,
                idempotency_key=build_turn_outbox_key(
                    "fixture-session",
                    user_message.id,
                ),
                payload=TurnCommittedPayload(
                    session_id="fixture-session",
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                    state_version=0,
                ),
            )
            async with session_factory() as first_db:
                await SqlAlchemyMemoryRepository(first_db).enqueue_outbox(intent)
                await first_db.commit()

            async with session_factory() as second_db:
                with pytest.raises(DuplicateOutboxTaskError) as error:
                    await SqlAlchemyMemoryRepository(second_db).enqueue_outbox(intent)
                await second_db.rollback()

            assert error.value.code.value == "DUPLICATE_IDEMPOTENCY_KEY"
            async with session_factory() as verification:
                count = await verification.scalar(select(func.count(MemoryOutboxTaskRow.id)))
            assert count == 1
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_concurrent_chat_turns_keep_transaction_context_isolated(tmp_path: Path) -> None:
    """确认并发轮次不会串用消息标识、Working State 或 Outbox 负载。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "outbox-concurrency.db"
        )

        async def execute_turn(symbol: str):
            async with session_factory() as db:
                return await ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(db),
                ).execute(
                    ChatCommand(
                        user_id="fixture-user-concurrent",
                        session_id="fixture-session-concurrent",
                        message=f"查询 {symbol} 的基础信息和近期行情",
                    )
                )

        try:
            await _seed_user(session_factory, "fixture-user-concurrent")
            async with session_factory() as seed_db:
                seed_db.add(
                    Session(
                        id="fixture-session-concurrent",
                        user_id="fixture-user-concurrent",
                        mode="chat",
                    )
                )
                await seed_db.commit()
            first, second = await asyncio.gather(
                execute_turn("600519.SH"),
                execute_turn("000001.SZ"),
            )
            async with session_factory() as verification:
                outbox_rows = list(
                    (
                        await verification.execute(
                            select(MemoryOutboxTaskRow)
                            .where(
                                MemoryOutboxTaskRow.task_kind
                                == OutboxTaskKind.TURN_COMMITTED.value
                            )
                            .order_by(MemoryOutboxTaskRow.user_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                state_count = await verification.scalar(
                    select(func.count(MemoryWorkingStateRow.session_id))
                )
                message_count = await verification.scalar(
                    select(func.count(Message.id)).where(
                        Message.session_id == "fixture-session-concurrent"
                    )
                )
                turn_count = await verification.scalar(
                    select(Session.turn_count).where(
                        Session.id == "fixture-session-concurrent"
                    )
                )

            assert first.session_id == second.session_id == "fixture-session-concurrent"
            assert state_count == 1
            assert message_count == 4
            assert turn_count == 2
            assert len(outbox_rows) == 2
            assert all(
                row.task_kind == OutboxTaskKind.TURN_COMMITTED.value
                for row in outbox_rows
            )
            assert {
                (row.user_id, row.session_id, row.payload_json["session_id"])
                for row in outbox_rows
            } == {
                (
                    "fixture-user-concurrent",
                    first.session_id,
                    first.session_id,
                ),
            }
            assert len({row.idempotency_key for row in outbox_rows}) == 2
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_outbox_rejects_cross_user_session_and_message_references(
    tmp_path: Path,
) -> None:
    """确认真实用户不能创建指向其他用户会话的 Outbox。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "outbox-owner.db"
        )
        try:
            await _seed_user(session_factory, "fixture-user-owner")
            await _seed_user(session_factory, "fixture-user-attacker")
            async with session_factory() as seed_db:
                seed_db.add(
                    Session(
                        id="fixture-session-owner",
                        user_id="fixture-user-owner",
                        mode="chat",
                    )
                )
                user_message = Message(
                    session_id="fixture-session-owner",
                    role="user",
                    content="所有者消息",
                )
                assistant_message = Message(
                    session_id="fixture-session-owner",
                    role="assistant",
                    content="所有者回复",
                )
                seed_db.add_all((user_message, assistant_message))
                await seed_db.commit()

            intent = NewOutboxTask(
                user_id="fixture-user-attacker",
                session_id="fixture-session-owner",
                aggregate_type="chat_turn",
                aggregate_id="fixture-session-owner",
                task_kind=OutboxTaskKind.TURN_COMMITTED,
                idempotency_key=build_turn_outbox_key(
                    "fixture-session-owner",
                    user_message.id,
                ),
                payload=TurnCommittedPayload(
                    session_id="fixture-session-owner",
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                    state_version=0,
                ),
            )
            async with session_factory() as db:
                with pytest.raises(MemoryRepositoryError) as error:
                    await SqlAlchemyMemoryRepository(db).enqueue_outbox(intent)
                await db.rollback()
            assert error.value.code is MemoryErrorCode.OWNERSHIP_MISMATCH

            async with session_factory() as verification:
                count = await verification.scalar(
                    select(func.count(MemoryOutboxTaskRow.id))
                )
            assert count == 0
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_memory_rejects_same_user_cross_session_message_references(
    tmp_path: Path,
) -> None:
    """确认同一用户也不能把另一会话消息绑定到当前 State 或 Outbox。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "cross-session-authority.db"
        )
        try:
            await _seed_user(session_factory, "fixture-user-cross-session")
            async with session_factory() as seed_db:
                seed_db.add_all(
                    (
                        Session(
                            id="fixture-session-a",
                            user_id="fixture-user-cross-session",
                            mode="chat",
                        ),
                        Session(
                            id="fixture-session-b",
                            user_id="fixture-user-cross-session",
                            mode="chat",
                        ),
                    )
                )
                await seed_db.flush()
                foreign_user_message = Message(
                    session_id="fixture-session-b",
                    role="user",
                    content="另一会话的用户消息",
                )
                foreign_assistant_message = Message(
                    session_id="fixture-session-b",
                    role="assistant",
                    content="另一会话的助手消息",
                )
                seed_db.add_all((foreign_user_message, foreign_assistant_message))
                await seed_db.commit()

            async with session_factory() as state_db:
                repository = SqlAlchemyMemoryRepository(state_db)
                with pytest.raises(MemoryRepositoryError) as state_error:
                    await repository.load_or_create_working_state(
                        user_id="fixture-user-cross-session",
                        session_id="fixture-session-a",
                        source_message_id=foreign_user_message.id,
                    )
                await state_db.rollback()
            assert (
                state_error.value.code
                is MemoryErrorCode.PERSISTENCE_CONSTRAINT_VIOLATION
            )

            intent = NewOutboxTask(
                user_id="fixture-user-cross-session",
                session_id="fixture-session-a",
                aggregate_type="chat_turn",
                aggregate_id="fixture-session-a",
                task_kind=OutboxTaskKind.TURN_COMMITTED,
                idempotency_key=build_turn_outbox_key(
                    "fixture-session-a",
                    foreign_user_message.id,
                ),
                payload=TurnCommittedPayload(
                    session_id="fixture-session-a",
                    user_message_id=foreign_user_message.id,
                    assistant_message_id=foreign_assistant_message.id,
                    state_version=0,
                ),
            )
            async with session_factory() as outbox_db:
                with pytest.raises(MemoryRepositoryError) as outbox_error:
                    await SqlAlchemyMemoryRepository(outbox_db).enqueue_outbox(intent)
                await outbox_db.rollback()
            assert (
                outbox_error.value.code
                is MemoryErrorCode.PERSISTENCE_CONSTRAINT_VIOLATION
            )

            async with session_factory() as verification:
                state_count = await verification.scalar(
                    select(func.count(MemoryWorkingStateRow.session_id))
                )
                outbox_count = await verification.scalar(
                    select(func.count(MemoryOutboxTaskRow.id))
                )
            assert state_count == 0
            assert outbox_count == 0
        finally:
            await engine.dispose()

    asyncio.run(run_case())
