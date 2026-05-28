import asyncio
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "langchain_core.messages" not in sys.modules:
    langchain_core = types.ModuleType("langchain_core")
    langchain_core_messages = types.ModuleType("langchain_core.messages")

    class AIMessage:  # pragma: no cover - import shim for test env
        def __init__(self, content=None):
            self.content = content

    langchain_core_messages.AIMessage = AIMessage
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.messages"] = langchain_core_messages

from src.agents.skill_executor_node import (
    _build_prompt,
    _build_synthesis_prompt,
    _execute_financial_sop_skill,
    _execution_observability_metrics,
)
from src.agents.tushare_reference_planner import PlannedToolCall, TushareToolPlan


class SkillExecutorPromptTests(unittest.TestCase):
    def test_build_prompt_includes_memory_context_body(self):
        prompt = _build_prompt(
            user_message="请分析比亚迪今天值不值得买",
            memory_context="【用户投资画像】\n风险偏好：balanced\n关注板块：新能源",
            answer_policy_context="【回答策略上下文】\nconstraints:\n- 当前只看 A 股口径\nreply_preference_hint: 先给结论，再展开",
            profile_summary="风险偏好: balanced",
            resolved_company="比亚迪",
            resolved_symbol="002594.SZ",
            selected_skill="tushare-data",
            analysis_mode="single_stock_fundamental",
            tool_plan_summary="- get_market_bars: recent market context",
        )
        self.assertIn("【memory_context】", prompt)
        self.assertIn("风险偏好：balanced", prompt)
        self.assertIn("关注板块：新能源", prompt)
        self.assertIn("【回答策略上下文】", prompt)
        self.assertNotIn("【running_summary】", prompt)

    def test_build_synthesis_prompt_uses_answer_policy_context(self):
        prompt = _build_synthesis_prompt(
            user_message="继续分析比亚迪",
            memory_context="",
            answer_policy_context="【回答策略上下文】\nconstraints:\n- 当前只看 A 股口径",
            profile_summary="",
            selected_skill="tushare-data",
            analysis_mode="general_chat",
            resolved_company="比亚迪",
            resolved_symbol="002594.SZ",
            tool_results=[],
        )
        self.assertIn("【回答策略上下文】", prompt)
        self.assertIn("当前只看 A 股口径", prompt)
        self.assertNotIn("【running_summary】", prompt)

    def test_execution_observability_metrics_include_failure_rate_latency_and_policy(self):
        metrics = _execution_observability_metrics(
            route_confidence=0.91,
            planned_tool_names=["get_fund_basic_info", "get_fund_nav", "forbidden_tool"],
            tool_results=[
                ("get_fund_basic_info", {"ok": True, "duration_ms": 120}),
                ("get_fund_nav", {"ok": False, "duration_ms": 450}),
            ],
            degrade_policy={"current_stage": "graceful_decline"},
            policy_violation_names=["forbidden_tool"],
            evidence_ok=False,
        )
        self.assertEqual(metrics["tool_batch_size"], 3)
        self.assertEqual(metrics["tool_failure_count"], 1)
        self.assertAlmostEqual(metrics["tool_failure_rate"], 0.5)
        self.assertEqual(metrics["policy_violation_count"], 1)
        self.assertEqual(metrics["degrade_stage"], "graceful_decline")
        self.assertEqual(metrics["p95_latency"], 450.0)
        self.assertFalse(metrics["evidence_ok"])

    def test_execute_financial_sop_skill_short_circuits_on_sector_preflight_failure(self):
        skill_spec = {
            "allowed_tools": ["get_sector_snapshot", "get_sector_constituents", "get_index_bars"],
            "tool_plan_steps": [{"tool": "get_sector_snapshot", "required": True}],
            "degrade_policy": {
                "stages": [
                    {"name": "primary", "next_stage": "graceful_decline"},
                    {"name": "graceful_decline", "next_stage": "none"},
                ],
                "when_missing_evidence": "graceful_decline",
            },
        }
        fake_registry = SimpleNamespace(
            load_skill_spec=lambda _skill_name: skill_spec,
            load_skill_markdown=lambda _skill_name: "# Sector Hotspot Brief",
            find_references=lambda *_args, **_kwargs: [],
        )
        fake_plan = TushareToolPlan(
            selected_skill="financial-sop",
            analysis_mode="sector_hotspot_brief",
            planner_type="skill_planner",
            references=[],
            tool_calls=[
                PlannedToolCall(
                    tool_name="get_sector_snapshot",
                    arguments={"query": "新能源板块最近行情怎么样"},
                    reason="inspect sector snapshot",
                    required=True,
                )
            ],
        )

        with patch("src.agents.skill_executor_node.get_skill_registry", return_value=fake_registry):
            with patch("src.agents.skill_executor_node.build_skill_tool_plan", return_value=fake_plan):
                result = asyncio.run(
                    _execute_financial_sop_skill(
                        selected_skill="financial-sop",
                        skill_name="sector-hotspot-brief",
                        execution_policy="deterministic",
                        user_message="新能源板块最近行情怎么样",
                        effective_query="新能源板块最近行情怎么样",
                        memory_context="",
                        answer_policy_context="",
                        profile_summary="",
                        route_arguments={
                            "skill_params": {
                                "raw_sector_query": "新能源",
                                "failure_code": "sector_unresolved",
                            }
                        },
                        analysis_mode="sector_market",
                        enable_tool_prefetch_concurrency=False,
                        router_model="router",
                        resolver_model="resolver",
                        synthesis_model="synthesis",
                        route_confidence=1.0,
                    )
                )

        self.assertEqual(result.failure_code, "sector_unresolved")
        self.assertEqual(result.trace.get("reply_mode"), "graceful-decline")
        self.assertFalse(result.trace.get("used_tools"))
        self.assertEqual(result.trace.get("preflight_result"), "sector_unresolved")
        self.assertEqual(result.trace.get("planned_tools"), ["get_sector_snapshot"])


if __name__ == "__main__":
    unittest.main()
