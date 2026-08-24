"""验证 M4 计划、权限、DAG 调度和工具失败治理。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    ConstraintSet,
    ConversationRunContext,
    Entity,
    EntityType,
    ErrorCode,
    EvidenceFact,
    ReplyPreference,
    RunBudget,
    SopRewriteResult,
    StepStatus,
    TimeScope,
    ToolArgument,
    ToolObservation,
    ValidationIssueCode,
)
from src.conversation.errors import ToolPermanentError, ToolTransientError  # noqa: E402
from src.conversation.execution import ControlledExecutor  # noqa: E402
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.validation import PlanValidator  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402


def _stock_rewrite() -> SopRewriteResult:
    entity = Entity(symbol="600519.SH", name="贵州茅台", entity_type=EntityType.STOCK)
    return SopRewriteResult(
        effective_query="分析贵州茅台的行情和财务质量",
        entity=entity,
        entities=(entity,),
        requested_dimensions=(),
        skill_name="stock-first-pass",
        data_requirements=("stock_basic", "market_snapshot", "financial_indicator"),
        constraints=ConstraintSet(),
        reply_preference=ReplyPreference(),
        time_scope=TimeScope.LATEST_TRADING_DAY,
    )


def _validated_stock_plan(*, budget: RunBudget | None = None):
    catalog = ToolGovernanceCatalog.default()
    permissions = ControlledPermissionResolver(
        catalog=catalog,
        skill_catalog=SkillRegistry().conversation_snapshot(),
    ).resolve(_stock_rewrite())
    plan = ControlledPlanner(catalog=catalog).plan(
        _stock_rewrite(),
        permissions,
        trace_id="trace-m4",
    )
    validation = PlanValidator().validate(
        plan,
        permissions,
        budget=budget or RunBudget(),
    )
    assert validation.validated_plan is not None
    return validation.validated_plan


@pytest.mark.unit
def test_skill_permission_snapshot_is_read_only_and_intersects_catalog() -> None:
    """确认 Skill 只能获得已登记且只读的工具权限。"""
    catalog = ToolGovernanceCatalog.default()
    snapshot = ControlledPermissionResolver(
        catalog=catalog,
        skill_catalog=SkillRegistry().conversation_snapshot(),
    ).resolve(_stock_rewrite())

    assert snapshot.allowed_tools == (
        "get_balance_sheet",
        "get_cashflow",
        "get_fina_indicator",
        "get_income",
        "get_market_bars",
        "get_stock_basic_info",
    )
    assert all(item.side_effect.value == "READ" for item in snapshot.permissions)
    assert len(snapshot.snapshot_hash) == 64


@pytest.mark.unit
def test_validator_rejects_unauthorized_invalid_duplicate_and_over_budget_plan() -> None:
    """确认越权、参数错误、重复动作和步骤超预算均在执行前被拒。"""
    validated = _validated_stock_plan()
    plan = validated.plan
    first = plan.steps[0]
    market_step = next(step for step in plan.steps if step.tool_name == "get_market_bars")
    invalid_steps = (
        replace(first, tool_name="trade_order"),
        replace(
            market_step,
            step_id="bad-limit",
            arguments=(ToolArgument(name="limit", value="many"),),
        ),
        replace(first, step_id="duplicate-action"),
    )
    invalid_plan = replace(plan, steps=invalid_steps)

    result = PlanValidator().validate(
        invalid_plan,
        validated.permissions,
        budget=RunBudget(max_plan_steps=2),
    )
    codes = {issue.code for issue in result.issues}

    assert result.validated_plan is None
    assert ValidationIssueCode.TOOL_NOT_ALLOWED in codes
    assert ValidationIssueCode.ARGUMENT_TYPE_MISMATCH in codes
    assert ValidationIssueCode.DUPLICATE_ACTION in codes
    assert ValidationIssueCode.STEP_LIMIT_EXCEEDED in codes


@pytest.mark.unit
def test_validator_rejects_cycle_and_unknown_dependency() -> None:
    """确认有环或悬空依赖的 DAG 不能形成 ValidatedToolPlan。"""
    validated = _validated_stock_plan()
    plan = validated.plan
    first, second, *rest = plan.steps
    invalid = replace(
        plan,
        steps=(
            replace(first, depends_on=(second.step_id,)),
            replace(second, depends_on=(first.step_id, "missing-step")),
            *rest,
        ),
    )

    result = PlanValidator().validate(invalid, validated.permissions, budget=RunBudget())
    codes = {issue.code for issue in result.issues}

    assert result.validated_plan is None
    assert ValidationIssueCode.CYCLIC_DEPENDENCY in codes
    assert ValidationIssueCode.UNKNOWN_DEPENDENCY in codes


class _ConcurrentTool:
    def __init__(self) -> None:
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def execute(self, call):
        self.calls.append(call)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=(EvidenceFact(key="fixture", value="ok"),),
            source="fixture:m4",
            observed_at=date(2026, 8, 24),
            attempts=1,
        )


@pytest.mark.unit
def test_executor_runs_independent_steps_with_bounded_concurrency() -> None:
    """确认独立 DAG 节点并发执行，但不会突破请求级并发预算。"""

    async def run_case() -> None:
        tool = _ConcurrentTool()
        budget = RunBudget(max_concurrency=2)
        plan = _validated_stock_plan(budget=budget)
        result = await ControlledExecutor(tool).execute(
            plan,
            ConversationRunContext(
                trace_id="trace-concurrency",
                run_id="run-concurrency",
                session_id="session-concurrency",
                request_id="request-concurrency",
                turn_index=1,
                budget=budget,
            ),
        )

        assert result.tool_call_count == 3
        assert result.batch_count == 1
        assert tool.max_active == 2
        assert all(item.status is StepStatus.SUCCEEDED for item in result.observations)

    asyncio.run(run_case())


class _FailureTool:
    def __init__(self, *, transient: bool) -> None:
        self.transient = transient
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        if self.transient and len(self.calls) == 1:
            raise ToolTransientError("fixture transient")
        if not self.transient:
            raise ToolPermanentError("fixture permanent")
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=(EvidenceFact(key="fixture", value="recovered"),),
            source="fixture:m4",
            observed_at=date(2026, 8, 24),
            attempts=1,
        )


@pytest.mark.unit
def test_executor_retries_only_transient_failures() -> None:
    """确认瞬时错误有限重试，永久错误立即停止且不泄露异常原文。"""

    async def run_case() -> None:
        budget = RunBudget(max_tool_attempts=2)
        plan = _validated_stock_plan(budget=budget)
        single = replace(
            plan,
            plan=replace(plan.plan, steps=(plan.plan.steps[0],)),
            execution_layers=((plan.plan.steps[0].step_id,),),
        )
        context = ConversationRunContext(
            trace_id="trace-retry",
            run_id="run-retry",
            session_id="session-retry",
            request_id="request-retry",
            turn_index=1,
            budget=budget,
        )

        transient_tool = _FailureTool(transient=True)
        recovered = await ControlledExecutor(transient_tool).execute(single, context)
        assert recovered.tool_call_count == 2
        assert recovered.observations[0].attempts == 2
        assert recovered.observations[0].status is StepStatus.SUCCEEDED

        permanent_tool = _FailureTool(transient=False)
        failed = await ControlledExecutor(permanent_tool).execute(single, context)
        assert failed.tool_call_count == 1
        assert failed.observations[0].error_code is ErrorCode.TOOL_EXECUTION_FAILED
        assert "fixture permanent" not in (failed.observations[0].error_message or "")

    asyncio.run(run_case())
