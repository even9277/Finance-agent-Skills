"""回放 M4 Executor 的成功、瞬时恢复和永久失败案例。"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for import_root in (PROJECT_ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.conversation.contracts import (  # noqa: E402
    ConstraintSet,
    ConversationRunContext,
    Entity,
    EntityType,
    EvidenceFact,
    ReplyPreference,
    RunBudget,
    SopRewriteResult,
    TimeScope,
    ToolObservation,
)
from src.conversation.errors import ToolPermanentError, ToolTransientError  # noqa: E402
from src.conversation.execution import ControlledExecutor  # noqa: E402
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.validation import PlanValidator  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


class _EvalTool:
    def __init__(self, behavior: str) -> None:
        self.behavior = behavior
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        market_attempts = sum(item.tool_name == "get_market_bars" for item in self.calls)
        if (
            call.tool_name == "get_market_bars"
            and self.behavior == "transient_once"
            and market_attempts == 1
        ):
            raise ToolTransientError("fixture transient")
        if call.tool_name == "get_market_bars" and self.behavior == "permanent_market":
            raise ToolPermanentError("fixture permanent")
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=(EvidenceFact(key="fixture", value="ok"),),
            source="fixture:executor-m4",
            observed_at=date(2026, 8, 24),
            attempts=1,
        )


def _validated_plan(budget: RunBudget):
    entity = Entity(symbol="600519.SH", name="贵州茅台", entity_type=EntityType.STOCK)
    rewrite = SopRewriteResult(
        effective_query="贵州茅台首轮分析",
        entity=entity,
        entities=(entity,),
        requested_dimensions=(),
        skill_name="stock-first-pass",
        data_requirements=("stock_basic", "market_snapshot", "financial_indicator"),
        constraints=ConstraintSet(),
        reply_preference=ReplyPreference(),
        time_scope=TimeScope.LATEST_TRADING_DAY,
    )
    catalog = ToolGovernanceCatalog.default()
    registry = SkillRegistry()
    runtime = registry.runtime_snapshot()
    planner_context = registry.get_loader(runtime).load_for_planner(
        "stock-first-pass",
        query=rewrite.effective_query,
    )
    permissions = ControlledPermissionResolver(
        catalog=catalog,
        skill_catalog=registry.conversation_snapshot(runtime),
    ).resolve(rewrite, skill_context=planner_context)
    plan = ControlledPlanner(catalog=catalog).plan(
        rewrite,
        permissions,
        trace_id="eval-m5",
        skill_context=planner_context,
    )
    result = PlanValidator().validate(plan, permissions, budget=budget)
    assert result.validated_plan is not None
    return result.validated_plan


@pytest.mark.eval_smoke
def test_executor_eval_replays_bounded_failure_cases() -> None:
    """验证三种固定失败语义、调用预算和归一化状态。"""
    rows = load_jsonl(Path("tests/evals/executor/data/smoke.jsonl"))

    async def run_case(row: dict[str, Any]) -> None:
        budget = RunBudget(max_tool_attempts=row["max_tool_attempts"], max_concurrency=2)
        tool = _EvalTool(row["behavior"])
        result = await ControlledExecutor(tool).execute(
            _validated_plan(budget),
            ConversationRunContext(
                trace_id=row["case_id"],
                run_id=f"run-{row['case_id']}",
                session_id="session-executor-eval",
                request_id=row["case_id"],
                turn_index=1,
                budget=budget,
            ),
        )
        assert result.tool_call_count == row["gold"]["tool_call_count"]
        assert [item.status.value for item in result.observations] == row["gold"]["statuses"]

    for row in rows:
        asyncio.run(run_case(row))
