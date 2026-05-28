import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.synthesis.synthesize_fallback import build_fallback_synthesis_prompt  # noqa: E402


class FallbackSynthesisTests(unittest.TestCase):
    def test_fallback_warns_when_realtime_data_needed(self):
        prompt = build_fallback_synthesis_prompt(
            effective_query="今天贵州茅台涨了吗",
            answer_policy_context="简洁回答",
            ltm_full="无",
        )
        self.assertIn("fallback", prompt)
        self.assertIn("需要进入数据技能链路验证", prompt)
        self.assertIn("advisory", prompt)


if __name__ == "__main__":
    unittest.main()
