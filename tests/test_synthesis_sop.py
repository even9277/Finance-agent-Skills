import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.synthesis.synthesize_sop import build_sop_synthesis_prompt  # noqa: E402


class SopSynthesisTests(unittest.TestCase):
    def test_prompt_preserves_skill_contract(self):
        prompt = build_sop_synthesis_prompt(
            effective_query="做一份 ETF 筛选",
            tool_data={"results": [{"tool_name": "search_web_news", "evidence_type": "web_news", "payload": {"items": []}}]},
            skill_id="etf-screen",
            output_template="先结论后证据",
            fallbacks="证据不足则保守回答",
            decision_rules="不得强推",
        )
        self.assertIn("financial-sop", prompt)
        self.assertIn("先结论后证据", prompt)
        self.assertIn("证据不足则保守回答", prompt)
        self.assertIn("accepted_evidences", prompt)


if __name__ == "__main__":
    unittest.main()
