from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.agents.executor.execution_scheduler import StepResult
from src.agents.planner.plan_validator import ToolPlanV2
from src.agents.verifier.scoring import score_evidence, score_total

EvidenceStatus = Literal["sufficient", "partial", "insufficient"]
ClaimLevel = Literal["advisory", "analytical", "descriptive", "refuse"]
SuggestedAction = Literal["continue", "retry", "replan", "stop", "graceful_degrade"]


class VerificationResult(BaseModel):
    status: EvidenceStatus
    evidence_score: int
    score_breakdown: dict[str, int]
    accepted_evidences: list[dict] = Field(default_factory=list)
    rejected_evidences: list[dict] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    allowed_claim_level: ClaimLevel
    confidence: float
    failure_reason: str = ""
    retryable_steps: list[str] = Field(default_factory=list)
    suggested_next_action: SuggestedAction
    hard_gate_failures: list[str] = Field(default_factory=list)


class EvidenceVerifier:
    def __init__(self, *, sufficient_threshold: int = 80, partial_threshold: int = 60) -> None:
        self.sufficient_threshold = sufficient_threshold
        self.partial_threshold = partial_threshold

    def verify(self, *, plan: ToolPlanV2, step_results: list[StepResult]) -> VerificationResult:
        accepted = [item for item in step_results if item.status == "succeeded" and item.evidence and item.evidence.ok]
        rejected = [item for item in step_results if item not in accepted]
        hard_gate_failures = self._hard_gate_failures(plan=plan, accepted=accepted, step_results=step_results)
        missing_dimensions = self._missing_dimensions(plan=plan, accepted=accepted)
        breakdown = score_evidence(plan, accepted)
        total = score_total(breakdown)

        if hard_gate_failures:
            status: EvidenceStatus = "insufficient"
            allowed: ClaimLevel = "refuse"
        elif total >= self.sufficient_threshold and not missing_dimensions:
            status = "sufficient"
            allowed = "analytical"
        elif total >= self.partial_threshold:
            status = "partial"
            allowed = "descriptive"
        else:
            status = "insufficient"
            allowed = "refuse"

        retryable_steps = [
            item.step_id
            for item in rejected
            if item.is_retryable or item.error_type in {"timeout", "rate_limited", "http_5xx", "empty_payload"}
        ]
        suggested = self._suggest_action(
            status=status,
            hard_gate_failures=hard_gate_failures,
            retryable_steps=retryable_steps,
            missing_dimensions=missing_dimensions,
        )
        return VerificationResult(
            status=status,
            evidence_score=total,
            score_breakdown=breakdown,
            accepted_evidences=[self._evidence_ref(item) for item in accepted],
            rejected_evidences=[self._rejected_ref(item) for item in rejected],
            missing_dimensions=missing_dimensions,
            allowed_claim_level=allowed,
            confidence=min(1.0, max(0.0, total / 100)),
            failure_reason=";".join(hard_gate_failures),
            retryable_steps=retryable_steps,
            suggested_next_action=suggested,
            hard_gate_failures=hard_gate_failures,
        )

    @staticmethod
    def _hard_gate_failures(*, plan: ToolPlanV2, accepted: list[StepResult], step_results: list[StepResult]) -> list[str]:
        failures: list[str] = []
        required_step_ids = {step.step_id for step in plan.steps if step.required}
        accepted_required = {item.step_id for item in accepted if item.step_id in required_step_ids}
        if required_step_ids and not accepted_required:
            failures.append("required_all_missing")

        plan_types = {step.step_id: step.evidence_type for step in plan.steps}
        for item in accepted:
            if item.evidence and item.evidence.evidence_type != plan_types.get(item.step_id):
                failures.append("schema_evidence_type_mismatch")
                break

        target_symbol = str((plan.entity or {}).get("symbol") or "").strip().upper()
        if target_symbol:
            for item in accepted:
                symbol = str(item.evidence.symbol or "").strip().upper() if item.evidence else ""
                if symbol and symbol != target_symbol:
                    failures.append("entity_conflict")
                    break
        return failures

    @staticmethod
    def _missing_dimensions(*, plan: ToolPlanV2, accepted: list[StepResult]) -> list[str]:
        accepted_types = {item.evidence.evidence_type for item in accepted if item.evidence}
        missing = []
        for step in plan.steps:
            if step.required and step.evidence_type not in accepted_types:
                missing.append(step.evidence_type)
        return list(dict.fromkeys(missing))

    @staticmethod
    def _suggest_action(
        *,
        status: EvidenceStatus,
        hard_gate_failures: list[str],
        retryable_steps: list[str],
        missing_dimensions: list[str],
    ) -> SuggestedAction:
        if retryable_steps:
            return "retry"
        if hard_gate_failures and missing_dimensions:
            return "replan"
        if status == "sufficient":
            return "continue"
        if status == "partial":
            return "graceful_degrade"
        return "stop"

    @staticmethod
    def _evidence_ref(item: StepResult) -> dict:
        evidence = item.evidence
        return {
            "step_id": item.step_id,
            "tool_name": item.tool_name,
            "evidence_id": evidence.evidence_id if evidence else "",
            "evidence_type": evidence.evidence_type if evidence else "",
            "symbol": evidence.symbol if evidence else None,
            "source_api": evidence.source_api if evidence else "",
            "trade_date": evidence.trade_date if evidence else None,
        }

    @staticmethod
    def _rejected_ref(item: StepResult) -> dict:
        evidence = item.evidence
        return {
            "step_id": item.step_id,
            "tool_name": item.tool_name,
            "status": item.status,
            "error_type": item.error_type or (evidence.error_type if evidence else None),
            "error_message": item.error_message or (evidence.error_message if evidence else None),
            "evidence_id": evidence.evidence_id if evidence else "",
            "evidence_type": evidence.evidence_type if evidence else "",
        }


__all__ = ["EvidenceStatus", "EvidenceVerifier", "VerificationResult"]
