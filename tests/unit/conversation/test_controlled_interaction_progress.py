"""锁定 D04 领域进度合同与真实工具执行边界。"""

from __future__ import annotations

import asyncio
import importlib
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    ConversationRunContext,
    Entity,
    EntityType,
    ErrorCode,
    EvidenceDimension,
    EvidenceFact,
    EvidenceRequirement,
    RunBudget,
    StepStatus,
    ToolArgument,
    ToolObservation,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
    ToolPolicy,
    ValidatedToolPlan,
)
from src.conversation.execution import ControlledExecutor  # noqa: E402


def _progress_api() -> Any:
    """延迟加载待实现合同，使缺失能力表现为单个测试失败。"""
    return importlib.import_module("src.conversation.progress")


def _validated_plan(*, steps: tuple[ToolPlanStep, ...] | None = None) -> ValidatedToolPlan:
    """构造不经过模型或外部服务的最小已校验只读计划。"""
    effective_steps = steps or (
        ToolPlanStep(
            step_id="market-step",
            tool_name="get_market_bars",
            symbol="600519.SH",
            evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
            required=True,
            arguments=(ToolArgument(name="limit", value=5),),
            idempotency_key="private-idempotency-key",
            template_step="market_snapshot",
        ),
    )
    permissions = ToolPermissionSnapshot.create(
        permissions=(
            ToolPolicy(
                tool_name="get_market_bars",
                evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
                supported_entity_types=(EntityType.STOCK,),
                input_fields=(),
                api_family="fixture",
                retryable=False,
            ),
        ),
        source="d04-fixture",
        version="v1",
    )
    plan = ToolPlan(
        plan_id="plan-d04",
        entity=Entity(
            symbol="600519.SH",
            name="贵州茅台",
            entity_type=EntityType.STOCK,
        ),
        entities=(
            Entity(
                symbol="600519.SH",
                name="贵州茅台",
                entity_type=EntityType.STOCK,
            ),
        ),
        steps=effective_steps,
        requirements=(
            EvidenceRequirement(
                dimension=EvidenceDimension.MARKET_SNAPSHOT,
                required=True,
                entity_symbol="600519.SH",
            ),
        ),
        objective="分析行情与证据限制",
    )
    return ValidatedToolPlan(
        plan=plan,
        permissions=permissions,
        execution_layers=tuple((step.step_id,) for step in effective_steps),
    )


def _context() -> ConversationRunContext:
    """返回带稳定关联 ID 的单轮执行上下文。"""
    return ConversationRunContext(
        trace_id="trace-d04",
        run_id="run-d04",
        session_id="session-d04",
        request_id="request-d04",
        turn_index=1,
        budget=RunBudget(max_tool_attempts=1),
    )


class _RecordingObserver:
    """记录领域事件并模拟无延迟的异步消费端。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_progress(self, event: Any) -> None:
        """按产生顺序保存事件。"""
        self.events.append(event)


class _SuccessfulTool:
    """返回一条可校验证据的确定性只读工具。"""

    async def execute(self, call: Any) -> ToolObservation:
        """返回与授权调用完全匹配的观察。"""
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=(EvidenceFact(key="close", value="1688.00", unit="CNY"),),
            source="fixture:d04",
            observed_at=date(2026, 9, 3),
            attempts=1,
        )


class _FailingTool:
    """抛出包含敏感标记的未知 Provider 异常。"""

    async def execute(self, call: Any) -> ToolObservation:
        """模拟不可向客户端透传的工具失败。"""
        del call
        raise RuntimeError("SECRET_PROVIDER_DETAIL")


@pytest.mark.unit
def test_progress_contract_has_finite_step_and_tool_lifecycles() -> None:
    """D04-C01/C06：过程状态必须使用冻结的有限枚举。"""
    progress = _progress_api()

    assert tuple(item.value for item in progress.ProgressStepStatus) == (
        "PLANNED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
        "REPLANNED",
        "CANCELLED",
    )
    assert tuple(item.value for item in progress.ProgressToolStatus) == (
        "STARTED",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
        "CANCELLED",
    )


@pytest.mark.unit
def test_executor_emits_real_step_and_tool_boundaries_in_order() -> None:
    """D04-C01/C02：成功状态只能从真实 Executor 调用边界产生。"""

    async def run_case() -> None:
        progress = _progress_api()
        observer = _RecordingObserver()
        result = await ControlledExecutor(_SuccessfulTool()).execute(
            _validated_plan(),
            _context(),
            progress_observer=observer,
            plan_revision=1,
        )

        assert result.observations[0].status is StepStatus.SUCCEEDED
        assert [type(event) for event in observer.events] == [
            progress.StepStatusProgress,
            progress.ToolStatusProgress,
            progress.ToolStatusProgress,
            progress.StepStatusProgress,
        ]
        assert [event.status.value for event in observer.events] == [
            "RUNNING",
            "STARTED",
            "SUCCEEDED",
            "SUCCEEDED",
        ]
        tool_events = [
            event
            for event in observer.events
            if isinstance(event, progress.ToolStatusProgress)
        ]
        assert tool_events[0].tool_call_id == tool_events[1].tool_call_id
        assert tool_events[0].attempt == tool_events[1].attempt == 1
        assert tool_events[0].elapsed_ms is None
        assert tool_events[1].elapsed_ms is not None
        assert tool_events[1].elapsed_ms >= 0

    asyncio.run(run_case())


@pytest.mark.unit
def test_executor_failure_progress_is_closed_and_redacted() -> None:
    """D04-C03：工具失败必须闭合生命周期且不泄露 Provider 异常。"""

    async def run_case() -> None:
        _progress_api()
        observer = _RecordingObserver()
        result = await ControlledExecutor(_FailingTool()).execute(
            _validated_plan(),
            _context(),
            progress_observer=observer,
            plan_revision=1,
        )

        assert result.observations[0].error_code is ErrorCode.TOOL_EXECUTION_FAILED
        assert [event.status.value for event in observer.events] == [
            "RUNNING",
            "STARTED",
            "FAILED",
            "FAILED",
        ]
        assert "SECRET_PROVIDER_DETAIL" not in repr(observer.events)

    asyncio.run(run_case())


@pytest.mark.unit
def test_executor_dependency_skip_has_no_fake_tool_start() -> None:
    """D04-C03：依赖失败后的步骤必须跳过，不能伪造一次工具调用。"""

    async def run_case() -> None:
        progress = _progress_api()
        first = _validated_plan().plan.steps[0]
        dependent = replace(
            first,
            step_id="dependent-step",
            depends_on=(first.step_id,),
            idempotency_key="dependent-private-key",
        )
        plan = _validated_plan(steps=(first, dependent))
        observer = _RecordingObserver()
        await ControlledExecutor(_FailingTool()).execute(
            plan,
            _context(),
            progress_observer=observer,
            plan_revision=1,
        )

        dependent_events = [
            event
            for event in observer.events
            if getattr(event, "step_id", None) == dependent.step_id
        ]
        assert [type(event) for event in dependent_events] == [
            progress.ToolStatusProgress,
            progress.StepStatusProgress,
        ]
        assert [event.status.value for event in dependent_events] == [
            "SKIPPED",
            "SKIPPED",
        ]
        assert all(event.attempt == 0 for event in dependent_events[:1])

    asyncio.run(run_case())
