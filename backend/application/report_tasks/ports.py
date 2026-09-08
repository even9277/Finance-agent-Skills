"""声明报告任务创建用例依赖的持久化端口。"""

from __future__ import annotations

from typing import Protocol

from backend.application.report_tasks.contracts import (
    ReportTaskClaim,
    ReportTaskCreateResult,
    ReportTaskSnapshotRecord,
    ReportTaskSnapshotUpdate,
)


class ReportTaskClaimRepository(Protocol):
    """定义数据库权威的报告任务原子创建或复用端口。"""

    async def create_or_reuse(self, claim: ReportTaskClaim) -> ReportTaskCreateResult:
        """原子创建、复用或换代一条用户作用域治理记录。

        Args:
            claim: 不含原始命令和显式键的低敏创建声明。

        Returns:
            唯一任务、报告和当前请求是否拥有派发权。

        Raises:
            ReportIdempotencyConflictError: 相同键绑定了不同请求指纹。
        """
        ...


class ReportTaskSnapshotRepository(Protocol):
    """定义报告任务最新快照的 PostgreSQL 权威端口。"""

    async def persist_snapshot(
        self,
        update: ReportTaskSnapshotUpdate,
    ) -> ReportTaskSnapshotRecord | None:
        """提交 Report 与治理快照；历史无治理行任务返回 ``None``。"""
        ...

    async def load_latest(self, task_id: str) -> ReportTaskSnapshotRecord | None:
        """按任务标识读取最新用户作用域快照。"""
        ...
