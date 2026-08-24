"""集中管理可选 Redis 记忆缓存的应用生命周期。"""

from __future__ import annotations

import logging
from typing import cast

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from backend.application.memory.cache import MemoryCacheConfig, MemoryHotCache
from backend.config import settings

from .redis_cache import AsyncRedisClient, RedisMemoryHotCache

logger = logging.getLogger(__name__)

_memory_cache: MemoryHotCache | None = None


async def initialize_memory_cache() -> MemoryHotCache | None:
    """按配置创建 Redis 连接池并执行非阻塞健康探测。

    Returns:
        开启时返回可降级缓存端口，关闭时返回 ``None``。即使 Redis 不可达，
        也保留端口供后续恢复，且不阻断应用启动。
    """
    global _memory_cache
    if not settings.enable_redis_cache:
        _memory_cache = None
        return None
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=settings.redis_connect_timeout_sec,
        socket_timeout=settings.redis_socket_timeout_sec,
        max_connections=settings.redis_max_connections,
        retry=Retry(NoBackoff(), 0),
    )
    cache = RedisMemoryHotCache(
        cast(AsyncRedisClient, client),
        MemoryCacheConfig(
            namespace=settings.redis_cache_namespace,
            ttl_sec=settings.redis_cache_ttl_sec,
            lease_sec=settings.redis_cache_lease_sec,
            singleflight_wait_ms=settings.redis_singleflight_wait_ms,
        ),
    )
    _memory_cache = cache
    health = await cache.health()
    logger.info(
        "memory_cache_initialized stage=%s status=%s error_code=%s",
        "memory.cache.bootstrap",
        health["status"],
        health["error_code"],
    )
    return cache


def get_memory_cache() -> MemoryHotCache | None:
    """返回当前进程的可选缓存端口，不在业务层自行创建连接。"""
    return _memory_cache


async def close_memory_cache() -> None:
    """关闭当前缓存连接池并清空全局引用。"""
    global _memory_cache
    cache = _memory_cache
    _memory_cache = None
    if cache is not None:
        await cache.close()


def set_memory_cache_for_testing(cache: MemoryHotCache | None) -> None:
    """仅供隔离测试替换进程缓存端口，生产装配不得调用。"""
    global _memory_cache
    _memory_cache = cache
