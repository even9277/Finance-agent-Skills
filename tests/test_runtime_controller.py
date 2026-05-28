import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.controller.runtime_controller import RuntimeController  # noqa: E402
from src.agents.executor.budget import ExecutionBudget, RuntimeBudgetState  # noqa: E402
from src.agents.verifier.evidence_verifier import VerificationResult  # noqa: E402


def _verification(status="sufficient", retryable=None, missing=None, score=90):
    return VerificationResult(
        status=status,
        evidence_score=score,
        score_breakdown={"entity": 25, "freshness": 20, "dimension": 25, "role": 15, "quality": 15},
        allowed_claim_level="analytical" if status == "sufficient" else "descriptive",
        confidence=score / 100,
        retryable_steps=retryable or [],
        missing_dimensions=missing or [],
        suggested_next_action="continue",
    )


class RuntimeControllerTests(unittest.TestCase):
    def test_continue_when_sufficient(self):
        decision = RuntimeController().decide(
            verification=_verification(),
            budget_state=RuntimeBudgetState(ExecutionBudget()),
            step_results=[],
        )
        self.assertEqual(decision.action, "continue")

    def test_retry_when_retryable_steps_exist(self):
        decision = RuntimeController().decide(
            verification=_verification(status="partial", retryable=["s1"], score=60),
            budget_state=RuntimeBudgetState(ExecutionBudget()),
            step_results=[],
        )
        self.assertEqual(decision.action, "retry")
        self.assertEqual(decision.retry_steps, ["s1"])

    def test_replan_when_missing_dimensions_and_budget_allows(self):
        decision = RuntimeController().decide(
            verification=_verification(status="insufficient", missing=["stock_market"], score=30),
            budget_state=RuntimeBudgetState(ExecutionBudget(max_replans=1)),
            step_results=[],
        )
        self.assertEqual(decision.action, "replan")

    def test_graceful_degrade_when_partial_without_retry(self):
        decision = RuntimeController().decide(
            verification=_verification(status="partial", score=65),
            budget_state=RuntimeBudgetState(ExecutionBudget()),
            step_results=[],
        )
        self.assertEqual(decision.action, "graceful_degrade")

    def test_stop_when_budget_exhausted(self):
        state = RuntimeBudgetState(ExecutionBudget(total_timeout_ms=0))
        decision = RuntimeController().decide(
            verification=_verification(status="insufficient", score=20),
            budget_state=state,
            step_results=[],
        )
        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.stop_reason, "total_timeout")

    def test_repeated_fingerprint_degrades(self):
        decision = RuntimeController().decide(
            verification=_verification(status="partial", missing=["stock_market"], score=50),
            budget_state=RuntimeBudgetState(ExecutionBudget()),
            step_results=[],
            repeated_fingerprints={"x"},
        )
        self.assertEqual(decision.action, "graceful_degrade")
        self.assertEqual(decision.reason, "duplicate_action_fingerprint")


if __name__ == "__main__":
    unittest.main()
