import asyncio

import backend.integrations.redis.runtime as redis_runtime
from backend.integrations.redis.client import RedisClient
from backend.integrations.redis.runtime import get_redis_health_dict


class _PingOkClient:
    async def ping(self):
        return True


def _reset_runtime_test_state() -> None:
    redis_runtime._redis_enabled_override = None
    redis_runtime._redis_client = None


def test_health_dict_should_return_disabled_when_redis_off():
    redis_runtime._redis_enabled_override = False
    try:
        result = asyncio.run(get_redis_health_dict())
        assert result == {"status": "disabled"}
    finally:
        _reset_runtime_test_state()


def test_health_dict_should_return_ok_when_ping_success():
    redis_runtime._redis_enabled_override = True
    client = RedisClient("redis://localhost:6379/0")
    client._client = _PingOkClient()
    client._available = True
    redis_runtime._redis_client = client
    try:
        result = asyncio.run(get_redis_health_dict())
        assert result["status"] == "ok"
        assert "latency_ms" in result
    finally:
        _reset_runtime_test_state()


def test_health_dict_should_return_degraded_when_ping_fails():
    redis_runtime._redis_enabled_override = True
    client = RedisClient("redis://localhost:6379/0")
    client._client = object()
    client._available = False
    client._last_error = "connection refused"

    async def fail_ping():
        return False

    client.ping = fail_ping  # type: ignore[method-assign]
    redis_runtime._redis_client = client
    try:
        result = asyncio.run(get_redis_health_dict())
        assert result["status"] == "degraded"
        assert "error" in result
    finally:
        _reset_runtime_test_state()
