from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.agents.executor.budget import RuntimeBudgetState
from src.agents.executor.execution_scheduler import StepResult
from src.agents.verifier.evidence_verifier import VerificationResult

ControllerAction = Literal["continue", "retry", "replan", "stop", "graceful_degrade"]


class ControllerDecision(BaseModel):
    action: ControllerAction
    reason: str
    retry_steps: list[str] = []
    budget_remaining_ms: int
    stop_reason: str = ""


class RuntimeController:
    def decide(
        self,
        *,
        verification: VerificationResult,
        budget_state: RuntimeBudgetState,
        step_results: list[StepResult],
        repeated_fingerprints: set[str] | None = None,
    ) -> ControllerDecision:
        remaining = budget_state.remaining_ms()
        repeated = repeated_fingerprints or set()
        if remaining <= 0:
            return ControllerDecision(action="stop", reason="budget_exhausted", budget_remaining_ms=remaining, stop_reason="total_timeout")
        if repeated:
            return ControllerDecision(action="graceful_degrade", reason="duplicate_action_fingerprint", budget_remaining_ms=remaining)
        if verification.status == "sufficient":
            return ControllerDecision(action="continue", reason="evidence_sufficient", budget_remaining_ms=remaining)
        if verification.retryable_steps:
            return ControllerDecision(
                action="retry",
                reason="retryable_step_failure",
                retry_steps=list(verification.retryable_steps),
                budget_remaining_ms=remaining,
            )
        if verification.missing_dimensions and budget_state.can_replan():
            return ControllerDecision(action="replan", reason="missing_dimensions_replan_allowed", budget_remaining_ms=remaining)
        if verification.status == "partial":
            return ControllerDecision(action="graceful_degrade", reason="partial_evidence", budget_remaining_ms=remaining)
        return ControllerDecision(action="stop", reason="evidence_insufficient", budget_remaining_ms=remaining, stop_reason=verification.failure_reason)


__all__ = ["ControllerDecision", "RuntimeController"]
