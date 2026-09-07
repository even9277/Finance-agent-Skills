"""验证报告复合观察订阅在取消和竞争完成时不泄漏子任务。"""

from __future__ import annotations

import asyncio

import pytest

from backend.routers.report import _ReportUpdateSubscription


class _BlockingSubscription:
    """提供可观察取消状态的测试订阅。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def receive(self) -> object:
        """阻塞到取消或测试显式释放。"""
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return object()


@pytest.mark.unit
def test_composite_subscription_cancels_children_when_outer_wait_is_cancelled() -> None:
    """D06-T06：SSE reconcile 超时取消外层等待时不得遗留接收任务。"""

    async def scenario() -> None:
        local = _BlockingSubscription()
        remote = _BlockingSubscription()
        receive_task = asyncio.create_task(
            _ReportUpdateSubscription(local, remote).receive()
        )
        try:
            await asyncio.gather(local.started.wait(), remote.started.wait())
            receive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receive_task
            await asyncio.sleep(0)
            assert local.cancelled.is_set()
            assert remote.cancelled.is_set()
        finally:
            # 即使前置断言失败也释放阻塞点，避免测试自身制造 pending-task 告警。
            local.release.set()
            remote.release.set()
            await asyncio.sleep(0)

    asyncio.run(scenario())
