"""验证长期候选治理 Worker 的领取、校验、重试与幂等边界。"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.candidates import (  # noqa: E402
    CandidateExtractionRequest,
)
from backend.db.database import Base  # noqa: E402
from backend.db.models import (  # noqa: E402
    MemoryCandidateRow,
    MemoryOutboxTaskRow,
    MemorySummaryMetadataRow,
    MemoryWorkingStateRow,
    Message,
    Session,
    User,
)
from backend.services.ltm_governance_worker import (  # noqa: E402
    LongTermGovernanceWorker,
)
from src.memory.contracts import (  # noqa: E402
    CandidateDraft,
    CandidateEvidence,
    MEMORY_SCHEMA_VERSION,
    MemoryValueKind,
    OutboxTaskKind,
    OutboxTaskStatus,
    SummaryStatus,
    build_candidate_outbox_key,
)


class _StaticExtractor:
    """离线 Provider：返回固定候选，不访问模型或网络。"""

    def __init__(self, drafts: tuple[CandidateDraft, ...]) -> None:
        self.drafts = drafts
        self.requests: list[CandidateExtractionRequest] = []

    async def extract(self, request: CandidateExtractionRequest) -> tuple[CandidateDraft, ...]:
        self.requests.append(request)
        return self.drafts


class _FailingExtractor:
    """离线 Provider：模拟短暂供应商故障。"""

    async def extract(self, request: CandidateExtractionRequest) -> tuple[CandidateDraft, ...]:
        del request
        raise RuntimeError("fixture provider unavailable")


async def _factory(tmp_path: Path):
    """创建带外键约束的隔离数据库。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ltm-worker.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _preference_draft() -> CandidateDraft:
    """返回一个可在跨会话重复后晋升的低影响偏好候选。"""
    return CandidateDraft(
        kind=MemoryValueKind.TEXT,
        category="response_preference",
        normalized_key="response_preference:conclusion_first",
        confidence=0.95,
        evidence=(
            CandidateEvidence(
                session_id="worker-session",
                message_id=1,
                source_role="user",
                query_hash="fixture-query",
                observed_on=date(2026, 8, 25),
                confidence=0.95,
                state_version=1,
                summary_version=1,
            ),
        ),
        content="回答先给结论，再解释风险",
        conflict_key="response_preference:default",
    )


