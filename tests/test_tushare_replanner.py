import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.executor.budget import ExecutionBudget  # noqa: E402
from src.agents.executor.execution_scheduler import action_fingerprint  # noqa: E402
from src.agents.replanner.tushare_replanner import ReplanContext, TushareReplanner  # noqa: E402
from src.agents.tool_discovery.discovery_resolver import ToolDiscoveryResolver  # noqa: E402


class TushareReplannerTests(unittest.TestCase):
    def test_adds_missing_dimension_steps(self):
        context = ReplanContext(
            plan_id="plan_a",
            trace_id="trace_a",
            attempt=0,
            missing_dimensions=["financial_indicator"],
            action_fingerprints=[],
            budget_remaining_ms=10000,
            user_intent_summary="贵州茅台财务指标",
        )
        discovery = ToolDiscoveryResolver().resolve(
            {"data_requirements": ["financial_indicator"]},
            active_entity={"asset_type": "stock", "symbol": "600519.SH"},
        )
        result = TushareReplanner().replan(
            context=context,
            discovery_result=discovery,
            active_entity={"asset_type": "stock", "symbol": "600519.SH"},
        )
        self.assertFalse(result.skipped)
        self.assertEqual(result.added_plan.plan_id, "plan_a_replan_1")
        self.assertEqual(result.added_plan.steps[0].tool_name, "get_fina_indicator")
        self.assertEqual(result.added_plan.steps[0].step_id, "r1_s1")

    def test_skips_after_max_replans(self):
        context = ReplanContext(
            plan_id="plan_a",
            trace_id="trace_a",
            attempt=1,
            missing_dimensions=["financial_indicator"],
            budget_remaining_ms=10000,
        )
        result = TushareReplanner(budget=ExecutionBudget(max_replans=1)).replan(
            context=context,
            discovery_result={"available_tools": ["get_fina_indicator"]},
            active_entity={"asset_type": "stock"},
        )
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "max_replans_exhausted")

    def test_skips_duplicate_fingerprint(self):
        fp = action_fingerprint("get_fina_indicator", {"query": "贵州茅台财务指标", "limit": 4})
        context = ReplanContext(
            plan_id="plan_a",
            trace_id="trace_a",
            attempt=0,
            missing_dimensions=["financial_indicator"],
            action_fingerprints=[fp],
            budget_remaining_ms=10000,
            user_intent_summary="贵州茅台财务指标",
        )
        discovery = ToolDiscoveryResolver().resolve(
            {"data_requirements": ["financial_indicator"]},
            active_entity={"asset_type": "stock"},
        )
        result = TushareReplanner().replan(
            context=context,
            discovery_result=discovery,
            active_entity={"asset_type": "stock"},
        )
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "duplicate_action_fingerprint")


if __name__ == "__main__":
    unittest.main()
