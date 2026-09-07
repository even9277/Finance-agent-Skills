"""验证 Redis 版本唤醒经 PostgreSQL 对账进入跨实例 SSE。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from backend.application.report_progress.contracts import (
    ReportStage,
    ReportStageSnapshot,
    ReportStageStatus,
    ReportTaskStatus,
)
from backend.application.report_progress.snapshot import ReportProgressSnapshot
from backend.infrastructure.report_tasks.redis_store import ReportTaskVersionNotification
from backend.routers import report as report_router


class _RemoteSubscription:
    """按序返回另一个实例发布的两个持久版本通知。"""

    def __init__(self) -> None:
        self._messages = iter(
            (
                ReportTaskVersionNotification("task-d06-sse", 7),
                ReportTaskVersionNotification("task-d06-sse", 8),
            )
        )

    async def receive(self) -> ReportTaskVersionNotification:
        """让出一次事件循环后返回下一版本。"""
        await asyncio.sleep(0)
        return next(self._messages)


class _RemoteRuntime:
    """记录 SSE 是否完整释放跨实例订阅。"""

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def subscribe(self, task_id: str) -> AsyncIterator[_RemoteSubscription]:
        """提供测试订阅并统计确定性清理。"""
        assert task_id == "task-d06-sse"
        self.opened += 1
        try:
            yield _RemoteSubscription()
        finally:
            self.closed += 1


@pytest.mark.contract
def test_sse_reconciles_cross_instance_versions_and_closes_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D06-T06：B 收到 A 的摘要通知后只从权威快照发送 7、8 版本。"""
    initial = ReportProgressSnapshot(
        task_id="task-d06-sse",
        report_id="report-d06-sse",
        user_id="user-d06-sse",
        status=ReportTaskStatus.RUNNING,
        progress=20,
        error_code=None,
        message=None,
        snapshot_version=6,
        stages=(
            ReportStageSnapshot(
                stage=ReportStage.PREPARING,
                stage_status=ReportStageStatus.SUCCEEDED,
            ),
        ),
    )
    stage_v7 = ReportProgressSnapshot(
        task_id=initial.task_id,
        report_id=initial.report_id,
        user_id=initial.user_id,
        status=ReportTaskStatus.RUNNING,
        progress=35,
        error_code=None,
        message=None,
        snapshot_version=7,
        stages=(
            *initial.stages,
            ReportStageSnapshot(
                stage=ReportStage.FUNDAMENTAL_ANALYSIS,
                stage_status=ReportStageStatus.SUCCEEDED,
            ),
        ),
    )
    terminal_v8 = ReportProgressSnapshot(
        task_id=initial.task_id,
        report_id=initial.report_id,
        user_id=initial.user_id,
        status=ReportTaskStatus.COMPLETED,
        progress=100,
        error_code=None,
        message=None,
        snapshot_version=8,
        stages=stage_v7.stages,
    )
    snapshots = iter((initial, stage_v7, terminal_v8))
    runtime = _RemoteRuntime()

    async def reload(_task_id: str) -> ReportProgressSnapshot:
        return next(snapshots)

    monkeypatch.setattr(report_router, "get_report_task_runtime", lambda: runtime)
    monkeypatch.setattr(report_router, "_reload_sse_snapshot", reload)

    async def consume() -> list[object]:
        return [event.data async for event in report_router._report_event_stream(initial)]

    frames = asyncio.run(consume())
    assert [getattr(frame, "type") for frame in frames] == [
        "stream_ready",
        "stage_update",
        "task_terminal",
    ]
    assert [getattr(frame, "sequence") for frame in frames] == [6, 7, 8]
    assert [getattr(frame, "progress") for frame in frames] == [20, 35, 100]
    assert runtime.opened == runtime.closed == 1
