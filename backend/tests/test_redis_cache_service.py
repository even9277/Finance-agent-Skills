import asyncio
import json
import time

from backend.integrations.redis.cache_service import CacheService
from backend.integrations.redis.client import RedisClient
from backend.integrations.redis.key_builder import KeyBuilder
from backend.integrations.redis.metrics import MetricsCollector


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.expires_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str):
        self._expire_if_needed(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False, **kw):
        _ = kw
        self._expire_if_needed(key)
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
            self.expires_at[key] = time.monotonic() + ex
        return True

    async def delete(self, key: str):
        self._expire_if_needed(key)
        if key in self.store:
            del self.store[key]
            self.ttls.pop(key, None)
            self.expires_at.pop(key, None)
            return 1
        return 0

    async def ttl(self, key: str):
        self._expire_if_needed(key)
        if key in self.expires_at:
            return max(0, int(self.expires_at[key] - time.monotonic()))
        return self.ttls.get(key, -1 if key in self.store else -2)

    def _expire_if_needed(self, key: str) -> None:
        deadline = self.expires_at.get(key)
        if deadline is not None and time.monotonic() >= deadline:
            self.store.pop(key, None)
            self.ttls.pop(key, None)
            self.expires_at.pop(key, None)

    def lock(self, name: str, timeout: float = 1.0, blocking_timeout: float = 1.0):
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return _FakeRedisLock(self._locks[name], timeout, blocking_timeout)


class _FakeRedisLock:
    def __init__(self, lock: asyncio.Lock, timeout: float, blocking_timeout: float):
        self._lock = lock
        self._timeout = timeout
        self._blocking_timeout = blocking_timeout
        self.acquired = False

    async def acquire(self, blocking: bool = True):
        try:
            await asyncio.wait_for(
                self._lock.acquire(),
                timeout=self._blocking_timeout,
            )
            self.acquired = True
            return True
        except asyncio.TimeoutError:
            return False

    async def release(self):
        if self.acquired and self._lock.locked():
            self._lock.release()
            self.acquired = False


def _build_service(
    *,
    redis_enabled: bool = True,
    available: bool = True,
    fake: FakeRedis | None = None,
) -> tuple[CacheService, RedisClient, MetricsCollector, FakeRedis]:
    metrics = MetricsCollector()
    client = RedisClient("redis://localhost:6379/0")
    fake_redis = fake or FakeRedis()
    client._client = fake_redis
    client._available = available
    svc = CacheService(
        client,
        KeyBuilder("test"),
        metrics,
        redis_enabled=redis_enabled,
        unavailable_recheck_sec=3600,
    )
    return svc, client, metrics, fake_redis


def test_cache_get_should_miss_when_empty():
    svc, _, metrics, _ = _build_service()
    env, meta = asyncio.run(svc.get("finagent:test:demo:item:x"))
    assert env is None
    assert meta["cache_hit"] is False
    assert meta["fallback"] is False
    assert metrics.snapshot()["counters"]["cache_miss"] == 1


def test_cache_set_then_get_should_hit():
    svc, _, metrics, _ = _build_service()
    key = "finagent:test:demo:item:hello"

    async def run():
        set_meta = await svc.set(key, {"msg": "world"}, ttl_seconds=60, source="demo")
        env, get_meta = await svc.get(key)
        return set_meta, env, get_meta

    set_meta, env, get_meta = asyncio.run(run())
    assert set_meta["success"] is True
    assert env is not None
    assert env.data == {"msg": "world"}
    assert get_meta["cache_hit"] is True
    assert metrics.snapshot()["counters"]["cache_hit"] == 1
    assert metrics.snapshot()["counters"]["cache_set"] == 1


