import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.tushare_reference_planner import build_tushare_tool_plan


class TushareReferencePlannerTests(unittest.TestCase):
    def test_builds_fundamental_plan_with_market_and_financial_tools(self):
        plan = build_tushare_tool_plan(
            user_message="请根据我的用户画像，专业分析下比亚迪今天值不值得买入",
            analysis_mode="single_stock_fundamental",
            resolved_symbol="002594.SZ",
            enable_market_tools=True,
            enable_index_tools=False,
            enable_sector_tools=False,
        )
        tool_names = [item.tool_name for item in plan.tool_calls]
        self.assertIn("get_market_bars", tool_names)
        self.assertIn("get_fina_indicator", tool_names)
        self.assertIn("get_income", tool_names)

    def test_builds_sector_plan_with_sector_tools(self):
        plan = build_tushare_tool_plan(
            user_message="分析半导体板块今天行情",
            analysis_mode="sector_market",
            resolved_symbol=None,
            enable_market_tools=False,
            enable_index_tools=False,
            enable_sector_tools=True,
        )
        tool_names = [item.tool_name for item in plan.tool_calls]
        self.assertIn("get_sector_snapshot", tool_names)

    def test_builds_fund_selection_plan_with_fund_tools(self):
        plan = build_tushare_tool_plan(
            user_message="能推荐下黄金ETF的基金吗？",
            analysis_mode="stock_selection",
            resolved_symbol=None,
            enable_market_tools=True,
            enable_index_tools=False,
            enable_sector_tools=True,
        )
        tool_names = [item.tool_name for item in plan.tool_calls]
        self.assertIn("get_fund_basic_info", tool_names)
        self.assertIn("get_fund_nav", tool_names)
        self.assertIn("get_fund_share", tool_names)


if __name__ == "__main__":
    unittest.main()
