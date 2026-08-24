"""验证 Redis 记忆热缓存的安全边界与失败语义。"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
from backend.infrastructure.memory.redis_cache import RedisMemoryHotCache  # noqa: E402
from src.memory.contracts import MemoryScope, WorkingEntity, WorkingState  # noqa: E402


class _FakeRedis:
    """只实现缓存适配器用到的 Redis 命令，并记录写入参数。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.available = True

    async def get(self, key: str) -> str | None:
        if not self.available:
            raise ConnectionError("redis unavailable")
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> bool | None:
        if not self.available:
            raise ConnectionError("redis unavailable")
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expiries[key] = ex
        return True

    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expiries.pop(key, None)
        return int(existed)

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        del script, numkeys
        if self.values.get(key) != token:
            return 0
        return await self.delete(key)

    async def ping(self) -> bool:
        if not self.available:
            raise ConnectionError("redis unavailable")
        return True

    async def aclose(self) -> None:
        return None


def _context() -> CachedConversationContext:
    return CachedConversationContext(
        turn_count=2,
        summary_version=1,
        running_summary="用户关注低波动资产",
        recent_messages=("user: 你好", "assistant: 你好"),
    )


def test_cache_key_hides_raw_tenant_identifiers_and_applies_ttl() -> None:
    """缓存键不得泄露原始租户标识，写入必须携带有限 TTL。"""
    fake = _FakeRedis()
    cache = RedisMemoryHotCache(
        fake,
        MemoryCacheConfig(namespace="finance-test", ttl_sec=37),
    )

    asyncio.run(cache.set_context("user-secret", "session-secret", _context()))

    key = next(iter(fake.values))
    assert "user-secret" not in key
    assert "session-secret" not in key
    assert key.startswith("finance-test:memory:v1:")
    assert fake.expiries[key] == 37


def test_cache_rejects_stale_malformed_and_cross_owner_payloads() -> None:
    """持久缓存是不可信输入，版本、结构或所属范围异常时必须回源。"""

    async def scenario() -> None:
        fake = _FakeRedis()
        cache = RedisMemoryHotCache(fake, MemoryCacheConfig(namespace="finance-test"))
        await cache.set_context("u1", "s1", _context())
        key = next(iter(fake.values))

        stale = await cache.get_context(
            "u1", "s1", expected_turn_count=3, expected_summary_version=1
        )
        assert stale.status is CacheLookupStatus.STALE

        await cache.set_context("u1", "s1", _context())
        payload = json.loads(fake.values[key])
        payload["owner_ref"] = "tampered"
        fake.values[key] = json.dumps(payload)
        cross_owner = await cache.get_context(
            "u1", "s1", expected_turn_count=2, expected_summary_version=1
        )
        assert cross_owner.status is CacheLookupStatus.MALFORMED

        await cache.set_context("u1", "s1", _context())
        fake.values[key] = "{not-json"
        malformed = await cache.get_context(
            "u1", "s1", expected_turn_count=2, expected_summary_version=1
        )
        assert malformed.status is CacheLookupStatus.MALFORMED

    asyncio.run(scenario())


def test_cache_outage_degrades_without_raising_and_reports_safe_health() -> None:
    """Redis 中断只能产生显式降级，不得向聊天前台传播连接异常。"""

    async def scenario() -> None:
        fake = _FakeRedis()
        fake.available = False
        cache = RedisMemoryHotCache(fake, MemoryCacheConfig(namespace="finance-test"))

        result = await cache.get_context(
            "u1", "s1", expected_turn_count=0, expected_summary_version=0
        )
        health: Mapping[str, object] = await cache.health()

        assert result.status is CacheLookupStatus.DEGRADED
        assert health["status"] == "DEGRADED"
        assert health["error_code"] == "UNAVAILABLE"
        assert "redis://" not in json.dumps(health)

    asyncio.run(scenario())


def test_working_state_and_profile_require_authoritative_versions() -> None:
    """Working State 与画像都只能命中权威数据库给出的当前版本。"""

    async def scenario() -> None:
        cache = RedisMemoryHotCache(
            _FakeRedis(), MemoryCacheConfig(namespace="finance-test")
        )
        state = WorkingState(
            active_entity=WorkingEntity(
                symbol="600519.SH", name="贵州茅台", entity_type="stock"
            ),
            constraints=("不追高",),
            reply_preference_hint="先给结论",
            scope=MemoryScope.SESSION_SEGMENT,
            state_version=3,
            source_message_id=12,
        )
        profile = CachedCompactProfile(
            profile_version="2026-08-25T10:00:00.000000",
            risk_level="balanced",
            sectors=("消费",),
            response_pref="risk_first",
        )

        await cache.set_working_state("u1", "s1", state)
        await cache.set_profile("u1", profile)
        state_hit = await cache.get_working_state(
            "u1", "s1", expected_state_version=3
        )
        profile_hit = await cache.get_profile(
            "u1", expected_profile_version=profile.profile_version
        )

        assert state_hit.status is CacheLookupStatus.HIT
        assert state_hit.value == state
        assert profile_hit.status is CacheLookupStatus.HIT
        assert profile_hit.value == profile
        assert (
            await cache.get_profile("u1", expected_profile_version="newer")
        ).status is CacheLookupStatus.STALE

    asyncio.run(scenario())


