"""验证 M6 派生索引、混合召回和用户/版本隔离合同。"""

# 测试需要将仓库和 Agent 包根目录加入 sys.path，再导入运行时模块。
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from typing import cast
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.retrieval import MemoryRetrievalRequest
from backend.application.memory.retrieval import MemoryRetrievalUseCase
from backend.db.database import Base
from backend.db.models import MemoryProviderReferenceRow, MemoryRecordRow, User
from backend.services.semantic_index_worker import SemanticIndexWorker
from backend.infrastructure.memory.index_tasks import enqueue_index_upsert
from backend.infrastructure.memory.retrieval_repository import (
    SqlAlchemyMemoryRetrievalRepository,
)
from backend.infrastructure.memory.semantic_provider import (
    DeterministicEmbeddingProvider,
    Mem0SemanticProvider,
    PgVectorSemanticProvider,
)
from backend.application.chat.contracts import ChatCommand
from backend.application.chat.use_case import ControlledChatUseCase
from backend.infrastructure.chat.testing import (
    FakeModelProvider,
    FakeToolProvider,
    InMemoryConversationRepository,
    InMemoryTraceSink,
)
from src.conversation.workflow import ControlledConversationWorkflow
from src.memory.contracts import (
    MemoryRecordStatus,
    MemoryValueKind,
    RetrievalItem,
    RetrievalResult,
    RetrievalStatus,
)


