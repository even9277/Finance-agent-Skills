import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.skill_evidence import validate_evidence


class _ToolMessage:
    def __init__(self, name, content):
        self.name = name
        self.content = content
        self.type = "tool"


class SkillEvidenceTests(unittest.TestCase):
    def test_validate_evidence_emits_evidence_ids(self):
        response = {
            "messages": [
                _ToolMessage(
                    "get_fund_basic_info",
                    '{"ok": true, "tool_result_id": "toolr_1", "evidence_type": "fund_basic", "symbol": "159321.SZ", "payload": [{"ts_code": "159321.SZ"}]}',
                ),
                _ToolMessage(
                    "get_fund_nav",
                    '{"ok": true, "tool_result_id": "toolr_2", "evidence_type": "fund_nav", "symbol": "159321.SZ", "payload": [{"trade_date": "20260407"}]}',
                ),
            ]
        }
        result = validate_evidence(
            analysis_mode="fund_compare",
            resolved_symbol=None,
            response=response,
            skill_spec={
                "required_evidence": {
                    "must_have_all": ["fund_basic"],
                    "must_have_any": ["fund_nav"],
                }
            },
        )
        self.assertTrue(result.evidence_ok)
        self.assertEqual(len(result.accepted_evidences), 2)
        for item in result.accepted_evidences:
            self.assertTrue(item.get("evidence_id"))


if __name__ == "__main__":
    unittest.main()