def test_inner_payload_versions_cannot_disagree_with_envelope() -> None:
    """外层版本正确但内部版本被篡改时，三类缓存都必须拒绝命中。"""

    async def tamper_payload(
        cache: RedisMemoryHotCache,
        fake: _FakeRedis,
        *,
        key_fragment: str,
        field: str,
        value: object,
    ) -> None:
        key = next(key for key in fake.values if key_fragment in key)
        envelope = json.loads(fake.values[key])
        envelope["payload"][field] = value
        fake.values[key] = json.dumps(envelope)

    async def scenario() -> None:
        fake = _FakeRedis()
        cache = RedisMemoryHotCache(fake, MemoryCacheConfig(namespace="finance-test"))
        context = _context()
        state = WorkingState(state_version=3, scope=MemoryScope.SESSION_SEGMENT)
        profile = CachedCompactProfile(profile_version="profile-v1")
        await cache.set_context("u1", "s1", context)
        await cache.set_working_state("u1", "s1", state)
        await cache.set_profile("u1", profile)

        await tamper_payload(
            cache,
            fake,
            key_fragment=":context:",
            field="turn_count",
            value=999,
        )
        await tamper_payload(
            cache,
            fake,
            key_fragment=":working:",
            field="state_version",
            value=999,
        )
        await tamper_payload(
            cache,
            fake,
            key_fragment=":profile:",
            field="profile_version",
            value="tampered",
        )

        context_result = await cache.get_context(
            "u1", "s1", expected_turn_count=2, expected_summary_version=1
        )
        state_result = await cache.get_working_state(
            "u1", "s1", expected_state_version=3
        )
        profile_result = await cache.get_profile(
            "u1", expected_profile_version="profile-v1"
        )
        assert context_result.status is CacheLookupStatus.STALE
        assert state_result.status is CacheLookupStatus.STALE
        assert profile_result.status is CacheLookupStatus.STALE

    asyncio.run(scenario())


def test_working_state_rejects_coerced_strings_and_wrong_memory_schema() -> None:
    """对象/数字字符串字段和非权威内部 Schema 必须作为 MALFORMED 清理。"""

    async def scenario() -> None:
        fake = _FakeRedis()
        cache = RedisMemoryHotCache(fake, MemoryCacheConfig(namespace="finance-test"))
        state = WorkingState(state_version=3, scope=MemoryScope.SESSION_SEGMENT)

        await cache.set_working_state("u1", "s1", state)
        key = next(key for key in fake.values if ":working:" in key)
        envelope = json.loads(fake.values[key])
        envelope["payload"]["reply_preference_hint"] = {"bad": "type"}
        fake.values[key] = json.dumps(envelope)
        malformed_text = await cache.get_working_state(
            "u1", "s1", expected_state_version=3
        )
        assert malformed_text.status is CacheLookupStatus.MALFORMED

        await cache.set_working_state("u1", "s1", state)
        envelope = json.loads(fake.values[key])
        envelope["payload"]["schema_version"] = "memory-v999"
        fake.values[key] = json.dumps(envelope)
        malformed_schema = await cache.get_working_state(
            "u1", "s1", expected_state_version=3
        )
        assert malformed_schema.status is CacheLookupStatus.MALFORMED

    asyncio.run(scenario())


def test_singleflight_lease_is_token_fenced_and_bounded() -> None:
    """竞争者不能释放持有者租约，租约必须使用独立短 TTL。"""

    async def scenario() -> None:
        fake = _FakeRedis()
        cache = RedisMemoryHotCache(
            fake,
            MemoryCacheConfig(namespace="finance-test", lease_sec=5),
        )

        contenders = await asyncio.gather(
            *(cache.acquire_fill_lease("context", "u1", "s1") for _ in range(8))
        )
        tokens = [token for token in contenders if token is not None]
        assert len(tokens) == 1
        first = tokens[0]

        await cache.release_fill_lease("context", "u1", "s1", "wrong-token")
        assert any(key.endswith(":lease") for key in fake.values)
        await cache.release_fill_lease("context", "u1", "s1", first)
        assert all(not key.endswith(":lease") for key in fake.values)

    asyncio.run(scenario())
