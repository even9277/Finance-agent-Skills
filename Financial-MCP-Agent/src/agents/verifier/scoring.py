from __future__ import annotations

from typing import Any

from src.agents.executor.execution_scheduler import StepResult
from src.agents.planner.plan_validator import ToolPlanV2


def _entity_symbol(plan: ToolPlanV2) -> str:
    entity = plan.entity or {}
    return str(entity.get("symbol") or entity.get("canonical_id") or entity.get("ts_code") or "").strip().upper()


def entity_consistency_score(plan: ToolPlanV2, accepted: list[StepResult]) -> int:
    target = _entity_symbol(plan)
    if not target:
        return 25
    checked = [item for item in accepted if item.evidence and item.evidence.symbol]
    if not checked:
        return 18
    matches = sum(1 for item in checked if str(item.evidence.symbol or "").upper() == target)
    return round(25 * matches / len(checked))


def freshness_score(plan: ToolPlanV2, accepted: list[StepResult]) -> int:
    if not accepted:
        return 0
    time_scope = plan.time_scope or {}
    if not time_scope:
        return 20
    dated = [item for item in accepted if item.evidence and (item.evidence.trade_date or item.evidence.data_time)]
    if not dated:
        return 8
    return 20


def dimension_coverage_score(plan: ToolPlanV2, accepted: list[StepResult]) -> int:
    required_types = {step.evidence_type for step in plan.steps if step.required}
    if not required_types:
        return 25
    accepted_types = {item.evidence.evidence_type for item in accepted if item.evidence}
    return round(25 * len(required_types & accepted_types) / len(required_types))


def evidence_role_score(plan: ToolPlanV2, accepted: list[StepResult]) -> int:
    if not accepted:
        return 0
    required_steps = {step.step_id for step in plan.steps if step.required}
    if not required_steps:
        return 15
    required_accepted = {item.step_id for item in accepted if item.step_id in required_steps}
    return round(15 * len(required_accepted) / len(required_steps))


def data_quality_score(accepted: list[StepResult]) -> int:
    if not accepted:
        return 0
    good = 0
    for item in accepted:
        evidence = item.evidence
        if not evidence or not evidence.ok:
            continue
        payload = evidence.payload_summary
        if payload not in (None, [], {}):
            good += 1
    return round(15 * good / len(accepted))


def score_evidence(plan: ToolPlanV2, accepted: list[StepResult]) -> dict[str, int]:
    return {
        "entity": entity_consistency_score(plan, accepted),
        "freshness": freshness_score(plan, accepted),
        "dimension": dimension_coverage_score(plan, accepted),
        "role": evidence_role_score(plan, accepted),
        "quality": data_quality_score(accepted),
    }


def score_total(breakdown: dict[str, int]) -> int:
    return int(sum(breakdown.values()))


__all__ = ["score_evidence", "score_total"]