async def _fixture(tmp_path: Path):
    """创建单用例 SQLite 数据库，避免读取工作区 finance.db。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'm6.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all(
            [
                User(id="m6-user-a", display_name="A"),
                User(id="m6-user-b", display_name="B"),
                MemoryRecordRow(
                    id="record-a-v1",
                    user_id="m6-user-a",
                    kind=MemoryValueKind.TEXT.value,
                    category="preference",
                    content="用户偏好低波动和长期投资",
                    status=MemoryRecordStatus.ACTIVE.value,
                    scope="user",
                    version=1,
                    source="user_command",
                    evidence_ref="cmd:m6-a",
                    policy_version="memory-policy-v1",
                    activation_source="explicit_user",
                ),
                MemoryRecordRow(
                    id="record-b-v1",
                    user_id="m6-user-b",
                    kind=MemoryValueKind.TEXT.value,
                    category="preference",
                    content="用户偏好高风险短线交易",
                    status=MemoryRecordStatus.ACTIVE.value,
                    scope="user",
                    version=1,
                    source="user_command",
                    evidence_ref="cmd:m6-b",
                    policy_version="memory-policy-v1",
                    activation_source="explicit_user",
                ),
            ]
        )
        await db.commit()
    return engine, factory


def test_deterministic_embedding_is_stable_and_normalized() -> None:
    """相同文本每次生成相同向量，离线测试不依赖模型服务。"""
    embedder = DeterministicEmbeddingProvider(dimensions=32)
    first = embedder.embed("长期投资 低波动")
    second = embedder.embed("长期投资 低波动")
    assert first == second
    assert len(first) == 32
    assert round(sum(item * item for item in first), 6) == 1.0


def test_pgvector_provider_and_retrieval_enforce_owner_and_budget(tmp_path: Path) -> None:
    """派生 Provider 只返回同用户当前版本，召回再执行 token budget packing。"""

    async def scenario() -> None:
        engine, factory = await _fixture(tmp_path)
        try:
            provider = PgVectorSemanticProvider(
                factory,
                embedder=DeterministicEmbeddingProvider(dimensions=32),
            )
            await provider.upsert(
                user_id="m6-user-a",
                record_id="record-a-v1",
                memory_version=1,
                category="preference",
                content="用户偏好低波动和长期投资",
                metadata={"memory_record_id": "record-a-v1", "memory_version": 1},
            )
            await provider.upsert(
                user_id="m6-user-b",
                record_id="record-b-v1",
                memory_version=1,
                category="preference",
                content="用户偏好高风险短线交易",
                metadata={"memory_record_id": "record-b-v1", "memory_version": 1},
            )
            hits = await provider.search(
                user_id="m6-user-a",
                query="长期投资",
                top_k=5,
                min_score=0.0,
            )
            assert {item.record_id for item in hits} == {"record-a-v1"}

            async with factory() as db:
                result = await SqlAlchemyMemoryRetrievalRepository(db).retrieve(
                    MemoryRetrievalRequest(
                        user_id="m6-user-a",
                        query="长期投资",
                        top_k=5,
                        token_budget=2,
                    ),
                    provider,
                )
            assert result.items == ()
            assert result.token_count == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_deleted_authority_is_not_recalled_after_provider_hit(tmp_path: Path) -> None:
    """Provider 中残留的旧索引不能绕过权威状态过滤。"""

    async def scenario() -> None:
        engine, factory = await _fixture(tmp_path)
        try:
            provider = PgVectorSemanticProvider(
                factory,
                embedder=DeterministicEmbeddingProvider(dimensions=32),
            )
            await provider.upsert(
                user_id="m6-user-a",
                record_id="record-a-v1",
                memory_version=1,
                category="preference",
                content="用户偏好低波动和长期投资",
                metadata={},
            )
            async with factory() as db:
                row = await db.scalar(
                    select(MemoryRecordRow).where(MemoryRecordRow.id == "record-a-v1")
                )
                assert row is not None
                row.status = MemoryRecordStatus.DELETED.value
                await db.commit()
                result = await SqlAlchemyMemoryRetrievalRepository(db).retrieve(
                    MemoryRetrievalRequest(user_id="m6-user-a", query="长期投资"),
                    provider,
                )
            assert result.items == ()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_semantic_timeout_degrades_to_authoritative_lexical_recall(tmp_path: Path) -> None:
    """语义 Provider 超时只降级增强层，PostgreSQL 词法召回仍返回结果。"""

    class _SlowProvider:
        name = "slow-provider"

        async def search(self, **kwargs):
            del kwargs
            await asyncio.sleep(0.05)
            return ()

    async def scenario() -> None:
        engine, factory = await _fixture(tmp_path)
        try:
            async with factory() as db:
                repository = SqlAlchemyMemoryRetrievalRepository(
                    db,
                    semantic_timeout_sec=0.001,
                )
                result = await repository.retrieve(
                    MemoryRetrievalRequest(
                        user_id="m6-user-a",
                        query="长期投资",
                    ),
                    cast(PgVectorSemanticProvider, _SlowProvider()),
                )
            assert result.status is RetrievalStatus.PARTIAL
            assert result.items[0].record_id == "record-a-v1"
            assert result.degraded_providers == ("slow-provider",)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_mem0_adapter_rejects_cross_user_results_and_missing_provider_id() -> None:
    """Mem0 返回值必须带项目用户边界和可持久化 Provider ID。"""

    class _FakeMem0:
        async def search(self, *args, **kwargs):
            del args, kwargs
            return {
                "results": [
                    {
                        "id": "foreign-id",
                        "score": 0.99,
                        "metadata": {
                            "project_user_id": "m6-user-b",
                            "memory_record_id": "record-b-v1",
                            "memory_version": 1,
                        },
                    }
                ]
            }

        async def add(self, *args, **kwargs):
            del args, kwargs
            return {"results": [{}]}

    async def scenario() -> None:
        provider = Mem0SemanticProvider(_FakeMem0())
        hits = await provider.search(
            user_id="m6-user-a",
            query="投资偏好",
            top_k=5,
            min_score=0.1,
        )
        assert hits == ()
        with pytest.raises(ValueError, match="MEM0_PROVIDER_ID_MISSING"):
            await provider.upsert(
                user_id="m6-user-a",
                record_id="record-a-v1",
                memory_version=1,
                category="preference",
                content="用户偏好长期投资",
                metadata={},
            )

    asyncio.run(scenario())


def test_retrieval_context_reaches_synthesis_but_not_evidence() -> None:
    """历史记忆进入合成合同，同时保持 accepted evidence 单独受 Verifier 控制。"""

    class _FakeRetrieval:
        async def execute(self, request):
            del request
            return RetrievalResult(
                status=RetrievalStatus.SUCCEEDED,
                items=(
                    RetrievalItem(
                        record_id="memory-1",
                        category="preference",
                        content="用户偏好长期投资",
                        score=0.9,
                        retrieval_reasons=("lexical",),
                        memory_version=1,
                    ),
                ),
                token_count=4,
            )

    async def scenario() -> None:
        model = FakeModelProvider()
        trace = InMemoryTraceSink()
        use_case = ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(
                model=model,
                tool=FakeToolProvider(),
                trace=trace,
            ),
            repository=InMemoryConversationRepository(),
            retrieval=cast(MemoryRetrievalUseCase, _FakeRetrieval()),
        )
        outcome = await use_case.execute(
            ChatCommand(
                user_id="m6-user-a",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
                session_id="m6-session",
            )
        )
        assert outcome.workflow_result is not None
        context = model.calls[0].context
        assert context.retrieved_memories[0].record_id == "memory-1"
        assert context.rejected_evidence == ()
        context_event = trace.events[0]
        attrs = {item.key: item.value for item in context_event.attributes}
        assert attrs["memory_hit_count"] == 1
        assert attrs["memory_context_status"] == "USED"

    asyncio.run(scenario())


def test_semantic_worker_is_idempotent_and_creates_provider_reference(tmp_path: Path) -> None:
    """Outbox 任务只消费一次，Provider 映射可重复处理而不产生重复引用。"""

    class _FakeProvider:
        name = "fake-semantic"

        def __init__(self) -> None:
            self.upserts = 0
            self.deletes = 0

        async def upsert(self, **kwargs):
            self.upserts += 1
            return f"fake:{kwargs['record_id']}:{kwargs['memory_version']}"

        async def delete(self, **kwargs):
            del kwargs
            self.deletes += 1

        async def search(self, **kwargs):
            del kwargs
            return ()

    async def scenario() -> None:
        engine, factory = await _fixture(tmp_path)
        try:
            async with factory() as db:
                row = await db.scalar(
                    select(MemoryRecordRow).where(MemoryRecordRow.id == "record-a-v1")
                )
                assert row is not None
                assert await enqueue_index_upsert(db, row)
                await db.commit()
            provider = _FakeProvider()
            worker = SemanticIndexWorker(
                session_factory=factory,
                provider=provider,
                max_attempts=2,
            )
            assert await worker.process_next()
            assert not await worker.process_next()
            assert provider.upserts == 1
            async with factory() as db:
                references = (await db.execute(select(MemoryProviderReferenceRow))).scalars().all()
            assert len(references) == 1
            assert references[0].status == "ACTIVE"
        finally:
            await engine.dispose()

    asyncio.run(scenario())
