import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.tools.chat_tushare_tools import _build_response  # noqa: E402


class ChatTushareToolsEnvelopeTests(unittest.TestCase):
    def test_build_response_includes_v2_envelope_fields(self):
        result = _build_response(
            symbol="600519.SH",
            payload=[{"trade_date": "20260520", "close": 100.0}],
            source_api="pro_bar",
            evidence_type="stock_market",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source_api"], "pro_bar")
        self.assertEqual(result["api_family"], "stock_market")
        self.assertEqual(result["trade_date"], "20260520")
        self.assertTrue(result["fetch_ts"])
        self.assertEqual(result["fetch_ts"], result["data_time"])
        self.assertIn("evidence_id", result)
        self.assertIn("tool_result_id", result)


if __name__ == "__main__":
    unittest.main()
