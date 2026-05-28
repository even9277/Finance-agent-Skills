import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.executor.evidence_envelope import EvidenceEnvelope  # noqa: E402
from src.agents.executor.execution_scheduler import StepResult  # noqa: E402
from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2  # noqa: E402
from src.agents.verifier.evidence_verifier import EvidenceVerifier  # noqa: E402


def _step(step_id, tool_name="get_market_bars", evidence_type="stock_market", required=True):
    return ToolPlanStepV2(
        step_id=step_id,
        goal="goal",
        tool_name=tool_name,
        arguments={"query": "贵州茅台", "limit": 1},
        expected_observation=evidence_type,
        required=required,
        evidence_type=evidence_type,
    )


def _plan(*steps, symbol="600519.SH"):
    return ToolPlanV2(
        plan_id="plan_v",
        trace_id="trace_v",
        route="tushare-data",
        objective="verify",
        entity={"asset_type": "stock", "symbol": symbol},
        steps=list(steps),
        time_scope={"trade_date": "latest_trading_day"},
    )


def _result(step_id="s1", tool_name="get_market_bars", evidence_type="stock_market", symbol="600519.SH", ok=True, status="succeeded", required_error=None):
    evidence = EvidenceEnvelope(
        evidence_id=f"ev_{step_id}",
        tool_call_id=f"tc_{step_id}",
        step_id=step_id,
        plan_id="plan_v",
        trace_id="trace_v",
        tool_name=tool_name,
        ok=ok,
        source_api="pro_bar",
        evidence_type=evidence_type,
        symbol=symbol,
        trade_date="20260520",
        data_time="2026-05-20T00:00:00+08:00",
        fetch_ts="2026-05-20T00:00:00+08:00",
        api_family="stock_market",
        payload_summary=[{"close": 100}],
        is_primary_evidence=True,
    )
    return StepResult(
        step_id=step_id,
        tool_name=tool_name,
        status=status,
        action_fingerprint=f"{tool_name}:x",
        error_type=required_error,
        is_retryable=bool(required_error),
        new_evidence=ok,
        evidence=evidence,
        started_at="t1",
        finished_at="t2",
        elapsed_ms=1,
    )


class EvidenceVerifierTests(unittest.TestCase):
    def test_sufficient_evidence_allows_analytical_claims(self):
        plan = _plan(_step("s1"))
        result = EvidenceVerifier().verify(plan=plan, step_results=[_result()])
        self.assertEqual(result.status, "sufficient")
        self.assertEqual(result.allowed_claim_level, "analytical")
        self.assertEqual(result.suggested_next_action, "continue")
        self.assertEqual(result.missing_dimensions, [])

    def test_required_all_missing_hard_gate_refuses(self):
        plan = _plan(_step("s1"))
        failed = _result(status="failed", ok=False, required_error="empty_payload")
        result = EvidenceVerifier().verify(plan=plan, step_results=[failed])
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.allowed_claim_level, "refuse")
        self.assertIn("required_all_missing", result.hard_gate_failures)
        self.assertEqual(result.suggested_next_action, "retry")

    def test_entity_conflict_hard_gate(self):
        plan = _plan(_step("s1"), symbol="600519.SH")
        result = EvidenceVerifier().verify(plan=plan, step_results=[_result(symbol="000001.SZ")])
        self.assertIn("entity_conflict", result.hard_gate_failures)
        self.assertEqual(result.allowed_claim_level, "refuse")

    def test_evidence_type_mismatch_hard_gate(self):
        plan = _plan(_step("s1", evidence_type="stock_market"))
        result = EvidenceVerifier().verify(plan=plan, step_results=[_result(evidence_type="stock_daily")])
        self.assertIn("schema_evidence_type_mismatch", result.hard_gate_failures)

    def test_partial_score_degrades(self):
        plan = _plan(_step("s1"), _step("s2", tool_name="get_fina_indicator", evidence_type="financial_indicator"))
        result = EvidenceVerifier().verify(plan=plan, step_results=[_result()])
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.allowed_claim_level, "descriptive")
        self.assertIn("financial_indicator", result.missing_dimensions)


if __name__ == "__main__":
    unittest.main()
