import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.planner.plan_validator import PlanValidator  # noqa: E402
from src.agents.planner.tushare_planner import TusharePlanner  # noqa: E402
from src.agents.tool_discovery.discovery_resolver import ToolDiscoveryResolver  # noqa: E402


class TusharePlannerTests(unittest.TestCase):
    def test_plans_only_available_tools_from_rewrite_hints(self):
        rewrite = {
            "effective_query": "贵州茅台今天走势和财务指标",
            "entities": [{"asset_type": "stock", "symbol": "600519.SH", "display_name": "贵州茅台"}],
            "data_requirements": ["market_bars", "financial_indicator"],
            "time_scope": {"trade_date": "latest_trading_day"},
            "candidate_tool_hints": ["get_market_bars", "get_fina_indicator", "get_fund_nav"],
        }
        discovery = ToolDiscoveryResolver().resolve(rewrite, active_entity={"asset_type": "stock", "symbol": "600519.SH"})
        plan = TusharePlanner().plan(
            rewrite_result=rewrite,
            discovery_result=discovery,
            active_entity={"asset_type": "stock", "symbol": "600519.SH"},
            trace_id="trace_1",
        )
        tool_names = [step.tool_name for step in plan.steps]
        self.assertEqual(tool_names, ["get_market_bars", "get_fina_indicator"])
        self.assertEqual(plan.trace_id, "trace_1")
        self.assertEqual(plan.discovery_trace_id, discovery.discovery_trace_id)
        PlanValidator().validate(plan, discovery_result=discovery)

    def test_maps_requirements_when_hints_empty(self):
        rewrite = {
            "effective_query": "新能源板块最近行情",
            "data_requirements": ["sector_snapshot", "sector_constituents"],
        }
        active_entity = {"asset_type": "sector", "display_name": "新能源"}
        discovery = ToolDiscoveryResolver().resolve(rewrite, active_entity=active_entity)
        plan = TusharePlanner().plan(rewrite_result=rewrite, discovery_result=discovery, active_entity=active_entity)
        self.assertEqual([step.tool_name for step in plan.steps], ["get_sector_snapshot", "get_sector_constituents"])
        self.assertEqual(plan.steps[0].arguments.get("sector_name"), "新能源")
        PlanValidator().validate(plan, discovery_result=discovery)


if __name__ == "__main__":
    unittest.main()
