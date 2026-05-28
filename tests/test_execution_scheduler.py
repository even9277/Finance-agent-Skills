import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.executor.budget import ExecutionBudget  # noqa: E402
from src.agents.executor.execution_scheduler import (  # noqa: E402
    ExecutionScheduler,
    action_fingerprint,
    plan_execution_layers,
)
from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2  # noqa: E402


def _step(step_id, tool_name="get_market_bars", args=None, depends_on=None, evidence_type="stock_market"):
    return ToolPlanStepV2(
        step_id=step_id,
        goal=f"goal {step_id}",
        tool_name=tool_name,
        arguments=args if args is not None else {"query": step_id, "limit": 1},
        depends_on=depends_on or [],
        expected_observation=evidence_type,
        required=True,
        evidence_type=evidence_type,
    )


def _plan(*steps):
    return ToolPlanV2(
        plan_id="plan_exec",
        trace_id="trace_exec",
        discovery_trace_id="disc_exec",
        route="tushare-data",
        objective="execute",
        entity={"asset_type": "stock", "symbol": "600519.SH"},
        steps=list(steps),
    )


class ExecutionSchedulerTests(unittest.TestCase):
    def test_plan_execution_layers_respects_dependencies(self):
        plan = _plan(_step("s1"), _step("s2"), _step("s3", depends_on=["s1", "s2"]))
        layers = plan_execution_layers(plan)
        self.assertEqual([[step.step_id for step in layer] for layer in layers], [["s1", "s2"], ["s3"]])

    def test_action_fingerprint_is_argument_order_stable(self):
        left = action_fingerprint("get_market_bars", {"query": "a", "limit": 1})
        right = action_fingerprint("get_market_bars", {"limit": 1, "query": "a"})
        self.assertEqual(left, right)

    def test_run_success_normalizes_evidence_envelope(self):
        async def invoker(tool_name, arguments):
            return {
                "ok": True,
                "source_api": "pro_bar",
                "evidence_type": "stock_market",
                "symbol": "600519.SH",
                "payload": [{"trade_date": "20260520", "close": 100}],
            }

        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(min_interval_ms=0),
            tool_invoker=invoker,
        )
        batches = asyncio.run(scheduler.run(_plan(_step("s1"))))
        result = batches[0].step_results[0]
        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.new_evidence)
        self.assertEqual(result.evidence.evidence_type, "stock_market")
        self.assertEqual(result.evidence.tool_call_id.startswith("toolcall_"), True)

    def test_duplicate_fingerprint_is_skipped(self):
        async def invoker(tool_name, arguments):
            return {"ok": True, "source_api": "pro_bar", "evidence_type": "stock_market", "payload": []}

        plan = _plan(_step("s1", args={"query": "same", "limit": 1}), _step("s2", args={"query": "same", "limit": 1}))
        scheduler = ExecutionScheduler(budget=ExecutionBudget(min_interval_ms=0), tool_invoker=invoker)
        batches = asyncio.run(scheduler.run(plan))
        statuses = [item.status for item in batches[0].step_results]
        self.assertEqual(statuses.count("succeeded"), 1)
        self.assertEqual(statuses.count("skipped"), 1)

    def test_retries_failed_envelope_once(self):
        calls = 0

        async def invoker(tool_name, arguments):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"ok": False, "source_api": "pro_bar", "evidence_type": "stock_market", "payload": {}, "error": "empty"}
            return {"ok": True, "source_api": "pro_bar", "evidence_type": "stock_market", "payload": [{"close": 1}]}

        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(per_tool_retry_limit=1, min_interval_ms=0),
            tool_invoker=invoker,
        )
        result = asyncio.run(scheduler.run(_plan(_step("s1"))))[0].step_results[0]
        self.assertEqual(calls, 2)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.evidence.retry_count, 1)

    def test_timeout_result(self):
        async def invoker(tool_name, arguments):
            await asyncio.sleep(0.05)
            return {"ok": True}

        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(per_tool_timeout_ms=1, per_tool_retry_limit=0, min_interval_ms=0),
            tool_invoker=invoker,
        )
        result = asyncio.run(scheduler.run(_plan(_step("s1"))))[0].step_results[0]
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error_type, "timeout")
        self.assertTrue(result.is_retryable)

    def test_global_concurrency_limit(self):
        active = 0
        max_active = 0

        async def invoker(tool_name, arguments):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"ok": True, "source_api": "pro_bar", "evidence_type": "stock_market", "payload": [{"x": 1}]}

        plan = _plan(
            _step("s1", args={"query": "1", "limit": 1}),
            _step("s2", args={"query": "2", "limit": 1}),
            _step("s3", args={"query": "3", "limit": 1}),
        )
        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(max_concurrency=2, per_api_family_limit=3, min_interval_ms=0),
            tool_invoker=invoker,
        )
        asyncio.run(scheduler.run(plan))
        self.assertLessEqual(max_active, 2)

    def test_skill_concurrency_can_tighten_global_limit(self):
        active = 0
        max_active = 0

        async def invoker(tool_name, arguments):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"ok": True, "source_api": "pro_bar", "evidence_type": "stock_market", "payload": [{"x": 1}]}

        plan = _plan(
            _step("s1", args={"query": "1", "limit": 1}),
            _step("s2", args={"query": "2", "limit": 1}),
            _step("s3", args={"query": "3", "limit": 1}),
        )
        plan.metadata["skill_concurrency"] = {"enabled": True, "batch_size": 1}
        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(max_concurrency=3, per_api_family_limit=3, min_interval_ms=0),
            tool_invoker=invoker,
        )
        asyncio.run(scheduler.run(plan))
        self.assertLessEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
