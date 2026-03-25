import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.chat_tushare_tools import _to_tushare_ts_code


class ChatTushareToolsTests(unittest.TestCase):
    def test_normalizes_baostock_style_symbol_to_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("sh.600519"), "600519.SH")
        self.assertEqual(_to_tushare_ts_code("sz.300750"), "300750.SZ")

    def test_normalizes_plain_code_to_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("600519"), "600519.SH")
        self.assertEqual(_to_tushare_ts_code("000001"), "000001.SZ")

    def test_keeps_existing_tushare_ts_code(self):
        self.assertEqual(_to_tushare_ts_code("600519.SH"), "600519.SH")


if __name__ == "__main__":
    unittest.main()
