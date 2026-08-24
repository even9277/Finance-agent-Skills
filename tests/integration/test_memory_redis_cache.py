"""在真实隔离 Redis 上验证记忆热缓存的运行语义。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

redis = pytest.importorskip("redis.asyncio")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.cache import (  # noqa: E402
    CacheLookupStatus,
    CachedCompactProfile,
    CachedConversationContext,
    MemoryCacheConfig,
)
from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.db.database import Base  # noqa: E402
from backend.db.models import (  # noqa: E402
    MemoryOutboxTaskRow,
    MemoryWorkingStateRow,
    Message,
    User,
)
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryTraceSink,
)
from backend.infrastructure.memory.redis_cache import RedisMemoryHotCache  # noqa: E402
from backend.db.models import Session  # noqa: E402
from backend.infrastructure.chat.repository import (  # noqa: E402
    SqlAlchemyConversationRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402
from src.memory.contracts import (  # noqa: E402
    MemoryScope,
    OutboxTaskKind,
    WorkingState,
)


def _redis_url() -> str:
    value = os.getenv("TEST_REDIS_URL", "").strip()
    if not value:
        pytest.skip("TEST_REDIS_URL 未设置；真实 Redis 集成测试仅在隔离 Compose 中执行")
    return value


@pytest.mark.integration
def test_real_redis_ttl_isolation_invalidation_and_corruption_fallback() -> None:
    """真实 Redis 必须保持 TTL、租户隔离、失效和损坏回源合同。"""

    async def scenario() -> None:
        namespace = f"finance-it-{uuid.uuid4().hex}"
        client = redis.Redis.from_url(_redis_url(), decode_responses=True, protocol=2)
        cache = RedisMemoryHotCache(
            client,
            MemoryCacheConfig(namespace=namespace, ttl_sec=20, lease_sec=3),
        )
        context = CachedConversationContext(
            turn_count=4,
            summary_version=2,
            running_summary="隔离测试摘要",
            recent_messages=("user: A", "assistant: B"),
        )
        try:
            await cache.set_context("u1", "s1", context)
            hit = await cache.get_context(
                "u1", "s1", expected_turn_count=4, expected_summary_version=2
            )
            other = await cache.get_context(
                "u2", "s1", expected_turn_count=4, expected_summary_version=2
            )
            assert hit.status is CacheLookupStatus.HIT
            assert hit.value == context
            assert other.status is CacheLookupStatus.MISS

            keys = await client.keys(f"{namespace}:*")
            assert len(keys) == 1
            ttl = await client.ttl(keys[0])
            assert 0 < ttl <= 20

            await client.set(keys[0], "bad-json", ex=20)
            malformed = await cache.get_context(
                "u1", "s1", expected_turn_count=4, expected_summary_version=2
            )
            assert malformed.status is CacheLookupStatus.MALFORMED
            assert await client.exists(keys[0]) == 0

            await cache.set_context("u1", "s1", context)
            await cache.invalidate_context("u1", "s1")
            assert (
                await cache.get_context(
                    "u1", "s1", expected_turn_count=4, expected_summary_version=2
                )
            ).status is CacheLookupStatus.MISS
        finally:
            remaining_keys = await client.keys(f"{namespace}:*")
            if remaining_keys:
                await client.delete(*remaining_keys)
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_unreachable_real_redis_endpoint_is_fail_open() -> None:
    """不可达端点应在短超时内返回 DEGRADED，而不是抛出或长时间重试。"""

    async def scenario() -> None:
        client = redis.Redis.from_url(
            "redis://127.0.0.1:1/15",
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=0.05,
            socket_timeout=0.05,
        )
        cache = RedisMemoryHotCache(client, MemoryCacheConfig(namespace="finance-down"))
        try:
            result = await asyncio.wait_for(
                cache.get_context(
                    "u1", "s1", expected_turn_count=0, expected_summary_version=0
                ),
                timeout=1,
            )
            assert result.status is CacheLookupStatus.DEGRADED
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_unreachable_redis_falls_back_to_authoritative_chat_transaction() -> None:
    """Redis 不可达时，两轮真实 Use Case 仍从数据库读取并原子保存状态。"""

    async def scenario() -> None:
        database_url = os.getenv(
            "TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:"
        )
        engine = create_async_engine(database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        client = redis.Redis.from_url(
            "redis://127.0.0.1:1/15",
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=0.05,
            socket_timeout=0.05,
        )
        cache = RedisMemoryHotCache(client, MemoryCacheConfig(namespace="finance-fallback"))
        workflow = ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=FakeToolProvider(),
            trace=InMemoryTraceSink(),
            skill_catalog=SkillRegistry().conversation_snapshot(),
        )
        try:
            if os.getenv("TEST_DATABASE_URL"):
                assert engine.dialect.name == "postgresql"
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with session_factory() as db:
                db.add(User(id="redis-fallback-user", display_name="Redis fallback"))
                await db.commit()
            async with session_factory() as db:
                first = await ControlledChatUseCase(
                    workflow=workflow,
                    repository=SqlAlchemyConversationRepository(db, cache=cache),
                ).execute(
                    ChatCommand(
                        user_id="redis-fallback-user",
                        message="查询贵州茅台 600519.SH",
                    )
                )
            async with session_factory() as db:
                second = await ControlledChatUseCase(
                    workflow=workflow,
                    repository=SqlAlchemyConversationRepository(db, cache=cache),
                ).execute(
                    ChatCommand(
                        user_id="redis-fallback-user",
                        session_id=first.session_id,
                        message="继续说明它的风险",
                    )
                )
            async with session_factory() as db:
                message_count = await db.scalar(
                    select(func.count(Message.id)).where(
                        Message.session_id == first.session_id
                    )
                )
                state_count = await db.scalar(
                    select(func.count(MemoryWorkingStateRow.session_id)).where(
                        MemoryWorkingStateRow.session_id == first.session_id
                    )
                )
                turn_outbox_count = await db.scalar(
                    select(func.count(MemoryOutboxTaskRow.id)).where(
                        MemoryOutboxTaskRow.session_id == first.session_id,
                        MemoryOutboxTaskRow.task_kind
                        == OutboxTaskKind.TURN_COMMITTED.value,
                    )
                )
            assert second.session_id == first.session_id
            assert message_count == 4
            assert state_count == 1
            assert turn_outbox_count == 2
            assert (await cache.health())["status"] == "DEGRADED"
        finally:
            async with session_factory() as db:
                await db.execute(
                    delete(User).where(User.id == "redis-fallback-user")
                )
                await db.commit()
            await client.aclose()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_real_redis_rejects_inner_version_tampering_for_all_cache_kinds() -> None:
    """真实 Redis 中外层版本未变、内部版本被改时也不得返回 HIT。"""

    async def scenario() -> None:
        namespace = f"finance-tamper-{uuid.uuid4().hex}"
        client = redis.Redis.from_url(_redis_url(), decode_responses=True, protocol=2)
        cache = RedisMemoryHotCache(client, MemoryCacheConfig(namespace=namespace))
        try:
            await cache.set_context(
                "u1",
                "s1",
                CachedConversationContext(
                    turn_count=2,
                    summary_version=1,
                    running_summary=None,
                ),
            )
            await cache.set_working_state(
                "u1",
                "s1",
                WorkingState(state_version=3, scope=MemoryScope.SESSION_SEGMENT),
            )
            await cache.set_profile(
                "u1", CachedCompactProfile(profile_version="profile-v1")
            )
            mutations = {
                "context": ("turn_count", 999),
                "working": ("state_version", 999),
                "profile": ("profile_version", "tampered"),
            }
            for kind, (field, value) in mutations.items():
                keys = await client.keys(f"{namespace}:memory:v1:{kind}:*")
                assert len(keys) == 1
                envelope = json.loads(await client.get(keys[0]))
                envelope["payload"][field] = value
                await client.set(keys[0], json.dumps(envelope), ex=60)

            assert (
                await cache.get_context(
                    "u1", "s1", expected_turn_count=2, expected_summary_version=1
                )
            ).status is CacheLookupStatus.STALE
            assert (
                await cache.get_working_state("u1", "s1", expected_state_version=3)
            ).status is CacheLookupStatus.STALE
            assert (
                await cache.get_profile("u1", expected_profile_version="profile-v1")
            ).status is CacheLookupStatus.STALE
        finally:
            remaining_keys = await client.keys(f"{namespace}:*")
            if remaining_keys:
                await client.delete(*remaining_keys)
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_real_redis_lease_expiry_and_token_fencing() -> None:
    """真实 Redis 上只有一个租约持有者，过期可重获且旧 token 无权释放。"""

    async def scenario() -> None:
        namespace = f"finance-lease-{uuid.uuid4().hex}"
        client = redis.Redis.from_url(_redis_url(), decode_responses=True, protocol=2)
        cache = RedisMemoryHotCache(
            client,
            MemoryCacheConfig(namespace=namespace, lease_sec=1),
        )
        try:
            contenders = await asyncio.gather(
                *(cache.acquire_fill_lease("context", "u1", "s1") for _ in range(12))
            )
            tokens = [token for token in contenders if token is not None]
            assert len(tokens) == 1
            first_token = tokens[0]

            await cache.release_fill_lease("context", "u1", "s1", "wrong-token")
            assert await cache.acquire_fill_lease("context", "u1", "s1") is None

            await asyncio.sleep(1.1)
            second_token = await cache.acquire_fill_lease("context", "u1", "s1")
            assert second_token is not None
            assert second_token != first_token

            await cache.release_fill_lease("context", "u1", "s1", first_token)
            assert await cache.acquire_fill_lease("context", "u1", "s1") is None
            await cache.release_fill_lease("context", "u1", "s1", second_token)
            final_token = await cache.acquire_fill_lease("context", "u1", "s1")
            assert final_token is not None
            await cache.release_fill_lease("context", "u1", "s1", final_token)
        finally:
            remaining_keys = await client.keys(f"{namespace}:*")
            if remaining_keys:
                await client.delete(*remaining_keys)
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_real_redis_singleflight_collapses_concurrent_repository_cold_reads() -> None:
    """两个 Repository 同时冷读时，真实 Redis 租约应把数据库回源收敛为一次。"""

    class _HistoryResult:
        def __init__(self) -> None:
            self._messages = [
                SimpleNamespace(role="user", content="第一轮"),
                SimpleNamespace(role="assistant", content="已回答"),
            ]

        def scalars(self) -> _HistoryResult:
            return self

        def all(self) -> list[SimpleNamespace]:
            return self._messages

    class _CountingSession:
        def __init__(self) -> None:
            self.execute_count = 0

        async def execute(self, _statement: object) -> _HistoryResult:
            self.execute_count += 1
            await asyncio.sleep(0.02)
            return _HistoryResult()

    async def scenario() -> None:
        namespace = f"finance-singleflight-{uuid.uuid4().hex}"
        client = redis.Redis.from_url(_redis_url(), decode_responses=True, protocol=2)
        cache = RedisMemoryHotCache(
            client,
            MemoryCacheConfig(
                namespace=namespace,
                lease_sec=2,
                singleflight_wait_ms=100,
            ),
        )
        counting_db = _CountingSession()
        db = cast(AsyncSession, counting_db)
        first_repository = SqlAlchemyConversationRepository(db, cache=cache)
        second_repository = SqlAlchemyConversationRepository(db, cache=cache)
        session = Session(id="session-singleflight", user_id="u1", mode="chat")
        session.turn_count = 1
        session.summary_version = 0
        session.running_summary = None
        try:
            first, second = await asyncio.gather(
                first_repository._load_context_snapshot(user_id="u1", session=session),
                second_repository._load_context_snapshot(user_id="u1", session=session),
            )
            assert first == second
            assert counting_db.execute_count == 1
            assert (
                await cache.get_context(
                    "u1",
                    session.id,
                    expected_turn_count=1,
                    expected_summary_version=0,
                )
            ).status is CacheLookupStatus.HIT
        finally:
            remaining_keys = await client.keys(f"{namespace}:*")
            if remaining_keys:
                await client.delete(*remaining_keys)
            await client.aclose()

    asyncio.run(scenario())
