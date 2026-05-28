import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.planner.plan_validator import PlanValidator  # noqa: E402
from src.agents.planner.sop_planner import SopPlanner  # noqa: E402
from src.agents.tool_discovery.discovery_resolver import ToolDiscoveryResolver  # noqa: E402


def _load_skill_spec(skill_name: str) -> dict:
    path = AGENT / "src" / "skills" / skill_name / "skill_spec.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class SopPlannerTests(unittest.TestCase):
    def test_stock_first_pass_wraps_skill_spec_plan(self):
        spec = _load_skill_spec("stock-first-pass")
        rewrite = {
            "effective_query": "贵州茅台现在怎么看",
            "entities": [{"asset_type": "stock", "symbol": "600519.SH", "display_name": "贵州茅台"}],
            "skill_params": {},
        }
        discovery = ToolDiscoveryResolver().resolve(
            {
                "candidate_tool_hints": spec["allowed_tools"],
                "data_requirements": ["stock_basic", "stock_market", "financial_indicator"],
            },
            active_entity={"asset_type": "stock", "symbol": "600519.SH"},
        )
        plan = SopPlanner().plan(
            skill_name="stock-first-pass",
            skill_spec=spec,
            user_message="贵州茅台现在怎么看",
            rewrite_result=rewrite,
            discovery_result=discovery,
            trace_id="trace_sop",
        )
        self.assertEqual(plan.route, "financial-sop")
        self.assertEqual(plan.skill_id, "stock-first-pass")
        self.assertEqual(plan.trace_id, "trace_sop")
        self.assertIn("get_stock_basic_info", [step.tool_name for step in plan.steps])
        PlanValidator().validate(plan, discovery_result=discovery)

    def test_fund_compare_repeats_steps_for_subjects(self):
        spec = _load_skill_spec("fund-compare")
        rewrite = {
            "effective_query": "华安黄金ETF和博时黄金ETF哪个适合我",
            "entities": [{"asset_type": "fund", "display_name": "华安黄金ETF"}],
            "skill_params": {
                "subjects": ["华安黄金ETF", "博时黄金ETF"],
            },
        }
        discovery = ToolDiscoveryResolver().resolve(
            {
                "candidate_tool_hints": spec["allowed_tools"],
                "data_requirements": ["fund_basic", "fund_nav", "fund_share"],
            },
            active_entity={"asset_type": "fund"},
        )
        plan = SopPlanner().plan(
            skill_name="fund-compare",
            skill_spec=spec,
            user_message="华安黄金ETF和博时黄金ETF哪个适合我",
            rewrite_result=rewrite,
            discovery_result=discovery,
        )
        basic_queries = [
            step.arguments.get("query")
            for step in plan.steps
            if step.tool_name == "get_fund_basic_info"
        ]
        self.assertEqual(basic_queries, ["华安黄金ETF", "博时黄金ETF"])
        PlanValidator().validate(plan, discovery_result=discovery)


if __name__ == "__main__":
    unittest.main()
