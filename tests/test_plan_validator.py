import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.planner.plan_validator import (  # noqa: E402
    PlanValidationError,
    PlanValidator,
    ToolPlanStepV2,
    ToolPlanV2,
)


def _plan(*steps: ToolPlanStepV2, entity=None) -> ToolPlanV2:
    return ToolPlanV2(
        plan_id="plan_test",
        trace_id="trace_test",
        discovery_trace_id="disc_test",
        route="tushare-data",
        objective="test objective",
        entity=entity or {"asset_type": "stock", "symbol": "600519.SH"},
        steps=list(steps),
    )


def _step(
    step_id: str,
    tool_name: str = "get_market_bars",
    *,
    args=None,
    depends_on=None,
    evidence_type: str = "stock_market",
    goal: str = "查询近期行情",
) -> ToolPlanStepV2:
    return ToolPlanStepV2(
        step_id=step_id,
        goal=goal,
        tool_name=tool_name,
        arguments=args if args is not None else {"query": "贵州茅台", "limit": 30},
        depends_on=depends_on or [],
        expected_observation="market bars",
        required=True,
        evidence_type=evidence_type,
    )


class PlanValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = PlanValidator()

    def test_valid_plan_returns_preview(self):
        plan = _plan(_step("s1"))
        result = self.validator.validate(plan, discovery_result={"available_tools": ["get_market_bars"]})
        self.assertEqual(result.plan.plan_id, "plan_test")
        self.assertEqual(len(result.plan_preview), 1)
        self.assertEqual(result.plan_preview[0].status, "planned")
        self.assertEqual(result.plan_preview[0].estimated_evidence, "stock_market")

    def test_rejects_tool_not_in_shortlist(self):
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(_plan(_step("s1")), discovery_result={"available_tools": ["get_daily_bars"]})
        self.assertEqual(ctx.exception.issues[0].code, "tool_not_in_shortlist")

    def test_rejects_unknown_tool(self):
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(_plan(_step("s1", tool_name="invented_tool")))
        self.assertEqual(ctx.exception.issues[0].code, "tool_not_in_registry")

    def test_rejects_empty_plan(self):
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(_plan())
        self.assertEqual(ctx.exception.issues[0].code, "empty_plan")

    def test_rejects_self_dependency(self):
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(_plan(_step("s1", depends_on=["s1"])))
        self.assertIn("self_dependency", {issue.code for issue in ctx.exception.issues})

    def test_rejects_dependency_cycle(self):
        plan = _plan(
            _step("s1", depends_on=["s2"]),
            _step("s2", depends_on=["s1"], args={"query": "贵州茅台", "limit": 20}),
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("dependency_cycle", {issue.code for issue in ctx.exception.issues})

    def test_rejects_argument_type_violation(self):
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(_plan(_step("s1", args={"query": "贵州茅台", "limit": "30"})))
        self.assertIn("arg_schema_violation", {issue.code for issue in ctx.exception.issues})

    def test_rejects_required_argument_missing(self):
        plan = _plan(
            _step(
                "s1",
                tool_name="search_web_news",
                args={"max_results": 3},
                evidence_type="web_news",
            ),
            entity={"asset_type": "stock"},
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan, discovery_result={"available_tools": ["search_web_news"]})
        self.assertIn("missing_required_arg", {issue.code for issue in ctx.exception.issues})

    def test_rejects_entity_type_mismatch(self):
        plan = _plan(
            _step("s1", tool_name="get_fund_nav", args={"query": "黄金ETF"}, evidence_type="fund_nav"),
            entity={"asset_type": "stock"},
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("entity_type_mismatch", {issue.code for issue in ctx.exception.issues})

    def test_rejects_evidence_type_mismatch(self):
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(_plan(_step("s1", evidence_type="stock_daily")))
        self.assertIn("evidence_type_mismatch", {issue.code for issue in ctx.exception.issues})

    def test_rejects_duplicate_action_fingerprint(self):
        plan = _plan(_step("s1"), _step("s2"))
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("duplicate_action_fingerprint", {issue.code for issue in ctx.exception.issues})

    def test_warns_for_weak_evidence_only(self):
        plan = _plan(
            _step(
                "s1",
                tool_name="search_web_news",
                args={"query": "贵州茅台 新闻"},
                evidence_type="web_news",
            )
        )
        result = self.validator.validate(plan, discovery_result={"available_tools": ["search_web_news"]})
        self.assertIn("weak_evidence_only", {warning.code for warning in result.warnings})


if __name__ == "__main__":
    unittest.main()
