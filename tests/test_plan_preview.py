import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.planner.plan_preview import build_plan_preview  # noqa: E402
from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2  # noqa: E402


class PlanPreviewTests(unittest.TestCase):
    def test_build_plan_preview_summarizes_safe_arguments(self):
        plan = ToolPlanV2(
            plan_id="plan_preview",
            route="tushare-data",
            objective="preview",
            steps=[
                ToolPlanStepV2(
                    step_id="s1",
                    goal="查询行情",
                    tool_name="get_market_bars",
                    arguments={"query": "贵州茅台", "limit": 30, "secret": "hidden"},
                    expected_observation="bars",
                    required=True,
                    evidence_type="stock_market",
                )
            ],
        )
        items = build_plan_preview(plan)
        self.assertEqual(items[0].title, "查询行情")
        self.assertEqual(items[0].args_summary, {"query": "贵州茅台", "limit": "30"})
        self.assertNotIn("secret", items[0].args_summary)


if __name__ == "__main__":
    unittest.main()
