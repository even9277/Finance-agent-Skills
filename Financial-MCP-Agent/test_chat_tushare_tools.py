import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.chat_tushare_tools import (
    _resolve_symbol,
    _run_web_news_search_tool,
    _to_tushare_ts_code,
    get_tushare_toolkit,
    resolve_sector_request,
)


class ChatTushareToolsTests(unittest.TestCase):
    def test_normalizes_baostock_style_symbol_to_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("sh.600519"), "600519.SH")
        self.assertEqual(_to_tushare_ts_code("sz.300750"), "300750.SZ")

    def test_normalizes_plain_code_to_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("600519"), "600519.SH")
        self.assertEqual(_to_tushare_ts_code("000001"), "000001.SZ")

    def test_keeps_existing_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("600519.SH"), "600519.SH")

    def test_resolve_symbol_prefers_query_resolved_symbol_when_exchange_suffix_is_wrong(self):
        with patch("backend.services.stock_resolver.resolve_stock", new=AsyncMock(return_value=("中国平安", "601318.SH"))):
            company_name, symbol, error = asyncio.run(
                _resolve_symbol(
                    query="中国平安（保险，非银行）最近一年经营指标，不要宏观分析",
                    symbol="601318.SZ",
                )
            )
        self.assertEqual(company_name, "中国平安")
        self.assertEqual(symbol, "601318.SH")
        self.assertIsNone(error)

    def test_resolve_sector_request_maps_new_energy_to_power_equipment(self):
        catalog = [
            {"industry_name": "电力设备", "index_code": "801730.SI", "level": "L1", "is_pub": "1", "_normalized_name": "电力设备"},
            {"industry_name": "汽车", "index_code": "801880.SI", "level": "L1", "is_pub": "1", "_normalized_name": "汽车"},
            {"industry_name": "公用事业", "index_code": "801160.SI", "level": "L1", "is_pub": "1", "_normalized_name": "公用事业"},
        ]
        with patch("src.tools.chat_tushare_tools._load_sw2021_sector_catalog", new=AsyncMock(return_value=catalog)):
            result = asyncio.run(resolve_sector_request(query="新能源板块最近行情怎么样"))
        self.assertEqual(result.get("normalized_sector_name"), "电力设备")
        self.assertEqual(result.get("index_code"), "801730.SI")
        self.assertGreater(result.get("match_confidence", 0), 0.8)

    def test_resolve_sector_request_returns_ambiguity_for_tech(self):
        catalog = [
            {"industry_name": "电子", "index_code": "801080.SI", "level": "L1", "is_pub": "1", "_normalized_name": "电子"},
            {"industry_name": "计算机", "index_code": "801750.SI", "level": "L1", "is_pub": "1", "_normalized_name": "计算机"},
            {"industry_name": "通信", "index_code": "801770.SI", "level": "L1", "is_pub": "1", "_normalized_name": "通信"},
            {"industry_name": "传媒", "index_code": "801760.SI", "level": "L1", "is_pub": "1", "_normalized_name": "传媒"},
        ]
        with patch("src.tools.chat_tushare_tools._load_sw2021_sector_catalog", new=AsyncMock(return_value=catalog)):
            result = asyncio.run(resolve_sector_request(query="科技板块怎么样"))
        self.assertEqual(result.get("failure_code"), "sector_ambiguous")
        self.assertIn("电子", result.get("candidate_sector_names", []))

    def test_toolkit_exposes_search_web_news(self):
        tool_names = {
            getattr(tool, "name", getattr(tool, "__name__", ""))
            for tool in get_tushare_toolkit()
        }
        self.assertIn("search_web_news", tool_names)

    def test_search_web_news_gracefully_fails_when_ddgs_unavailable(self):
        with patch("src.tools.chat_tushare_tools._DDGS_AVAILABLE", False):
            result = asyncio.run(_run_web_news_search_tool(query="中芯国际为什么涨了"))
        self.assertFalse(result.get("ok"))
        self.assertIn("ddgs", str(result.get("error", "")).lower())


if __name__ == "__main__":
    unittest.main()
