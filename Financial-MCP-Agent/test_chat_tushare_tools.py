import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.chat_tushare_tools import _to_tushare_ts_code, get_tushare_toolkit


class ChatTushareToolsTests(unittest.TestCase):
    def test_normalizes_baostock_style_symbol_to_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("sh.600519"), "600519.SH")
        self.assertEqual(_to_tushare_ts_code("sz.300750"), "300750.SZ")

    def test_normalizes_plain_code_to_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("600519"), "600519.SH")
        self.assertEqual(_to_tushare_ts_code("000001"), "000001.SZ")

    def test_keeps_existing_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("600519.SH"), "600519.SH")

    def test_toolkit_exposes_named_langchain_tools(self):
        """工具注册表必须保留业务名称，供 Skill Executor 按名称调用。"""
        expected = {
            "get_stock_basic_info",
            "get_market_bars",
            "get_fina_indicator",
            "get_income",
            "get_balance_sheet",
            "get_cashflow",
        }
        toolkit = get_tushare_toolkit()
        names = {getattr(tool, "name", "") for tool in toolkit}

        self.assertTrue(expected.issubset(names))
        self.assertTrue(all(callable(getattr(tool, "ainvoke", None)) for tool in toolkit))


if __name__ == "__main__":
    unittest.main()
