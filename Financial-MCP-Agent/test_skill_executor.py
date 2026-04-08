import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.skill_executor_node import _build_prompt, _execution_observability_metrics


class SkillExecutorPromptTests(unittest.TestCase):
    def test_build_prompt_includes_memory_context_body(self):
        prompt = _build_prompt(
            user_message="请分析比亚迪今天值不值得买",
            memory_context="【用户投资画像】\n风险偏好：balanced\n关注板块：新能源",
            running_summary="此前用户长期关注新能源和半导体。",
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


if __name__ == "__main__":
    unittest.main()
