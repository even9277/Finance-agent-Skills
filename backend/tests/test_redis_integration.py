"""
Redis 集成测试：连接真实 Redis，验证 set → get → TTL 过期 → miss。

前置条件（任一不可用则 skip）：
  cd /root/Finance/docker && docker compose up -d redis
  默认 URL：redis://:finance_redis_123@127.0.0.1:6379/0
  可通过环境变量 REDIS_TEST_URL 覆盖。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid

import pytest

try:
    from redis.asyncio import Redis as _RedisAsyncio  # noqa: F401
except ImportError:
    _RedisAsyncio = None  # type: ignore[misc, assignment]

from backend.integrations.redis.cache_service import CacheService
from backend.integrations.redis.client import RedisClient
from backend.integrations.redis.key_builder import KeyBuilder
from backend.integrations.redis.metrics import MetricsCollector

pytestmark = pytest.mark.integration

DEFAULT_REDIS_URL = os.environ.get(
    "REDIS_TEST_URL",
    "redis://:finance_redis_123@127.0.0.1:6379/0",
)
INTEGRATION_ENV = os.environ.get("REDIS_TEST_NAMESPACE_ENV", "dev")


def _redis_tcp_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _parse_redis_host_port(url: str) -> tuple[str, int]:
    # 仅覆盖本仓库默认本地 URL，复杂 URL 回退 127.0.0.1:6379
    if "@" in url:
        host_part = url.split("@", 1)[1]
    else:
        host_part = url.split("://", 1)[-1]
    host_port = host_part.split("/", 1)[0]
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        return host or "127.0.0.1", int(port_str)
    return host_port or "127.0.0.1", 6379


@pytest.fixture(scope="module")
def require_live_redis():
    if _RedisAsyncio is None:
        pytest.skip(
            "需要 redis-py：在项目 .venv 中执行 pip install -r backend/requirements.txt"
        )
    host, port = _parse_redis_host_port(DEFAULT_REDIS_URL)
    if not _redis_tcp_reachable(host, port):
        pytest.skip(
            "需要本地 Redis 可连接。"
            "建议：cd /root/Finance/docker && docker compose up -d redis；"
            f"默认 URL={DEFAULT_REDIS_URL}"
        )


def _skip_if_connect_failed(client: RedisClient) -> None:
    if client.is_available():
        return
    snap = client.health_snapshot()
    reason = snap.error or "unknown"
    pytest.skip(f"Redis 连接失败: {reason}（URL={DEFAULT_REDIS_URL}）")


def _build_live_service() -> tuple[CacheService, RedisClient, str]:
    client = RedisClient(
        DEFAULT_REDIS_URL,
        max_connections=5,
        socket_timeout_ms=3000,
        connect_timeout_ms=3000,
        health_check_interval_sec=30,
    )
    metrics = MetricsCollector()
    svc = CacheService(
        client,
        KeyBuilder(INTEGRATION_ENV),
        metrics,
        redis_enabled=True,
        unavailable_recheck_sec=5,
        default_ttl_jitter_ratio=0.0,  # 集成测试用固定 TTL，便于断言过期
    )
    return svc, client, f"integration-{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_cache_set_get_should_hit(require_live_redis):
    async def _run() -> None:
        svc, client, item_id = _build_live_service()
        try:
            await client.connect()
            _skip_if_connect_failed(client)

            key = svc.key_builder.demo(item_id)
            meta_set = await svc.set(
                key,
                {"msg": "integration"},
                ttl_seconds=30,
                source="integration",
            )
            assert meta_set.get("success") is True

            envelope, meta_get = await svc.get(key)
            assert meta_get.get("cache_hit") is True
            assert envelope is not None
            assert envelope.data == {"msg": "integration"}
            assert envelope.source == "integration"
        finally:
            await client.close()

    asyncio.run(_run())


@pytest.mark.integration
def test_cache_should_miss_after_ttl(require_live_redis):
    async def _run() -> None:
        svc, client, item_id = _build_live_service()
        try:
            await client.connect()
            _skip_if_connect_failed(client)

            key = svc.key_builder.demo(item_id)
            await svc.set(key, {"n": 1}, ttl_seconds=2, source="integration")

            _, hit_meta = await svc.get(key)
            assert hit_meta.get("cache_hit") is True

            await asyncio.sleep(3)

            _, miss_meta = await svc.get(key)
            assert miss_meta.get("cache_hit") is False
            assert miss_meta.get("fallback") is False
        finally:
            await client.close()

    asyncio.run(_run())


@pytest.mark.integration
def test_demo_key_format_and_envelope_fields(require_live_redis):
    """对齐 §3.3：Key 格式与 Envelope JSON 字段。"""
    async def _run() -> None:
        svc, client, item_id = _build_live_service()
        try:
            await client.connect()
            _skip_if_connect_failed(client)

            key = svc.key_builder.demo(item_id)
            assert key == f"finagent:{INTEGRATION_ENV}:demo:item:{item_id}"

            await svc.set(key, {"k": "v"}, ttl_seconds=60, source="integration")
            raw = await client.get_client().get(key)
            assert raw is not None
            payload = json.loads(raw)
            for field in ("data", "schema_version", "updated_at", "source"):
                assert field in payload

            ttl = await client.get_client().ttl(key)
            assert isinstance(ttl, int) and ttl > 0
        finally:
            await client.close()

    asyncio.run(_run())
