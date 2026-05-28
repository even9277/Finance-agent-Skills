import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.router import route_v2


class RouteV2Tests(unittest.TestCase):
    def test_fund_compare_hits_sop(self):
        result = asyncio.run(route_v2("华安黄金 ETF 和博时黄金 ETF 哪个适合我"))
        self.assertEqual(result.final_route, "financial-sop")
        self.assertEqual(result.skill_id, "fund-compare")

    def test_concept_question_fallback(self):
        result = asyncio.run(route_v2("ETF 和 LOF 有什么区别"))
        self.assertEqual(result.final_route, "fallback")

    def test_current_market_question_tushare(self):
        result = asyncio.run(route_v2("贵州茅台今天收盘和最近走势"))
        self.assertEqual(result.final_route, "tushare-data")


if __name__ == "__main__":
    unittest.main()
