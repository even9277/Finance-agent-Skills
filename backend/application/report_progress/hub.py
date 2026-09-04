"""提供当前单进程部署使用的有界报告进度通知加速器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from backend.application.report_progress.contracts import (
    ReportProgressMessage,
    ReportProgressNotification,
    ReportStage,
    ReportStageSnapshot,
    ReportTerminalNotification,
)


class ReportProgressSubscription:
    """封装单个消费者的有界队列，不向调用方暴露写权限。"""

    def __init__(self, queue: asyncio.Queue[ReportProgressMessage]) -> None:
        self._queue = queue

    async def receive(self) -> ReportProgressMessage:
        """等待下一条报告进度通知。

        Returns:
            当前订阅者尚未消费的最新通知。
        """
        return await self._queue.get()


class ReportProgressHub:
    """向同一进程内的 SSE 订阅者广播 latest-event 通知。

    Args:
        queue_capacity: 每个订阅者最多保留的通知数。达到上限时丢弃最旧
            通知，保证后台报告任务不被慢浏览器反压。

    Notes:
        Hub 不是恢复权威，不提供跨进程或跨重启保证。数据库 Report 快照
        负责恢复和终态收敛；D06 可在同一 publisher port 下替换为 Redis。
    """

    def __init__(self, *, queue_capacity: int = 1) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity 必须大于 0")
        self._queue_capacity = queue_capacity
        self._subscribers: dict[str, set[asyncio.Queue[ReportProgressMessage]]] = {}
        self._stage_states: dict[str, dict[ReportStage, ReportStageSnapshot]] = {}
        self._dropped_count = 0

    @asynccontextmanager
    async def subscribe(self, task_id: str) -> AsyncIterator[ReportProgressSubscription]:
        """注册一个任务级订阅，并在退出时幂等释放。

        Args:
            task_id: 需要观察的报告任务标识。

        Yields:
            只读订阅对象。
        """
        queue: asyncio.Queue[ReportProgressMessage] = asyncio.Queue(
            maxsize=self._queue_capacity
        )
        subscribers = self._subscribers.setdefault(task_id, set())
        subscribers.add(queue)
        try:
            yield ReportProgressSubscription(queue)
        finally:
            current = self._subscribers.get(task_id)
            if current is not None:
                current.discard(queue)
                if not current:
                    self._subscribers.pop(task_id, None)

    def publish(self, message: ReportProgressMessage) -> None:
        """非阻塞广播一条通知，满队列时保留最新事实。

        Args:
            message: 阶段或数据库已提交的终态通知。
        """
        if isinstance(message, ReportProgressNotification):
            self._stage_states.setdefault(message.task_id, {})[message.stage] = (
                ReportStageSnapshot(
                    stage=message.stage,
                    stage_status=message.stage_status,
                )
            )

        for queue in tuple(self._subscribers.get(message.task_id, ())):
            if queue.full():
                try:
                    queue.get_nowait()
                    self._dropped_count += 1
                except asyncio.QueueEmpty:  # pragma: no cover - 同步事件循环内的防御分支
                    pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # pragma: no cover - 单线程事件循环内的防御分支
                self._dropped_count += 1

        if isinstance(message, ReportTerminalNotification):
            self._stage_states.pop(message.task_id, None)

    def subscriber_count(self, task_id: str) -> int:
        """返回任务当前进程内的活动订阅数。"""
        return len(self._subscribers.get(task_id, ()))

    def stage_snapshots(self, task_id: str) -> tuple[ReportStageSnapshot, ...]:
        """返回任务当前进程已观察到的阶段状态。"""
        states = self._stage_states.get(task_id, {})
        return tuple(states[stage] for stage in ReportStage if stage in states)

    @property
    def dropped_count(self) -> int:
        """返回因慢消费者而替换的通知累计数。"""
        return self._dropped_count


# 一次报告当前最多约 15 条阶段/终态事件；32 保留完整正常生命周期，
# 同时仍对异常慢消费者施加固定内存上限。
report_progress_hub = ReportProgressHub(queue_capacity=32)
