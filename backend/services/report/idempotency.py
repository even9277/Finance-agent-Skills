"""报告生成幂等控制。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from backend.integrations.redis.cache_service import CacheService
from backend.services.report.command_hasher import compute_query_hash

logger = logging.getLogger(__name__)

REPORT_IDEMPOTENCY_TTL_SECONDS = 600
PLACEHOLDER_STATE = "creating"
_PLACEHOLDER = {"state": PLACEHOLDER_STATE}


def build_report_idempotency_key(
    cache_service: Optional[CacheService],
    user_id: str,
    command: str,
) -> Optional[str]:
    if cache_service is None:
        return None
    query_hash = compute_query_hash(command)
    return cache_service.key_builder.report_idempotency_by_user_query(user_id, query_hash)


async def acquire_idempotency_slot(
    cache_service: Optional[CacheService],
    key: Optional[str],
) -> tuple[bool, dict[str, Any]]:
    if cache_service is None or key is None:
        return False, {"fallback": True, "reason": "redis_not_initialized"}
    try:
        acquired, meta = await cache_service.set_if_absent(
            key,
            _PLACEHOLDER,
            ttl_seconds=REPORT_IDEMPOTENCY_TTL_SECONDS,
            source="report_idempotency",
        )
        return acquired, meta
    except Exception as exc:
        logger.warning(
            "报告幂等占位失败，降级为允许创建任务 err=%s",
            type(exc).__name__,
            exc_info=True,
        )
        return False, {"fallback": True, "reason": type(exc).__name__}


async def read_idempotency_result(
    cache_service: Optional[CacheService],
    key: Optional[str],
    *,
    timeout_seconds: float = 3.0,
    interval_seconds: float = 0.2,
) -> Optional[dict[str, Any]]:
    if cache_service is None or key is None:
        return None

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        envelope, meta = await cache_service.get(key)
        if meta.get("fallback"):
            return None
        data = envelope.data if envelope else None
        if isinstance(data, dict) and data.get("task_id"):
            return {
                "task_id": data.get("task_id"),
                "report_id": data.get("report_id"),
                "status": data.get("status") or "pending",
            }
        await asyncio.sleep(interval_seconds)
    return None


async def finalize_idempotency_slot(
    cache_service: Optional[CacheService],
    key: Optional[str],
    *,
    task_id: str,
    report_id: str,
    status: str,
) -> None:
    if cache_service is None or key is None:
        return
    data = {
        "task_id": task_id,
        "report_id": report_id,
        "status": status,
        "state": "ready",
    }
    meta = await cache_service.set(
        key,
        data,
        ttl_seconds=REPORT_IDEMPOTENCY_TTL_SECONDS,
        source="report_idempotency",
    )
    if not meta.get("success"):
        logger.warning(
            "报告幂等占位转正式值失败 reason=%s",
            meta.get("reason") or meta.get("fallback_reason") or "unknown",
        )


async def release_idempotency_slot(
    cache_service: Optional[CacheService],
    key: Optional[str],
) -> None:
    if cache_service is None or key is None:
        return
    try:
        await cache_service.delete(key)
    except Exception:
        logger.warning("报告幂等占位释放失败", exc_info=True)
