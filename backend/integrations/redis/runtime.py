"""
Redis 运行时单例：由 FastAPI lifespan 初始化，供 health / redis_admin 复用。
"""

from __future__ import annotations

import logging
from typing import Optional

from .cache_service import CacheService
from .client import RedisClient

logger = logging.getLogger(__name__)

_redis_client: Optional[RedisClient] = None
_cache_service: Optional[CacheService] = None
# 仅测试注入，避免单测环境强依赖 backend.config
_redis_enabled_override: Optional[bool] = None


def _is_redis_enabled() -> bool:
    if _redis_enabled_override is not None:
        return _redis_enabled_override
    from backend.config import settings

    return settings.redis_enabled


def get_redis_client() -> Optional[RedisClient]:
    return _redis_client


def get_cache_service() -> Optional[CacheService]:
    return _cache_service


async def init_redis_runtime() -> None:
    """按 REDIS_ENABLED 初始化 Redis 客户端与 CacheService；失败仅降级不阻断启动。"""
    global _redis_client, _cache_service
    from backend.config import settings
    from .metrics import get_metrics_collector

    if not settings.redis_enabled:
        print("[backend] Redis 已禁用，跳过初始化")
        logger.info("[backend] Redis 已禁用，跳过初始化")
        return

    _redis_client = RedisClient.from_settings()
    try:
        ok = await _redis_client.connect()
        if ok:
            print("[backend] Redis 客户端已初始化，Redis ping 成功 ✓")
            logger.info("[backend] Redis 客户端已初始化，ping 成功")
        else:
            snap = _redis_client.health_snapshot()
            print(
                f"[backend] Redis 客户端已创建但不可用（degraded）: {snap.error or 'unknown'}"
            )
            logger.warning(
                "[backend] Redis ping 失败，进入降级: %s",
                snap.error or "redis_unavailable",
            )
    except Exception as exc:
        print(f"[backend] Redis 初始化异常（降级，不影响启动）: {exc}")
        logger.warning(
            "[backend] Redis 初始化异常，进入降级",
            exc_info=True,
        )

    _cache_service = CacheService.from_settings(
        _redis_client,
        get_metrics_collector(),
    )


async def close_redis_runtime() -> None:
    global _redis_client, _cache_service
    if _redis_client is not None:
        try:
            await _redis_client.close()
            print("[backend] Redis 连接已关闭")
            logger.info("[backend] Redis 连接已关闭")
        except Exception as exc:
            logger.warning("[backend] Redis 关闭异常: %s", exc, exc_info=True)
    _redis_client = None
    _cache_service = None


async def get_redis_health_dict() -> dict:
    """供 /api/health 与 /api/redis/health 使用的 Redis 状态快照。"""
    if not _is_redis_enabled():
        return {"status": "disabled"}

    if _redis_client is None:
        return {"status": "degraded", "error": "redis_not_initialized"}

    await _redis_client.ping()
    snap = _redis_client.health_snapshot()
    status = snap.status
    # connect 失败时 client 存在但不可用，统一对外暴露 degraded
    if status == "disabled":
        status = "degraded"

    payload: dict = {"status": status}
    if snap.latency_ms is not None:
        payload["latency_ms"] = round(snap.latency_ms, 3)
    if snap.error and status == "degraded":
        payload["error"] = snap.error
    return payload
