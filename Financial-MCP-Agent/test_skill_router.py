import sys
import unittest
from pathlib import Path
import asyncio
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.skill_router_node import (
    RouteFallback,
    RouteTushare,
    _build_sop_catalog,
    _extract_json_dict,
    route_chat_skill,
    skill_route_decision_from_dict,
    user_explicit_sop_decision,
)


class SkillRouterTests(unittest.TestCase):
    def test_build_sop_catalog_contains_name_and_description(self):
        catalog = _build_sop_catalog()
        self.assertIn("fund-compare", catalog)
        self.assertIn(": ", catalog)

    def test_extract_json_dict_supports_markdown_fence(self):
        payload = _extract_json_dict('```json\n{"route":"tushare"}\n```')
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("route"), "tushare")

    def test_extract_json_dict_supports_noisy_text_with_fenced_json(self):
        raw = (
            "模型前置说明（应被忽略）\n"
            "```json\n"
            '{"route":"tushare","skill_id":"fund-compare","execution_policy":"agentic"}\n'
            "```\n"
            "模型尾部说明（应被忽略）"
        )
        payload = _extract_json_dict(raw)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("route"), "tushare")

    def test_routes_finance_question_to_tushare(self):
        with patch(
            "src.agents.skill_router_node._llm_route",
            new=AsyncMock(return_value=RouteTushare(route="tushare")),
        ):
            result = asyncio.run(route_chat_skill("贵州茅台今天收盘多少钱"))
        self.assertEqual(result.route, "tushare")
        self.assertIsNone(result.skill_id)
        self.assertEqual(result.execution_policy, "deterministic")

    def test_non_sop_route_never_carries_skill_id(self):
        result = skill_route_decision_from_dict(
            {"route": "fallback", "skill_id": "fund-compare", "execution_policy": "agentic"}
        )
        self.assertEqual(result.route, "fallback")
        self.assertIsNone(result.skill_id)
        self.assertEqual(result.execution_policy, "deterministic")

    def test_routes_small_talk_to_fallback(self):
        with patch(
            "src.agents.skill_router_node._llm_route",
            new=AsyncMock(return_value=RouteFallback(route="fallback")),
        ):
            result = asyncio.run(route_chat_skill("你是谁"))
        self.assertEqual(result.route, "fallback")
        self.assertIsNone(result.skill_id)

    def test_user_explicit_sop_decision_uses_registry_execution_policy(self):
        result = user_explicit_sop_decision("fund-compare")
        self.assertIsNotNone(result)
        self.assertEqual(result.route, "sop")
        self.assertEqual(result.skill_id, "fund-compare")
        self.assertEqual(result.execution_policy, "deterministic")

    def test_user_explicit_sop_decision_rejects_unknown_skill(self):
        result = user_explicit_sop_decision("not-exist")
        self.assertIsNone(result)

    def test_weak_reference_reanswer_can_route_to_tushare_when_llm_hits(self):
        with patch(
            "src.agents.skill_router_node._llm_route",
            new=AsyncMock(return_value=RouteTushare(route="tushare")),
        ):
            result = asyncio.run(route_chat_skill("重新回答，给我今天收盘和最近走势"))
        self.assertEqual(result.route, "tushare")
        self.assertIsNone(result.skill_id)


if __name__ == "__main__":
    unittest.main()
