"""集中装配报告任务 Redis 镜像与跨实例版本通知生命周期。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from backend.application.report_tasks.contracts import (
    ReportTaskSnapshot,
    ReportTaskSnapshotRecord,
)
from backend.config import settings

from .redis_store import (
    AsyncRedisClient,
    RedisReportTaskSnapshotStore,
    ReportTaskRedisConfig,
    ReportTaskRedisSubscription,
)

logger = logging.getLogger(__name__)


class ReportTaskRuntime:
    """为执行器和 SSE 暴露一个可关闭的 Redis 派生观察边界。"""

    def __init__(self, store: RedisReportTaskSnapshotStore) -> None:
        self._store = store

    async def store_and_publish(
        self,
        *,
        user_id: str,
        key_digest: str,
        request_fingerprint: str,
        snapshot: ReportTaskSnapshot,
    ) -> None:
        """在数据库提交后镜像快照并发布版本；失败由适配器内部降级。"""
        await self._store.set_snapshot(
            user_id=user_id,
            key_digest=key_digest,
            request_fingerprint=request_fingerprint,
            snapshot=snapshot,
        )
        # 即使 SET 失败也发唤醒，其他实例仍可从 PostgreSQL 恢复权威快照。
        await self._store.publish_version(snapshot.task_id, snapshot.snapshot_version)

    async def store_record(self, record: ReportTaskSnapshotRecord) -> None:
        """镜像一条已提交数据库记录，供未命中或重启后的缓存重建。"""
        stored = await self._store.set_snapshot(
            user_id=record.user_id,
            key_digest=record.key_digest,
            request_fingerprint=record.request_fingerprint,
            snapshot=record.snapshot,
        )
        if stored:
            self._store.mark_rebuild()

    def mark_reconcile(self) -> None:
        """记录 SSE 回源 PostgreSQL 的低基数可观测事件。"""
        self._store.mark_reconcile()

    async def load_latest(
        self,
        *,
        user_id: str,
        key_digest: str,
        request_fingerprint: str,
    ) -> ReportTaskSnapshot | None:
        """读取派生镜像；未命中或损坏时调用方必须回源 PostgreSQL。"""
        return await self._store.get_snapshot(
            user_id=user_id,
            key_digest=key_digest,
            request_fingerprint=request_fingerprint,
        )

    @asynccontextmanager
    async def subscribe(self, task_id: str) -> AsyncIterator[ReportTaskRedisSubscription]:
        """在返回前完成摘要频道订阅，并在退出时清理连接。"""
        async with self._store.subscribe(task_id) as subscription:
            yield subscription

    async def health(self) -> dict[str, object]:
        """返回安全健康状态和低基数计数器。"""
        return await self._store.health()

    async def close(self) -> None:
        """关闭底层共享 Redis client。"""
        await self._store.close()


def create_report_task_runtime(
    *,
    redis_url: str,
    namespace: str,
    ttl_sec: int,
    connect_timeout_sec: float = 0.25,
    socket_timeout_sec: float = 0.50,
    max_connections: int = 20,
) -> ReportTaskRuntime:
    """从显式 typed 参数创建一个独立报告 Redis 运行时。

    Args:
        redis_url: redis-py 支持的连接 URL；只由 typed Settings 或测试注入。
        namespace: 与 Memory 分离的键空间前缀。
        ttl_sec: 最新快照镜像的过期秒数。
        connect_timeout_sec: 建连最长秒数。
        socket_timeout_sec: 单命令最长秒数。
        max_connections: 共享连接池上限。

    Returns:
        可用于镜像、订阅、健康检查和确定性关闭的运行时。
    """
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=connect_timeout_sec,
        socket_timeout=socket_timeout_sec,
        max_connections=max_connections,
        retry=Retry(NoBackoff(), 0),
    )
    store = RedisReportTaskSnapshotStore(
        cast(AsyncRedisClient, client),
        ReportTaskRedisConfig(namespace=namespace, ttl_sec=ttl_sec),
    )
    return ReportTaskRuntime(store)


_report_task_runtime: ReportTaskRuntime | None = None


async def initialize_report_task_runtime() -> ReportTaskRuntime | None:
    """按配置装配可降级报告 Redis 运行时，绝不阻断应用启动。"""
    global _report_task_runtime
    if not settings.enable_report_task_redis:
        _report_task_runtime = None
        return None
    runtime = create_report_task_runtime(
        redis_url=settings.redis_url,
        namespace=settings.report_task_redis_namespace,
        ttl_sec=settings.report_task_snapshot_ttl_sec,
        connect_timeout_sec=settings.redis_connect_timeout_sec,
        socket_timeout_sec=settings.redis_socket_timeout_sec,
        max_connections=settings.redis_max_connections,
    )
    _report_task_runtime = runtime
    health = await runtime.health()
    logger.info(
        "report_task_runtime_initialized stage=%s status=%s error_code=%s",
        "report.redis.bootstrap",
        health["status"],
        health["error_code"],
    )
    return runtime


def get_report_task_runtime() -> ReportTaskRuntime | None:
    """返回当前进程已装配的派生观察运行时。"""
    return _report_task_runtime


async def close_report_task_runtime() -> None:
    """关闭报告 Redis 连接池并清空全局引用。"""
    global _report_task_runtime
    runtime = _report_task_runtime
    _report_task_runtime = None
    if runtime is not None:
        await runtime.close()


def set_report_task_runtime_for_testing(runtime: ReportTaskRuntime | None) -> None:
    """仅供隔离测试替换当前进程运行时。"""
    global _report_task_runtime
    _report_task_runtime = runtime
