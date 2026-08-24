"""验证统一 Outbox 驱动的 Rolling Summary Worker。"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.application.memory.summary import (  # noqa: E402
    SummaryDraft,
    SummaryRequest,
)
from backend.application.memory.cache import MemoryHotCache  # noqa: E402
from backend.db.database import Base  # noqa: E402
from backend.db.models import (  # noqa: E402
    MemoryOutboxTaskRow,
    MemorySummaryMetadataRow,
    Message,
    Session,
    SessionSummary,
    StmCompactionTask,
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
from backend.infrastructure.memory.runtime import set_memory_cache_for_testing  # noqa: E402
from backend.services.stm_compaction_worker import SummaryCompactionWorker  # noqa: E402
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.memory.contracts import (  # noqa: E402
    OutboxTaskKind,
    OutboxTaskStatus,
    SummaryStatus,
)


class _DeterministicSummaryModel:
    """生成冻结边界一致的离线摘要。"""

    calls: list[SummaryRequest]

    def __init__(self) -> None:
        self.calls = []

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        self.calls.append(request)
        return SummaryDraft(
            summary="此前讨论了贵州茅台的近期走势，主线仍待继续。",
            source_start_message_id=request.source_start_message_id,
            source_end_message_id=request.source_end_message_id,
            source_message_count=len(request.messages),
            prompt_version=request.prompt_version,
        )


class _FailingSummaryModel:
    """模拟模型供应商在后台不可用。"""

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        del request
        raise RuntimeError("fixture provider unavailable")


class _AdvancingSummaryModel(_DeterministicSummaryModel):
    """模拟模型调用期间另一个 Worker 已经推进 last-good 版本。"""

    def __init__(self, session_factory, session_id: str) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._session_id = session_id

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        async with self._session_factory() as db:
            session = await db.get(Session, self._session_id)
            assert session is not None
            session.summary_version = 1
            session.running_summary = "另一个 Worker 已提交的 last-good"
            await db.commit()
        return await super().summarize(request)


class _HoldingSummaryModel:
    """暂停旧 Worker，构造 lease 过期后的双 Worker 交错。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def summarize(self, request: SummaryRequest) -> SummaryDraft:
        self.started.set()
        await self.release.wait()
        return SummaryDraft(
            summary="旧 Worker 的过期草稿不得生效",
            source_start_message_id=request.source_start_message_id,
            source_end_message_id=request.source_end_message_id,
            source_message_count=len(request.messages),
            prompt_version=request.prompt_version,
        )


