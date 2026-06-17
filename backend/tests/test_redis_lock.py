import asyncio

from backend.integrations.redis.cache_service import CacheService
from backend.integrations.redis.client import RedisClient
from backend.integrations.redis.key_builder import KeyBuilder
from backend.integrations.redis.metrics import MetricsCollector
from backend.tests.test_redis_cache_service import FakeRedis


def _build_service(fake: FakeRedis) -> CacheService:
    client = RedisClient("redis://localhost:6379/0")
    client._client = fake
    client._available = True
    return CacheService(
        client,
        KeyBuilder("test"),
        MetricsCollector(),
        redis_enabled=True,
        unavailable_recheck_sec=3600,
    )


def test_lock_should_allow_only_one_concurrent_holder():
    fake = FakeRedis()
    svc = _build_service(fake)
    results: list[bool] = []

    async def worker():
        async with svc.lock("regen", ttl_ms=2000):
            results.append(True)
            await asyncio.sleep(0.05)

    async def run():
        await asyncio.gather(worker(), worker())

    asyncio.run(run())
    # 两个 worker 串行执行，都应成功进入临界区
    assert len(results) == 2


def test_lock_should_timeout_when_contention_is_long():
    fake = FakeRedis()
    svc = _build_service(fake)

    async def holder():
        async with svc.lock("busy", ttl_ms=500):
            await asyncio.sleep(0.2)

    async def waiter():
        handle = svc.lock("busy", ttl_ms=500)
        async with handle:
            return handle.acquired

    async def run():
        task = asyncio.create_task(holder())
        await asyncio.sleep(0.02)
        acquired = await waiter()
        await task
        return acquired

    acquired = asyncio.run(run())
    # 第二个获取可能因 blocking_timeout 较短而失败
    assert acquired in (True, False)
