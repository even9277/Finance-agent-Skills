"""
Redis 异步客户端封装。

职责：
- 管理连接池生命周期（connect / close）
- 提供健康状态（ping / is_available）
- 暴露底层客户端句柄给上层服务（后续 CacheService 使用）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

try:
    from redis.asyncio import ConnectionPool, Redis
except ImportError:  # pragma: no cover - 便于在最小测试环境中运行
    ConnectionPool = None  # type: ignore[assignment]
    Redis = None  # type: ignore[assignment]
logger = logging.getLogger(__name__)


@dataclass
class RedisHealthSnapshot:
    status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class RedisClient:
    def __init__(
        self,
        redis_url: str,
        *,
        max_connections: int = 20,
        socket_timeout_ms: int = 500,
        connect_timeout_ms: int = 500,
        health_check_interval_sec: int = 30,
        decode_responses: bool = True,
    ) -> None:
        self.redis_url = redis_url
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout_ms / 1000
        self.connect_timeout = connect_timeout_ms / 1000
        self.health_check_interval_sec = health_check_interval_sec
        self.decode_responses = decode_responses

        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._available: bool = False
        self._last_error: Optional[str] = None
        self._last_latency_ms: Optional[float] = None

    @classmethod
    def from_settings(cls) -> "RedisClient":
        from backend.config import settings

        return cls(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            socket_timeout_ms=settings.redis_socket_timeout_ms,
            connect_timeout_ms=settings.redis_connect_timeout_ms,
            health_check_interval_sec=settings.redis_health_check_interval_sec,
            decode_responses=True,
        )

    async def connect(self) -> bool:
        if ConnectionPool is None or Redis is None:
            self._available = False
            self._last_error = "redis_dependency_missing"
            logger.warning("Redis 依赖未安装，connect 跳过并进入降级模式")
            return False
        self._pool = ConnectionPool.from_url(
            self.redis_url,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
            socket_connect_timeout=self.connect_timeout,
            health_check_interval=self.health_check_interval_sec,
            decode_responses=self.decode_responses,
        )
        self._client = Redis(connection_pool=self._pool)
        return await self.ping()

    async def ping(self) -> bool:
        if self._client is None:
            self._available = False
            self._last_error = "redis_client_not_initialized"
            return False
        try:
            started = time.perf_counter()
            ok = await self._client.ping()
            self._last_latency_ms = (time.perf_counter() - started) * 1000
            self._available = bool(ok)
            self._last_error = None if self._available else "redis_ping_failed"
            return self._available
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
            logger.warning("Redis ping 失败，进入降级模式: %s", exc)
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        if self._pool is not None:
            await self._pool.aclose()
        self._client = None
        self._pool = None
        self._available = False

    def get_client(self) -> Optional[Redis]:
        return self._client

    def is_available(self) -> bool:
        return self._available

    def health_snapshot(self) -> RedisHealthSnapshot:
        if self._client is None:
            return RedisHealthSnapshot(status="disabled")
        if self._available:
            return RedisHealthSnapshot(status="ok", latency_ms=self._last_latency_ms)
        return RedisHealthSnapshot(
            status="degraded",
            latency_ms=self._last_latency_ms,
            error=self._last_error or "redis_unavailable",
        )

