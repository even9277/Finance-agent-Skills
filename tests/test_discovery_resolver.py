import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.tool_discovery.discovery_resolver import ToolDiscoveryResolver  # noqa: E402


class DiscoveryResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = ToolDiscoveryResolver()

    def test_pre_discover_stock_market_question(self):
        result = self.resolver.pre_discover(
            active_entity={"asset_type": "stock", "symbol": "600519.SH"},
            final_route="tushare-data",
            coarse_task="贵州茅台今天行情和走势",
        )
        self.assertEqual(result.stage, "pre_discover")
        self.assertIn("get_market_bars", result.available_tools)
        self.assertIn("get_daily_bars", result.available_tools)
        self.assertNotIn("get_fund_nav", result.available_tools)
        self.assertEqual(result.filtered_out_tools.get("get_fund_nav"), "entity_type_mismatch")

    def test_pre_discover_sector_question(self):
        result = self.resolver.pre_discover(
            active_entity={"asset_type": "sector"},
            final_route="tushare-data",
            coarse_task="新能源板块最近热点",
        )
        self.assertIn("get_sector_snapshot", result.available_tools)
        self.assertIn("get_sector_constituents", result.available_tools)
        self.assertIn("get_index_bars", result.available_tools)

    def test_resolve_keeps_candidate_tool_hints_inside_registry(self):
        result = self.resolver.resolve(
            {
                "candidate_tool_hints": ["get_market_bars", "get_fina_indicator"],
                "data_requirements": ["market_bars", "financial_indicator"],
            },
            active_entity={"asset_type": "stock"},
        )
        self.assertIn("get_market_bars", result.available_tools)
        self.assertIn("get_fina_indicator", result.available_tools)
        self.assertEqual(result.selection_reason["get_market_bars"], "candidate_tool_hint")
        self.assertEqual(result.missing_capabilities, [])

    def test_resolve_filters_unknown_tool_hints(self):
        result = self.resolver.resolve(
            {
                "candidate_tool_hints": ["get_market_bars", "invented_tool"],
                "data_requirements": ["stock_market"],
            },
            active_entity={"asset_type": "stock"},
        )
        self.assertIn("get_market_bars", result.available_tools)
        self.assertEqual(result.filtered_out_tools.get("invented_tool"), "unknown_tool_hint")

    def test_resolve_filters_entity_mismatch(self):
        result = self.resolver.resolve(
            {
                "candidate_tool_hints": ["get_fund_nav", "get_fund_share"],
                "data_requirements": ["fund_nav", "fund_share"],
            },
            active_entity={"asset_type": "stock"},
        )
        self.assertNotIn("get_fund_nav", result.available_tools)
        self.assertEqual(result.filtered_out_tools.get("get_fund_nav"), "entity_type_mismatch")

    def test_missing_capability_signal_reports_uncovered_evidence(self):
        missing = self.resolver.missing_capability_signal(
            required_evidence_types=["stock_market", "fund_nav"],
            available_tools=["get_market_bars"],
        )
        self.assertEqual(missing, ["fund_nav"])

    def test_tool_schemas_are_limited_to_available_tools(self):
        result = self.resolver.resolve(
            {
                "candidate_tool_hints": ["search_web_news"],
                "data_requirements": ["web_news"],
            },
            active_entity={"asset_type": "stock"},
        )
        self.assertEqual(result.available_tools, ["search_web_news"])
        self.assertEqual(set(result.tool_schemas), {"search_web_news"})
        self.assertIn("query", result.tool_schemas["search_web_news"]["required"])

    def test_resolve_uses_entities_when_active_entity_missing(self):
        result = self.resolver.resolve(
            {
                "entities": [{"asset_type": "fund", "symbol": "518880.SH"}],
                "candidate_tool_hints": ["get_fund_basic_info", "get_fund_nav"],
                "data_requirements": ["fund_basic", "fund_nav"],
            }
        )
        self.assertIn("get_fund_basic_info", result.available_tools)
        self.assertIn("get_fund_nav", result.available_tools)
        self.assertNotIn("get_market_bars", result.available_tools)


if __name__ == "__main__":
    unittest.main()