async def _seed_task(session_factory, *, status: str = OutboxTaskStatus.PENDING.value) -> None:
    """写入 Worker 读取所需的用户、消息、摘要、状态和 Outbox 任务。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with session_factory() as db:
        db.add(User(id="worker-user", display_name="Worker 测试用户"))
        db.add(Session(id="worker-session", user_id="worker-user", mode="chat"))
        db.add_all(
            [
                Message(
                    id=1,
                    session_id="worker-session",
                    role="user",
                    content="以后先给结论，再解释风险",
                ),
                Message(
                    id=2,
                    session_id="worker-session",
                    role="user",
                    content="请保持这个回答习惯",
                ),
            ]
        )
        # 无 ORM relationship 的历史模型不会自动保证同一批 INSERT 的外键顺序。
        await db.flush()
        db.add_all(
            [
                MemoryWorkingStateRow(
                    session_id="worker-session",
                    schema_version=MEMORY_SCHEMA_VERSION,
                    state_version=1,
                    candidate_entities=[],
                    constraints=[],
                    reply_preference_hint="",
                    scope="session_segment",
                ),
                MemorySummaryMetadataRow(
                    session_id="worker-session",
                    summary_version=1,
                    status=SummaryStatus.SUCCEEDED.value,
                    source_start_message_id=1,
                    source_end_message_id=2,
                    source_message_count=2,
                    input_token_estimate=20,
                    output_token_count=8,
                    prompt_version="memory-summary-v1",
                    schema_version=MEMORY_SCHEMA_VERSION,
                ),
                MemoryOutboxTaskRow(
                    id="worker-task",
                    user_id="worker-user",
                    session_id="worker-session",
                    aggregate_type="chat_summary",
                    aggregate_id="worker-session",
                    task_kind=OutboxTaskKind.CANDIDATE_EXTRACT.value,
                    payload_json={
                        "session_id": "worker-session",
                        "expected_summary_version": 1,
                        "expected_state_version": 1,
                        "source_start_message_id": 1,
                        "source_end_message_id": 2,
                        "prompt_version": "memory-candidate-rem-v1",
                    },
                    status=status,
                    idempotency_key=build_candidate_outbox_key("worker-session", 1),
                    schema_version=MEMORY_SCHEMA_VERSION,
                    available_at=now,
                    attempt_count=0,
                ),
            ]
        )
        await db.commit()


def _worker(session_factory, extractor, *, max_attempts: int = 2) -> LongTermGovernanceWorker:
    """构造不依赖生产配置的离线 Worker。"""
    from backend.application.memory.candidates import CandidateExtractionUseCase

    return LongTermGovernanceWorker(
        session_factory=session_factory,
        extraction=CandidateExtractionUseCase(extractor=extractor),
        worker_id="worker-test",
        max_attempts=max_attempts,
        lease_seconds=30,
    )


@pytest.mark.integration
def test_ltm_worker_success_creates_governed_candidate(tmp_path: Path) -> None:
    """Worker 应校验用户证据并把任务与候选在同一事务内完成。"""

    async def run_case() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed_task(session_factory)
            extractor = _StaticExtractor((_preference_draft(),))
            worker = _worker(session_factory, extractor)

            assert await worker.process_next() is True

            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
                candidate = await db.scalar(select(MemoryCandidateRow))
            assert task is not None
            assert task.status == OutboxTaskStatus.SUCCEEDED.value
            assert candidate is not None
            assert candidate.user_id == "worker-user"
            assert len(extractor.requests) == 1
            assert [message.message_id for message in extractor.requests[0].messages] == [1, 2]
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_ltm_worker_malformed_payload_goes_to_dead_letter(tmp_path: Path) -> None:
    """损坏的持久任务必须 fail-closed，不能调用 Provider 或卡在处理中。"""

    async def run_case() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed_task(session_factory)
            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
                assert task is not None
                task.payload_json = {"session_id": "worker-session"}
                await db.commit()
            extractor = _StaticExtractor(())
            assert await _worker(session_factory, extractor).process_next() is True
            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
            assert task is not None
            assert task.status == OutboxTaskStatus.DEAD_LETTER.value
            assert task.last_error_code == "INVALID_CONTRACT"
            assert extractor.requests == []
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_ltm_worker_provider_failure_retries_then_dead_letters(tmp_path: Path) -> None:
    """Provider 故障只允许有限重试，超过预算后进入死信。"""

    async def run_case() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed_task(session_factory)
            worker = _worker(session_factory, _FailingExtractor(), max_attempts=2)
            assert await worker.process_next() is True
            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
                assert task is not None
                assert task.status == OutboxTaskStatus.RETRY.value
                task.available_at = datetime.now(UTC).replace(tzinfo=None)
                await db.commit()
            assert await worker.process_next() is True
            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
            assert task is not None
            assert task.status == OutboxTaskStatus.DEAD_LETTER.value
            assert task.last_error_code == "PROVIDER_UNAVAILABLE"
            assert task.attempt_count == 2
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_ltm_worker_reclaims_expired_lease(tmp_path: Path) -> None:
    """新 Worker 应能回收过期租约并推进任务，旧 token 不再拥有写权限。"""

    async def run_case() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed_task(session_factory, status=OutboxTaskStatus.PROCESSING.value)
            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
                assert task is not None
                task.attempt_count = 1
                task.lease_owner = "old-worker:expired"
                task.lease_expires_at = (
                    datetime.now(UTC) - timedelta(seconds=1)
                ).replace(tzinfo=None)
                await db.commit()
            assert await _worker(session_factory, _StaticExtractor((_preference_draft(),))).process_next()
            async with session_factory() as db:
                task = await db.get(MemoryOutboxTaskRow, "worker-task")
            assert task is not None
            assert task.status == OutboxTaskStatus.SUCCEEDED.value
            assert task.attempt_count == 2
            assert task.lease_owner is None
        finally:
            await engine.dispose()

    asyncio.run(run_case())
