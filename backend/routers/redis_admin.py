"""
Redis 管理/排障路由：health、metrics、demo（demo 由 REDIS_DEBUG_ENDPOINTS_ENABLED 控制）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import settings
from backend.integrations.redis.cache_service import CacheService
from backend.integrations.redis.metrics import get_metrics_collector
from backend.integrations.redis.runtime import (
    get_cache_service,
    get_redis_client,
    get_redis_health_dict,
)


class DemoSetRequest(BaseModel):
    id: str = Field(..., min_length=1)
    data: Any = None
    ttl_seconds: int = Field(..., gt=0)


def _ensure_redis_enabled() -> None:
    if not settings.redis_enabled:
        raise HTTPException(status_code=503, detail={"error": "redis_disabled"})


def _get_cache_service_or_raise() -> CacheService:
    _ensure_redis_enabled()
    svc = get_cache_service()
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "redis_not_initialized"},
        )
    return svc


def _envelope_to_dict(envelope: Any) -> dict:
    if hasattr(envelope, "model_dump"):
        return envelope.model_dump()
    return envelope.dict()


def build_redis_admin_router() -> APIRouter:
    """按配置动态注册路由；demo 仅在 REDIS_DEBUG_ENDPOINTS_ENABLED=true 时挂载。"""
    router = APIRouter()

    @router.get("/health", summary="Redis 专项健康检查")
    async def redis_health():
        _ensure_redis_enabled()
        return {"redis": await get_redis_health_dict()}

    if settings.redis_metrics_endpoint_enabled:

        @router.get("/metrics", summary="Redis 缓存指标")
        async def redis_metrics():
            _ensure_redis_enabled()
            client = get_redis_client()
            available = client.is_available() if client is not None else False
            return get_metrics_collector().snapshot(
                redis_enabled=settings.redis_enabled,
                redis_available=available,
            )

    if settings.redis_debug_endpoints_enabled:

        @router.post("/demo/set", summary="Demo 写入缓存")
        async def demo_set(body: DemoSetRequest):
            svc = _get_cache_service_or_raise()
            item_id = body.id.strip()
            redis_key = svc.key_builder.demo(item_id)
            meta = await svc.set(
                redis_key,
                body.data,
                body.ttl_seconds,
                source="demo",
            )
            return {"key": redis_key, **meta}

        @router.get("/demo/get", summary="Demo 读取缓存")
        async def demo_get(key: str = Query(..., min_length=1)):
            svc = _get_cache_service_or_raise()
            redis_key = svc.key_builder.demo(key.strip())
            envelope, meta = await svc.get(redis_key)
            payload: dict[str, Any] = {"key": redis_key, **meta}
            if envelope is not None:
                payload["envelope"] = _envelope_to_dict(envelope)
                payload["data"] = envelope.data
            else:
                payload["data"] = None
            return payload

        @router.delete("/demo/delete", summary="Demo 删除缓存")
        async def demo_delete(key: str = Query(..., min_length=1)):
            svc = _get_cache_service_or_raise()
            redis_key = svc.key_builder.demo(key.strip())
            meta = await svc.delete(redis_key)
            return {
                "key": redis_key,
                "ok": bool(meta.get("deleted")),
                **meta,
            }

    return router