def test_cache_set_should_reject_zero_ttl():
    svc, _, _, _ = _build_service()
    try:
        asyncio.run(svc.set("k", {"a": 1}, ttl_seconds=0, source="demo"))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_ttl_jitter_should_stay_within_expected_band():
    base = 100
    ratio = 0.1
    samples = [CacheService.ttl_with_jitter(base, ratio) for _ in range(200)]
    assert all(int(base * 0.9) <= t <= int(base * 1.1) + 1 for t in samples)


def test_get_with_version_should_return_none_on_mismatch():
    svc, _, metrics, fake = _build_service()
    key = "finagent:test:demo:item:v"

    async def run():
        await svc.set(key, {"x": 1}, ttl_seconds=30, source="demo", payload_version=1)
        return await svc.get_with_version(key, expected_payload_version=2)

    env, meta = asyncio.run(run())
    assert env is None
    assert meta.get("version_match") is False
    assert metrics.snapshot()["counters"]["cache_miss"] >= 1


def test_cache_should_fallback_when_redis_disabled():
    svc, _, metrics, _ = _build_service(redis_enabled=False)
    env, meta = asyncio.run(svc.get("any"))
    assert env is None
    assert meta["fallback"] is True
    assert meta["reason"] == "redis_disabled"
    assert metrics.snapshot()["counters"]["cache_fallback"] == 1


def test_cache_should_fallback_when_redis_unavailable():
    svc, client, metrics, _ = _build_service(available=False)

    async def _fail_ping():
        return False

    client.ping = _fail_ping  # type: ignore[method-assign]

    async def run():
        return await svc.get("any")

    env, meta = asyncio.run(run())
    assert env is None
    assert meta["fallback"] is True
    assert meta["reason"] == "redis_unavailable"


def test_cache_set_should_reject_oversize_value():
    svc, _, metrics, _ = _build_service()
    big = {"blob": "x" * (300 * 1024)}
    try:
        asyncio.run(svc.set("big-key", big, ttl_seconds=10, source="demo"))
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert metrics.snapshot()["counters"]["oversize_count"] == 1


def test_cache_delete_should_remove_key():
    svc, _, _, fake = _build_service()
    key = "finagent:test:demo:item:del"

    async def run():
        await svc.set(key, {"a": 1}, ttl_seconds=10, source="demo")
        meta = await svc.delete(key)
        env, _ = await svc.get(key)
        return meta, env

    meta, env = asyncio.run(run())
    assert meta["deleted"] is True
    assert key not in fake.store
    assert env is None


def test_set_if_absent_should_create_key_when_missing():
    svc, _, metrics, fake = _build_service()
    key = "finagent:test:demo:item:nx"

    async def run():
        created, meta = await svc.set_if_absent(key, {"first": True}, ttl_seconds=60, source="demo")
        env, _ = await svc.get(key)
        return created, meta, env

    created, meta, env = asyncio.run(run())
    assert created is True
    assert meta["success"] is True
    assert env is not None
    assert env.data == {"first": True}
    assert fake.ttls[key] > 0
    assert metrics.snapshot()["counters"]["cache_set"] == 1


def test_set_if_absent_should_not_overwrite_existing_key():
    svc, _, _, _ = _build_service()
    key = "finagent:test:demo:item:nx-existing"

    async def run():
        first, _ = await svc.set_if_absent(key, {"value": 1}, ttl_seconds=60, source="demo")
        second, second_meta = await svc.set_if_absent(key, {"value": 2}, ttl_seconds=60, source="demo")
        env, _ = await svc.get(key)
        return first, second, second_meta, env

    first, second, second_meta, env = asyncio.run(run())
    assert first is True
    assert second is False
    assert second_meta["exists"] is True
    assert env is not None
    assert env.data == {"value": 1}


def test_set_if_absent_should_fallback_when_redis_unavailable():
    svc, _, _, _ = _build_service(available=False)

    async def run():
        return await svc.set_if_absent("k", {"v": 1}, ttl_seconds=60, source="demo")

    created, meta = asyncio.run(run())
    assert created is False
    assert meta["fallback"] is True
    assert meta["reason"] == "redis_unavailable"
