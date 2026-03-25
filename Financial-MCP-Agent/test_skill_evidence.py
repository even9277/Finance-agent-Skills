import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.skill_evidence import validate_evidence


class _ToolMessage:
    type = "tool"

    def __init__(self, name, content):
        self.name = name
        self.content = content


class SkillEvidenceTests(unittest.TestCase):
    def test_single_stock_fundamental_requires_market_and_financial_evidence(self):
        response = {
            "messages": [
                _ToolMessage("get_market_bars", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "close": 300.1}]}'),
                _ToolMessage("get_fina_indicator", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "roe": 18.2}]}'),
            ]
        }
        result = validate_evidence(
            analysis_mode="single_stock_fundamental",
            resolved_symbol="002594.SZ",
            response=response,
        )
        self.assertTrue(result.evidence_ok)
        self.assertIn("get_market_bars", result.successful_tools)
        self.assertIn("get_fina_indicator", result.successful_tools)

    def test_single_stock_fundamental_rejects_financial_only_evidence(self):
        response = {
            "messages": [
                _ToolMessage("get_fina_indicator", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "roe": 18.2}]}'),
            ]
        }
        result = validate_evidence(
            analysis_mode="single_stock_fundamental",
            resolved_symbol="002594.SZ",
            response=response,
        )
        self.assertFalse(result.evidence_ok)

    def test_parses_nan_in_tool_payload(self):
        response = {
            "messages": [
                _ToolMessage("get_market_bars", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "close": 100.1}]}'),
                _ToolMessage("get_fina_indicator", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "roe": 18.2, "ebitda": NaN}]}'),
            ]
        }
        result = validate_evidence(
            analysis_mode="single_stock_fundamental",
            resolved_symbol="002594.SZ",
            response=response,
        )
        self.assertTrue(result.evidence_ok)

    def test_normalizes_resolved_symbol_when_matching_evidence(self):
        response = {
            "messages": [
                _ToolMessage("get_market_bars", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "close": 100.1}]}'),
                _ToolMessage("get_fina_indicator", '{"ok": true, "symbol": "002594.SZ", "payload": [{"ts_code": "002594.SZ", "roe": 18.2}]}'),
            ]
        }
        result = validate_evidence(
            analysis_mode="single_stock_fundamental",
            resolved_symbol="sz.002594",
            response=response,
        )
        self.assertTrue(result.evidence_ok)

    def test_stock_selection_requires_fund_candidate_and_supporting_fund_data(self):
        response = {
            "messages": [
                _ToolMessage("get_fund_basic_info", '{"ok": true, "symbol": "159315.SZ", "payload": [{"ts_code": "159315.SZ", "name": "黄金股ETF基金"}]}'),
                _ToolMessage("get_fund_nav", '{"ok": true, "symbol": "159315.SZ", "payload": [{"ts_code": "159315.SZ", "unit_nav": 1.23}]}'),
            ]
        }
        result = validate_evidence(
            analysis_mode="stock_selection",
            resolved_symbol=None,
            response=response,
        )
        self.assertTrue(result.evidence_ok)

    def test_stock_selection_rejects_fund_candidates_without_support_data(self):
        response = {
            "messages": [
                _ToolMessage("get_fund_basic_info", '{"ok": true, "symbol": "159315.SZ", "payload": [{"ts_code": "159315.SZ", "name": "黄金股ETF基金"}]}'),
            ]
        }
        result = validate_evidence(
            analysis_mode="stock_selection",
            resolved_symbol=None,
            response=response,
        )
        self.assertFalse(result.evidence_ok)


if __name__ == "__main__":
    unittest.main()
