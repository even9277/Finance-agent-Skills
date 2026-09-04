"""锁定 D05 报告工作流真实阶段与单调进度规则。"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_ANALYST_NODES = (
    "fundamental_analyst",
    "technical_analyst",
    "value_analyst",
    "news_analyst",
)


def _tracker(*, personalization_completion_nodes: set[str] | None = None) -> Any:
    """加载目标跟踪器并构造一条隔离任务。"""
    target = PROJECT_ROOT / "backend/application/report_progress/tracker.py"
    assert target.is_file(), f"目标模块尚未实现：{target.relative_to(PROJECT_ROOT)}"
    module = importlib.import_module("backend.application.report_progress.tracker")
    return module.ReportProgressTracker(
        task_id="task-d05",
        report_id="report-d05",
        personalization_completion_nodes=personalization_completion_nodes,
    )


def _event(kind: str, node: str, *, display_name: str | None = None) -> dict[str, object]:
    """构造顶层或显式嵌套的 LangGraph 事件。"""
    return {
        "event": kind,
        "name": display_name or node,
        "metadata": {"langgraph_node": node},
        "data": {},
    }


@pytest.mark.unit
@pytest.mark.parametrize("completion_order", [_ANALYST_NODES, tuple(reversed(_ANALYST_NODES))])
def test_parallel_analyst_completion_uses_count_and_never_regresses(
    completion_order: tuple[str, ...],
) -> None:
    """D05-T02：任意并行完成顺序都必须产生 35/50/65/80。"""
    tracker = _tracker()
    completed_progress: list[int] = []

    for node in completion_order:
        started = tracker.observe_langgraph_event(_event("on_chain_start", node))
        assert started is not None
        assert started.stage_status.value == "RUNNING"
        assert started.progress >= 20

        completed = tracker.observe_langgraph_event(_event("on_chain_end", node))
        assert completed is not None
        assert completed.stage_status.value == "SUCCEEDED"
        completed_progress.append(completed.progress)

    assert completed_progress == [35, 50, 65, 80]
    assert completed_progress == sorted(completed_progress)


@pytest.mark.unit
def test_stage_mapping_rejects_nested_root_unknown_or_duplicate_events() -> None:
    """D05-T02：只接受顶层白名单节点，内部子链和重复事件不推进。"""
    tracker = _tracker()

    nested = tracker.observe_langgraph_event(
        _event("on_chain_start", "fundamental_analyst", display_name="wrong_name")
    )
    assert nested is None
    mapped = tracker.observe_langgraph_event(
        _event("on_chain_start", "fundamental_analyst")
    )
    assert mapped is not None
    assert mapped.stage.value == "FUNDAMENTAL_ANALYSIS"

    first_end = tracker.observe_langgraph_event(_event("on_chain_end", "fundamental_analyst"))
    duplicate_end = tracker.observe_langgraph_event(
        _event("on_chain_end", "fundamental_analyst")
    )
    assert first_end is not None and first_end.progress == 35
    assert duplicate_end is None
    assert tracker.observe_langgraph_event(_event("on_chain_end", "unknown_node")) is None
    assert tracker.observe_langgraph_event(
        {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {}}
    ) is None


@pytest.mark.unit
def test_optional_personalization_is_explicitly_succeeded_or_skipped() -> None:
    """D05-T02：可选记忆阶段必须显式完成或跳过，不能由 UI 猜测。"""
    enabled = _tracker()
    started = enabled.observe_langgraph_event(_event("on_chain_start", "memory_read_node"))
    completed = enabled.observe_langgraph_event(_event("on_chain_end", "memory_read_node"))
    assert started is not None and started.stage.value == "PERSONALIZATION"
    assert completed is not None and completed.stage_status.value == "SUCCEEDED"
    assert completed.progress == 85
    assert enabled.observe_langgraph_event(
        _event("on_chain_start", "prepare_summary_context")
    ) is None
    assert enabled.observe_langgraph_event(
        _event("on_chain_end", "prepare_summary_context")
    ) is None

    combined = _tracker(personalization_completion_nodes={"prepare_summary_context"})
    assert combined.observe_langgraph_event(
        _event("on_chain_start", "memory_read_node")
    ).stage_status.value == "RUNNING"
    assert combined.observe_langgraph_event(
        _event("on_chain_end", "memory_read_node")
    ) is None
    assert combined.observe_langgraph_event(
        _event("on_chain_start", "prepare_summary_context")
    ) is None
    combined_done = combined.observe_langgraph_event(
        _event("on_chain_end", "prepare_summary_context")
    )
    assert combined_done is not None
    assert combined_done.stage_status.value == "SUCCEEDED"

    disabled = _tracker()
    skipped = disabled.skip_optional_personalization()
    assert skipped.stage.value == "PERSONALIZATION"
    assert skipped.stage_status.value == "SKIPPED"
    assert skipped.progress == 80


@pytest.mark.unit
def test_preparing_failure_closes_the_manual_stage_without_langgraph_event() -> None:
    """D05-T02：初始状态构建失败也必须闭合已经公开的 PREPARING。"""
    tracker = _tracker()
    started = tracker.begin_preparing()
    failed = tracker.fail_active_stages()

    assert started.stage.value == "PREPARING"
    assert started.stage_status.value == "RUNNING"
    assert len(failed) == 1
    assert failed[0].stage.value == "PREPARING"
    assert failed[0].stage_status.value == "FAILED"
    assert failed[0].progress == 10
