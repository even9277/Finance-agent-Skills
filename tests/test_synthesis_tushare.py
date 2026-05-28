import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.synthesis.synthesize_tushare import build_tushare_synthesis_prompt  # noqa: E402


class TushareSynthesisTests(unittest.TestCase):
    def test_prompt_uses_answer_context_pack_and_claim_level(self):
        prompt = build_tushare_synthesis_prompt(
            effective_query="分析贵州茅台最近走势",
            tool_data={
                "verification": {
                    "allowed_claim_level": "descriptive",
                    "missing_dimensions": ["stock_market"],
                    "accepted_evidences": [
                        {
                            "step_id": "s1",
                            "tool_name": "get_market_bars",
                            "evidence_id": "ev1",
                            "evidence_type": "stock_market",
                            "symbol": "600519.SH",
                            "source_api": "pro_bar",
                        }
                    ],
                }
            },
            answer_policy_context="偏保守",
            ltm_full="用户偏好：风险优先",
        )
        self.assertIn("AnswerContextPack", prompt)
        self.assertIn("allowed_claim_level", prompt)
        self.assertIn("descriptive", prompt)
        self.assertIn("不得输出强因果", prompt)
        self.assertNotIn("证据包 tool_data", prompt)


if __name__ == "__main__":
    unittest.main()
