from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.agents.executor.budget import ExecutionBudget
from src.agents.executor.execution_scheduler import StepResult, action_fingerprint
from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2
from src.agents.planner.tushare_planner import TusharePlanner
from src.agents.tool_discovery.executable_registry import (
    ExecutableToolRegistry,
    build_default_registry,
)


class ReplanContext(BaseModel):
    plan_id: str
    trace_id: str
    attempt: int
    completed_steps: list[StepResult] = Field(default_factory=list)
    failed_steps: list[StepResult] = Field(default_factory=list)
    accepted_evidences: list[dict[str, Any]] = Field(default_factory=list)
    rejected_evidences: list[dict[str, Any]] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    action_fingerprints: list[str] = Field(default_factory=list)
    budget_remaining_ms: int = 0
    verifier_suggested: str = ""
    user_intent_summary: str = ""
    constraints_snapshot: list[str] = Field(default_factory=list)


class ReplanResult(BaseModel):
    added_plan: ToolPlanV2 | None = None
    skipped: bool = False
    reason: str = ""


class TushareReplanner:
    def __init__(
        self,
        *,
        registry: ExecutableToolRegistry | None = None,
        budget: ExecutionBudget | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.budget = budget or ExecutionBudget()
        self.planner = TusharePlanner(registry=self.registry, prompt_version="p5_tushare_replanner_v1")

    def replan(
        self,
        *,
        context: ReplanContext,
        discovery_result: Any,
        active_entity: Any = None,
    ) -> ReplanResult:
        if context.attempt >= self.budget.max_replans:
            return ReplanResult(skipped=True, reason="max_replans_exhausted")
        if context.budget_remaining_ms <= 0:
            return ReplanResult(skipped=True, reason="budget_exhausted")
        if not context.missing_dimensions:
            return ReplanResult(skipped=True, reason="no_missing_dimensions")

        rewrite = {
            "effective_query": context.user_intent_summary,
            "data_requirements": list(context.missing_dimensions),
            "candidate_tool_hints": [],
            "time_scope": {},
        }
        candidate_plan = self.planner.plan(
            rewrite_result=rewrite,
            discovery_result=discovery_result,
            active_entity=active_entity,
            trace_id=context.trace_id,
            constraints=context.constraints_snapshot,
        )
        existing = set(context.action_fingerprints)
        filtered_steps: list[ToolPlanStepV2] = []
        for step in candidate_plan.steps:
            fp = action_fingerprint(step.tool_name, step.arguments)
            if fp in existing:
                continue
            filtered_steps.append(
                ToolPlanStepV2(
                    step_id=f"r{context.attempt + 1}_s{len(filtered_steps) + 1}",
                    goal=step.goal,
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                    depends_on=[],
                    expected_observation=step.expected_observation,
                    required=step.required,
                    evidence_type=step.evidence_type,
                )
            )
        if not filtered_steps:
            return ReplanResult(skipped=True, reason="duplicate_action_fingerprint")

        candidate_plan.plan_id = f"{context.plan_id}_replan_{context.attempt + 1}"
        candidate_plan.steps = filtered_steps
        return ReplanResult(added_plan=candidate_plan, skipped=False, reason="missing_dimensions")


__all__ = ["ReplanContext", "ReplanResult", "TushareReplanner"]
