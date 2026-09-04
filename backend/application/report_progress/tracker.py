"""把真实 LangGraph 节点事件投影为单调报告阶段事实。"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from backend.application.report_progress.contracts import (
    ReportProgressNotification,
    ReportStage,
    ReportStageSnapshot,
    ReportStageStatus,
)

_ANALYST_STAGE_BY_NODE: dict[str, ReportStage] = {
    "fundamental_analyst": ReportStage.FUNDAMENTAL_ANALYSIS,
    "technical_analyst": ReportStage.TECHNICAL_ANALYSIS,
    "value_analyst": ReportStage.VALUATION_ANALYSIS,
    "news_analyst": ReportStage.NEWS_ANALYSIS,
}
_NODE_STAGE: dict[str, ReportStage] = {
    **_ANALYST_STAGE_BY_NODE,
    "memory_read_node": ReportStage.PERSONALIZATION,
    "prepare_summary_context": ReportStage.PERSONALIZATION,
    "summarizer": ReportStage.SYNTHESIZING,
}
_STAGE_ORDER = tuple(ReportStage)


class ReportProgressTracker:
    """维护一条报告任务的节点去重、阶段状态与单调进度。

    Args:
        task_id: 报告任务标识。
        report_id: 报告标识。

    Notes:
        跟踪器只解释白名单节点。LangGraph 的 ``metadata.langgraph_node``
        优先于展示用 ``name``，避免包装 Runnable 名称遮蔽真实节点。
    """

    def __init__(
        self,
        *,
        task_id: str,
        report_id: str,
        personalization_completion_nodes: Collection[str] | None = None,
    ) -> None:
        """初始化任务跟踪器。

        Args:
            task_id: 报告任务标识。
            report_id: 报告标识。
            personalization_completion_nodes: 哪些真实节点结束后才可关闭
                PERSONALIZATION。默认适配仅 LTM 的 ``memory_read_node``；
                启用 STM 时由 service 指定 ``prepare_summary_context``。
        """
        self._task_id = task_id
        self._report_id = report_id
        self._personalization_completion_nodes = frozenset(
            personalization_completion_nodes or {"memory_read_node"}
        )
        self._progress = 0
        self._running_nodes: set[str] = set()
        self._completed_nodes: set[str] = set()
        self._stage_statuses: dict[ReportStage, ReportStageStatus] = {}

    @property
    def current_progress(self) -> int:
        """返回当前已确认的任务级单调进度。"""
        return self._progress

    def snapshots(self) -> tuple[ReportStageSnapshot, ...]:
        """按稳定阶段顺序返回当前进程观察到的状态。"""
        return tuple(
            ReportStageSnapshot(stage=stage, stage_status=self._stage_statuses[stage])
            for stage in _STAGE_ORDER
            if stage in self._stage_statuses
        )

    def begin_preparing(self) -> ReportProgressNotification:
        """标记报告任务已进入准备阶段。"""
        return self._notification(
            ReportStage.PREPARING,
            ReportStageStatus.RUNNING,
            progress=10,
        )

    def complete_preparing(self) -> ReportProgressNotification:
        """标记股票实体与初始状态已经准备完成。"""
        return self._notification(
            ReportStage.PREPARING,
            ReportStageStatus.SUCCEEDED,
            progress=20,
        )

    def skip_optional_personalization(self) -> ReportProgressNotification:
        """在 STM/LTM 均关闭时显式标记个性化阶段跳过。"""
        return self._notification(
            ReportStage.PERSONALIZATION,
            ReportStageStatus.SKIPPED,
            progress=max(self._progress, 80),
        )

    def observe_langgraph_event(
        self,
        event: Mapping[str, Any],
    ) -> ReportProgressNotification | None:
        """将一条 LangGraph start/end 事件映射为安全阶段事实。

        Args:
            event: LangGraph ``astream_events`` 返回的单条事件。

        Returns:
            首次有效状态变化对应的通知；未知、重复或非生命周期事件返回
            ``None``。
        """
        event_kind = str(event.get("event") or "")
        if event_kind not in {"on_chain_start", "on_chain_end", "on_chain_complete"}:
            return None

        metadata = event.get("metadata")
        safe_metadata = metadata if isinstance(metadata, Mapping) else {}
        metadata_node = str(
            safe_metadata.get("langgraph_node") or safe_metadata.get("node") or ""
        )
        event_name = str(event.get("name") or "")
        # LangGraph 会把 node metadata 传播给内部 Runnable；只有顶层事件的
        # name 与 node 一致。旧版本没有 metadata 时才回退到白名单 name。
        if metadata_node and event_name and event_name != metadata_node:
            return None
        node = metadata_node or event_name
        stage = _NODE_STAGE.get(node)
        if stage is None:
            return None
        stage_is_terminal = self._stage_statuses.get(stage) in {
            ReportStageStatus.SUCCEEDED,
            ReportStageStatus.FAILED,
            ReportStageStatus.SKIPPED,
        }

        if event_kind == "on_chain_start":
            if node in self._running_nodes or node in self._completed_nodes or stage_is_terminal:
                return None
            self._running_nodes.add(node)
            if self._stage_statuses.get(stage) is ReportStageStatus.RUNNING:
                return None
            progress = self._start_progress(stage)
            return self._notification(stage, ReportStageStatus.RUNNING, progress=progress)

        if node in self._completed_nodes or stage_is_terminal:
            self._completed_nodes.add(node)
            self._running_nodes.discard(node)
            return None
        self._completed_nodes.add(node)
        self._running_nodes.discard(node)
        if (
            stage is ReportStage.PERSONALIZATION
            and node not in self._personalization_completion_nodes
        ):
            return None
        progress = self._completion_progress(node, stage)
        return self._notification(stage, ReportStageStatus.SUCCEEDED, progress=progress)

    def fail_active_stages(self) -> tuple[ReportProgressNotification, ...]:
        """把异常发生时仍运行的公开阶段收敛为 FAILED。"""
        active_stages = tuple(
            stage
            for stage in _STAGE_ORDER
            if self._stage_statuses.get(stage) is ReportStageStatus.RUNNING
        )
        failed = [
            self._notification(
                stage,
                ReportStageStatus.FAILED,
                progress=self._progress,
            )
            for stage in active_stages
        ]
        self._running_nodes.clear()
        return tuple(failed)

    def _start_progress(self, stage: ReportStage) -> int:
        if stage is ReportStage.PREPARING:
            return max(self._progress, 10)
        if stage in _ANALYST_STAGE_BY_NODE.values():
            return max(self._progress, 20)
        if stage is ReportStage.PERSONALIZATION:
            return max(self._progress, 80)
        return max(self._progress, 90)

    def _completion_progress(self, node: str, stage: ReportStage) -> int:
        if stage is ReportStage.PREPARING:
            return max(self._progress, 20)
        if node in _ANALYST_STAGE_BY_NODE:
            completed_analysts = len(self._completed_nodes.intersection(_ANALYST_STAGE_BY_NODE))
            return max(self._progress, 20 + 15 * completed_analysts)
        if stage is ReportStage.PERSONALIZATION:
            return max(self._progress, 85)
        return max(self._progress, 95)

    def _notification(
        self,
        stage: ReportStage,
        stage_status: ReportStageStatus,
        *,
        progress: int,
    ) -> ReportProgressNotification:
        self._progress = max(self._progress, progress)
        previous = self._stage_statuses.get(stage)
        if previous not in {
            ReportStageStatus.SUCCEEDED,
            ReportStageStatus.FAILED,
            ReportStageStatus.SKIPPED,
        }:
            self._stage_statuses[stage] = stage_status
        return ReportProgressNotification(
            task_id=self._task_id,
            report_id=self._report_id,
            stage=stage,
            stage_status=stage_status,
            progress=self._progress,
        )
