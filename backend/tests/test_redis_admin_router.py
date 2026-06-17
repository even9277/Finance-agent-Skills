"""redis_admin 路由：开关、503、demo 流程（不依赖 FastAPI TestClient）。"""

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
try:
    from pydantic import field_validator  # noqa: F401
except ImportError:
    pytest.skip("需要 pydantic v2（与 backend.config 一致）", allow_module_level=True)

from fastapi import HTTPException

import backend.integrations.redis.runtime as redis_runtime
from backend.integrations.redis.metrics import get_metrics_collector, reset_metrics_collector
from backend.routers.redis_admin import DemoSetRequest, build_redis_admin_router
from backend.tests.test_redis_cache_service import _build_service


def _reset_runtime() -> None:
    redis_runtime._redis_enabled_override = None
    redis_runtime._redis_client = None
    redis_runtime._cache_service = None


def _route_paths(router) -> list[str]:
    return [getattr(route, "path", "") for route in router.routes]


def _find_endpoint(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") != path:
            continue
        methods = getattr(route, "methods", set()) or set()
        if method.upper() in methods:
            return route.endpoint
    return None


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _patch_settings(
    *,
    redis_enabled: bool = True,
    debug_endpoints: bool = True,
    metrics_endpoint: bool = True,
):
    """同时 patch config 与 redis_admin 模块内的 settings 引用。"""
    with (
        patch("backend.config.settings.redis_enabled", redis_enabled),
        patch(
            "backend.config.settings.redis_debug_endpoints_enabled",
            debug_endpoints,
        ),
        patch(
            "backend.config.settings.redis_metrics_endpoint_enabled",
            metrics_endpoint,
        ),
        patch("backend.routers.redis_admin.settings.redis_enabled", redis_enabled),
        patch(
            "backend.routers.redis_admin.settings.redis_debug_endpoints_enabled",
            debug_endpoints,
        ),
        patch(
            "backend.routers.redis_admin.settings.redis_metrics_endpoint_enabled",
            metrics_endpoint,
        ),
    ):
        yield


def _setup_cache_runtime() -> None:
    """与 /api/redis/metrics 共用同一 MetricsCollector 单例。"""
    from backend.integrations.redis.cache_service import CacheService
    from backend.integrations.redis.client import RedisClient
    from backend.integrations.redis.key_builder import KeyBuilder
    from backend.tests.test_redis_cache_service import FakeRedis

    metrics = get_metrics_collector()
    client = RedisClient("redis://localhost:6379/0")
    fake = FakeRedis()
    client._client = fake
    client._available = True
    svc = CacheService(
        client,
        KeyBuilder("test"),
        metrics,
        redis_enabled=True,
        unavailable_recheck_sec=3600,
    )
    redis_runtime._cache_service = svc
    redis_runtime._redis_client = client


def test_redis_health_should_return_503_when_redis_disabled():
    reset_metrics_collector()
    try:
        with _patch_settings(redis_enabled=False):
            router = build_redis_admin_router()
            health = _find_endpoint(router, "/health", "GET")
            assert health is not None
            with pytest.raises(HTTPException) as exc:
                _run(health())
            assert exc.value.status_code == 503
            assert exc.value.detail["error"] == "redis_disabled"
    finally:
        _reset_runtime()
        reset_metrics_collector()


def test_redis_metrics_route_should_not_mount_when_endpoint_disabled():
    reset_metrics_collector()
    try:
        with _patch_settings(metrics_endpoint=False):
            router = build_redis_admin_router()
            assert "/metrics" not in _route_paths(router)
    finally:
        reset_metrics_collector()


def test_demo_routes_should_not_mount_when_debug_endpoints_disabled():
    reset_metrics_collector()
    try:
        with _patch_settings(debug_endpoints=False):
            router = build_redis_admin_router()
            paths = _route_paths(router)
            assert "/demo/set" not in paths
            assert "/demo/get" not in paths
            assert "/demo/delete" not in paths
    finally:
        reset_metrics_collector()


def test_demo_set_get_delete_flow_should_work_when_debug_enabled():
    reset_metrics_collector()
    try:
        _setup_cache_runtime()
        with _patch_settings(debug_endpoints=True):
            router = build_redis_admin_router()
            demo_set = _find_endpoint(router, "/demo/set", "POST")
            demo_get = _find_endpoint(router, "/demo/get", "GET")
            demo_delete = _find_endpoint(router, "/demo/delete", "DELETE")
            assert demo_set and demo_get and demo_delete

            set_body = _run(
                demo_set(
                    DemoSetRequest(
                        id="hello",
                        data={"msg": "world"},
                        ttl_seconds=60,
                    )
                )
            )
            assert set_body["success"] is True
            assert set_body["key"] == "finagent:test:demo:item:hello"

            get_body = _run(demo_get(key="hello"))
            assert get_body["cache_hit"] is True
            assert get_body["data"] == {"msg": "world"}
            assert get_body["envelope"]["source"] == "demo"

            del_body = _run(demo_delete(key="hello"))
            assert del_body["ok"] is True

            miss_body = _run(demo_get(key="hello"))
            assert miss_body["cache_hit"] is False
            assert miss_body["data"] is None
    finally:
        _reset_runtime()
        reset_metrics_collector()


def test_redis_metrics_should_expose_counters_after_demo_calls():
    reset_metrics_collector()
    try:
        _setup_cache_runtime()
        with _patch_settings(debug_endpoints=True):
            router = build_redis_admin_router()
            demo_set = _find_endpoint(router, "/demo/set", "POST")
            demo_get = _find_endpoint(router, "/demo/get", "GET")
            metrics = _find_endpoint(router, "/metrics", "GET")
            assert demo_set and demo_get and metrics

            _run(
                demo_set(
                    DemoSetRequest(id="m1", data={"n": 1}, ttl_seconds=30)
                )
            )
            _run(demo_get(key="m1"))
            _run(demo_get(key="missing"))

            body = _run(metrics())
            assert body["redis_enabled"] is True
            assert body["redis_available"] is True
            assert body["counters"]["cache_set"] >= 1
            assert body["counters"]["cache_hit"] >= 1
            assert body["counters"]["cache_miss"] >= 1
    finally:
        _reset_runtime()
        reset_metrics_collector()