class _InvalidationSpy:
    """记录摘要成功后的缓存失效，并可模拟适配器实现异常。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail

    async def invalidate_context(self, user_id: str, session_id: str) -> None:
        self.calls.append((user_id, session_id))
        if self._fail:
            raise RuntimeError("fixture cache failure")


async def _create_session_factory(database_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _workflow() -> ControlledConversationWorkflow:
    return ControlledConversationWorkflow(
        model=FakeModelProvider(),
        tool=FakeToolProvider(),
        trace=InMemoryTraceSink(),
    )


async def _seed_summary_task(session_factory, monkeypatch: pytest.MonkeyPatch) -> str:
    async with session_factory() as db:
        db.add(User(id="fixture-user-summary", display_name="摘要测试用户"))
        await db.commit()
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
                    user_id="fixture-user-summary",
                    session_id=session_id,
                    message=query,
                )
            )
            session_id = outcome.session_id
    assert session_id is not None
    return session_id


@pytest.mark.integration
def test_summary_worker_applies_valid_draft_and_preserves_raw_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合格摘要只压缩冻结前缀，并写入版本、边界和 last-good。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "summary-success.db")
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            cache_spy = _InvalidationSpy(fail=True)
            set_memory_cache_for_testing(cast(MemoryHotCache, cache_spy))
            model = _DeterministicSummaryModel()
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=model,
                worker_id="worker-test",
                max_attempts=2,
            )

            assert await worker.process_next() is True

            async with session_factory() as db:
                session = await db.get(Session, session_id)
                messages = list(
                    (
                        await db.execute(
                            select(Message)
                            .where(Message.session_id == session_id)
                            .order_by(Message.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                snapshots = list(
                    (
                        await db.execute(
                            select(SessionSummary).where(
                                SessionSummary.session_id == session_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                metadata = await db.scalar(
                    select(MemorySummaryMetadataRow).where(
                        MemorySummaryMetadataRow.session_id == session_id
                    )
                )
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.session_id == session_id,
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value,
                    )
                )
                legacy_tasks = list((await db.execute(select(StmCompactionTask))).scalars())

            assert session is not None
            assert session.summary_version == 1
            assert session.running_summary == "此前讨论了贵州茅台的近期走势，主线仍待继续。"
            assert [item.is_compressed for item in messages] == [True, True, False, False]
            assert len(snapshots) == 1
            assert snapshots[0].start_message_id == messages[0].id
            assert snapshots[0].end_message_id == messages[1].id
            assert metadata is not None
            assert metadata.status == SummaryStatus.SUCCEEDED.value
            assert metadata.summary_version == 1
            assert task is not None
            assert task.status == OutboxTaskStatus.SUCCEEDED.value
            assert legacy_tasks == []
            assert cache_spy.calls == [("fixture-user-summary", session_id)]
        finally:
            set_memory_cache_for_testing(None)
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_stale_summary_task_never_overwrites_newer_last_good(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务冻结版本落后时直接取消，且不调用模型。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "summary-stale.db")
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            async with session_factory() as db:
                session = await db.get(Session, session_id)
                assert session is not None
                session.summary_version = 1
                session.running_summary = "更新的 last-good 摘要"
                await db.commit()
            model = _DeterministicSummaryModel()
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=model,
                worker_id="worker-stale",
                max_attempts=2,
            )

            assert await worker.process_next() is True

            async with session_factory() as db:
                session = await db.get(Session, session_id)
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                metadata = await db.scalar(
                    select(MemorySummaryMetadataRow).where(
                        MemorySummaryMetadataRow.session_id == session_id,
                        MemorySummaryMetadataRow.summary_version == 1,
                    )
                )
            assert session is not None
            assert session.running_summary == "更新的 last-good 摘要"
            assert model.calls == []
            assert task is not None
            assert task.status == OutboxTaskStatus.CANCELLED.value
            assert metadata is not None
            assert metadata.status == SummaryStatus.STALE.value
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_summary_provider_failure_keeps_foreground_and_last_good(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """后台模型失败只进入有限重试，不删除消息或覆盖 last-good。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "summary-failure.db")
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=_FailingSummaryModel(),
                worker_id="worker-failure",
                max_attempts=1,
            )

            assert await worker.process_next() is True

            async with session_factory() as db:
                session = await db.get(Session, session_id)
                messages = list(
                    (
                        await db.execute(
                            select(Message).where(Message.session_id == session_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                metadata = await db.scalar(
                    select(MemorySummaryMetadataRow).where(
                        MemorySummaryMetadataRow.session_id == session_id
                    )
                )
            assert session is not None
            assert session.running_summary is None
            assert session.summary_version == 0
            assert all(not message.is_compressed for message in messages)
            assert task is not None
            assert task.status == OutboxTaskStatus.DEAD_LETTER.value
            assert metadata is not None
            assert metadata.status == SummaryStatus.FAILED.value
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_summary_version_advancing_during_model_call_cancels_stale_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型调用期间版本前进时不得把 stale 草稿写成成功摘要。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "summary-race.db"
        )
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=_AdvancingSummaryModel(session_factory, session_id),
                worker_id="worker-race",
                max_attempts=2,
            )

            assert await worker.process_next() is True

            async with session_factory() as db:
                session = await db.get(Session, session_id)
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                snapshots = list(
                    (await db.execute(select(SessionSummary))).scalars().all()
                )
            assert session is not None
            assert session.running_summary == "另一个 Worker 已提交的 last-good"
            assert task is not None
            assert task.status == OutboxTaskStatus.CANCELLED.value
            assert snapshots == []
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_invalid_summary_payload_reaches_dead_letter_without_sticking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """损坏任务应直接进入死信，不能因二次解析失败卡在处理中。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "summary-invalid-payload.db"
        )
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            async with session_factory() as db:
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                assert task is not None
                task.payload_json = {"session_id": session_id}
                await db.commit()
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=_DeterministicSummaryModel(),
                worker_id="worker-invalid",
                max_attempts=3,
            )

            assert await worker.process_next() is True

            async with session_factory() as db:
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
            assert task is not None
            assert task.status == OutboxTaskStatus.DEAD_LETTER.value
            assert task.last_error_code == "INVALID_CONTRACT"
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_same_user_cross_session_task_tampering_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一用户下任务行与 payload 会话不一致时不得读取或压缩任一会话。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "summary-cross-session-tamper.db"
        )
        try:
            original_session_id = await _seed_summary_task(session_factory, monkeypatch)
            tampered_session_id = "fixture-session-tampered"
            async with session_factory() as db:
                db.add(
                    Session(
                        id=tampered_session_id,
                        user_id="fixture-user-summary",
                        mode="chat",
                    )
                )
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                assert task is not None
                # 模拟持久数据损坏：任务挂在 B，会话 payload 仍指向 A。
                task.session_id = tampered_session_id
                task.aggregate_id = tampered_session_id
                await db.commit()

            model = _DeterministicSummaryModel()
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=model,
                worker_id="worker-tamper",
                max_attempts=3,
            )
            assert await worker.process_next() is True

            async with session_factory() as db:
                original = await db.get(Session, original_session_id)
                tampered = await db.get(Session, tampered_session_id)
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                snapshots = list((await db.execute(select(SessionSummary))).scalars())
            assert original is not None
            assert original.summary_version == 0
            assert original.running_summary is None
            assert tampered is not None
            assert tampered.summary_version == 0
            assert task is not None
            assert task.status == OutboxTaskStatus.DEAD_LETTER.value
            assert task.last_error_code == "INVALID_CONTRACT"
            assert model.calls == []
            assert snapshots == []
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_missing_protected_tail_boundary_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务伪造不存在的受保护尾部边界时不得调用模型或压缩原始消息。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "summary-protected-tail-tamper.db"
        )
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            async with session_factory() as db:
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                assert task is not None
                tampered_payload = dict(task.payload_json)
                tampered_payload["protected_tail_start_message_id"] = 999_999
                task.payload_json = tampered_payload
                await db.commit()

            model = _DeterministicSummaryModel()
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=model,
                worker_id="worker-tail-tamper",
                max_attempts=3,
            )
            assert await worker.process_next() is True

            async with session_factory() as db:
                session = await db.get(Session, session_id)
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                compressed_count = await db.scalar(
                    select(func.count(Message.id)).where(
                        Message.session_id == session_id,
                        Message.is_compressed.is_(True),
                    )
                )
            assert session is not None
            assert session.summary_version == 0
            assert task is not None
            assert task.status == OutboxTaskStatus.DEAD_LETTER.value
            assert task.last_error_code == "INVALID_CONTRACT"
            assert compressed_count == 0
            assert model.calls == []
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_expired_processing_lease_is_reclaimed_and_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """进程中断留下的过期 PROCESSING 任务必须可被新 Worker 回收。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "summary-expired-lease.db"
        )
        try:
            await _seed_summary_task(session_factory, monkeypatch)
            async with session_factory() as db:
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                assert task is not None
                task.status = OutboxTaskStatus.PROCESSING.value
                task.attempt_count = 1
                task.lease_owner = "dead-worker"
                task.lease_expires_at = (
                    datetime.now(UTC) - timedelta(seconds=1)
                ).replace(tzinfo=None)
                await db.commit()
            worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=_DeterministicSummaryModel(),
                worker_id="replacement-worker",
                max_attempts=3,
            )

            assert await worker.process_next() is True

            async with session_factory() as db:
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
            assert task is not None
            assert task.status == OutboxTaskStatus.SUCCEEDED.value
            assert task.attempt_count == 2
            assert task.lease_owner is None
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_reclaimed_lease_fences_a_late_old_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新 Worker 回收任务后，恢复运行的旧 Worker 不得覆盖任务或摘要终态。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(
            tmp_path / "summary-fencing.db"
        )
        try:
            session_id = await _seed_summary_task(session_factory, monkeypatch)
            holding_model = _HoldingSummaryModel()
            old_worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=holding_model,
                worker_id="old-worker",
                max_attempts=3,
            )
            old_run = asyncio.create_task(old_worker.process_next())
            await holding_model.started.wait()

            async with session_factory() as db:
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                assert task is not None
                old_lease_token = task.lease_owner
                task.lease_expires_at = (
                    datetime.now(UTC) - timedelta(seconds=1)
                ).replace(tzinfo=None)
                await db.commit()

            new_worker = SummaryCompactionWorker(
                session_factory=session_factory,
                model=_DeterministicSummaryModel(),
                worker_id="new-worker",
                max_attempts=3,
            )
            assert await new_worker.process_next() is True
            holding_model.release.set()
            assert await old_run is True

            async with session_factory() as db:
                session = await db.get(Session, session_id)
                task = await db.scalar(
                    select(MemoryOutboxTaskRow).where(
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.SUMMARY_COMPACT.value
                    )
                )
                snapshots = list(
                    (await db.execute(select(SessionSummary))).scalars().all()
                )
            assert session is not None
            assert session.summary_version == 1
            assert session.running_summary != "旧 Worker 的过期草稿不得生效"
            assert task is not None
            assert task.status == OutboxTaskStatus.SUCCEEDED.value
            assert task.attempt_count == 2
            assert task.lease_owner is None
            assert old_lease_token is not None
            assert len(snapshots) == 1
        finally:
            holding_model.release.set()
            await engine.dispose()

    asyncio.run(run_case())
