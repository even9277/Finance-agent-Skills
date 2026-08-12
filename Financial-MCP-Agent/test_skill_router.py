import sys
import unittest
from pathlib import Path
import asyncio
import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.skill_router_node import route_chat_skill


class SkillRouterTests(unittest.TestCase):
    @pytest.mark.live
    def test_routes_stock_research_question_to_financial_sop(self):
        result = asyncio.run(route_chat_skill("帮我看一下贵州茅台最新财务指标"))
        self.assertEqual(result.selected_skill, "financial-sop")
        self.assertEqual(result.selected_skill_family, "financial-sop")
        self.assertEqual(result.skill_name, "stock-first-pass")
        self.assertGreaterEqual(result.confidence, 0.8)
        self.assertEqual(result.analysis_mode, "stock_first_pass")

    def test_routes_small_talk_to_fallback(self):
        result = asyncio.run(route_chat_skill("你是谁"))
        self.assertEqual(result.selected_skill, "fallback")
        self.assertEqual(result.analysis_mode, "general_chat")

    @pytest.mark.live
    def test_follow_up_inherits_prior_finance_context(self):
        result = asyncio.run(
            route_chat_skill(
                "是，请查询",
                conversation_context="用户: 能推荐下黄金ETF的基金吗？\n助手: 可以继续为你查询黄金ETF基金。",
            )
        )
        self.assertEqual(result.selected_skill, "financial-sop")
        self.assertEqual(result.selected_skill_family, "financial-sop")
        self.assertEqual(result.skill_name, "etf-screen")
        self.assertEqual(result.analysis_mode, "etf_screen")
        self.assertTrue(result.arguments.get("is_follow_up"))


if __name__ == "__main__":
    unittest.main()
