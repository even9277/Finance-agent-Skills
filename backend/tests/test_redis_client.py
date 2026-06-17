import asyncio

from backend.integrations.redis.client import RedisClient


class DummyRedisOk:
    async def ping(self):
        return True

    async def aclose(self):
        return None


class DummyRedisFail:
    async def ping(self):
        raise RuntimeError("boom")

    async def aclose(self):
        return None


class DummyPool:
    async def aclose(self):
        return None


def test_redis_client_ping_success_should_mark_available():
    client = RedisClient("redis://localhost:6379/0")
    client._client = DummyRedisOk()
    ok = asyncio.run(client.ping())
    assert ok is True
    assert client.is_available() is True
    assert client.health_snapshot().status == "ok"


def test_redis_client_ping_failure_should_mark_degraded():
    client = RedisClient("redis://localhost:6379/0")
    client._client = DummyRedisFail()
    ok = asyncio.run(client.ping())
    assert ok is False
    assert client.is_available() is False
    assert client.health_snapshot().status == "degraded"
    assert client.health_snapshot().error


def test_redis_client_close_should_not_raise():
    client = RedisClient("redis://localhost:6379/0")
    client._client = DummyRedisOk()
    client._pool = DummyPool()
    asyncio.run(client.close())
    assert client.get_client() is None
    assert client.is_available() is False

