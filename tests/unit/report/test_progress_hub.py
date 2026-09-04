"""锁定 D05 进程内报告进度加速器的资源和慢消费者语义。"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

def _modules() -> tuple[Any, Any]:
    """在测试体加载 contracts 与 hub，避免缺失模块中断 collection。"""
    contracts_path = PROJECT_ROOT / "backend/application/report_progress/contracts.py"
    hub_path = PROJECT_ROOT / "backend/application/report_progress/hub.py"
    assert contracts_path.is_file(), "目标 contracts 尚未实现"
    assert hub_path.is_file(), "目标 hub 尚未实现"
    return (
        importlib.import_module("backend.application.report_progress.contracts"),
        importlib.import_module("backend.application.report_progress.hub"),
    )


def _notification(contracts: Any, progress: int) -> Any:
    """构造不含报告正文或 Provider 私有字段的进度事实。"""
    return contracts.ReportProgressNotification(
        task_id="task-d05",
        report_id="report-d05",
        stage=contracts.ReportStage.FUNDAMENTAL_ANALYSIS,
        stage_status=contracts.ReportStageStatus.SUCCEEDED,
        progress=progress,
    )


@pytest.mark.unit
def test_slow_subscriber_receives_latest_notification_without_blocking_publisher() -> None:
    """D05-T03：满队列替换旧通知，publish 不等待浏览器消费。"""

    async def run_case() -> None:
        contracts, hub_module = _modules()
        hub = hub_module.ReportProgressHub(queue_capacity=1)
        async with hub.subscribe("task-d05") as subscription:
            for progress in (35, 50, 65, 80):
                hub.publish(_notification(contracts, progress))
            latest = await asyncio.wait_for(subscription.receive(), timeout=0.1)
            assert latest.progress == 80
            assert hub.subscriber_count("task-d05") == 1
        assert hub.subscriber_count("task-d05") == 0

    asyncio.run(run_case())


@pytest.mark.unit
def test_multiple_subscribers_are_isolated_and_disconnect_cleanup_is_idempotent() -> None:
    """D05-T03：每个订阅者独立收到事件，退出后不残留 task queue。"""

    async def run_case() -> None:
        contracts, hub_module = _modules()
        hub = hub_module.ReportProgressHub(queue_capacity=1)
        async with hub.subscribe("task-d05") as first:
            async with hub.subscribe("task-d05") as second:
                assert hub.subscriber_count("task-d05") == 2
                expected = _notification(contracts, 35)
                hub.publish(expected)
                received = await asyncio.gather(first.receive(), second.receive())
                assert received == [expected, expected]
        assert hub.subscriber_count("task-d05") == 0
        hub.publish(_notification(contracts, 50))
        assert hub.subscriber_count("task-d05") == 0

    asyncio.run(run_case())
