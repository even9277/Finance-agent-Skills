from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.agents.controller.runtime_controller import ControllerDecision, RuntimeController
from src.agents.executor.budget import ExecutionBudget, RuntimeBudgetState
from src.agents.executor.execution_scheduler import BatchResult, ExecutionScheduler, StepResult
from src.agents.planner.plan_validator import PlanValidator, ToolPlanV2, ValidatedToolPlan
from src.agents.planner.sop_planner import SopPlanner
from src.agents.planner.tushare_planner import TusharePlanner
from src.agents.replanner.tushare_replanner import ReplanContext, TushareReplanner
from src.agents.tool_discovery.discovery_resolver import ToolDiscoveryResolver, ToolDiscoveryResult
from src.agents.tool_discovery.executable_registry import ExecutableToolRegistry, build_default_registry
from src.agents.verifier.evidence_verifier import EvidenceVerifier, VerificationResult


class SkillRunnerV2Result(BaseModel):
    plan: ToolPlanV2
    discovery: ToolDiscoveryResult
    validation: ValidatedToolPlan
    batches: list[BatchResult] = Field(default_factory=list)
    step_status_events: list[dict[str, Any]] = Field(default_factory=list)
    verification: VerificationResult
    controller: ControllerDecision
    replans: list[ToolPlanV2] = Field(default_factory=list)
    skill_loader_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    registry_version: str = ""
    skill_version: str = ""
    spec_hash: str = ""

    def tool_data(self) -> dict[str, Any]:
        step_results = flatten_step_results(self.batches)
        return {
            "plan": _dump_model(self.plan),
            "plan_steps": [
                {
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "goal": step.goal,
                    "required": step.required,
                    "evidence_type": step.evidence_type,
                }
                for step in self.plan.steps
            ],
            "plan_preview": [_dump_model(item) for item in self.validation.plan_preview],
            "batches": [_dump_model(item) for item in self.batches],
            "results": [
                _dump_model(item.evidence)
                for item in step_results
                if item.evidence is not None
            ],
            "verification": _dump_model(self.verification),
            "controller": _dump_model(self.controller),
            "replans": [_dump_model(item) for item in self.replans],
            "step_status_events": list(self.step_status_events),
            "skill_loader_artifacts": list(self.skill_loader_artifacts),
            "registry_version": self.registry_version,
            "skill_version": self.skill_version,
            "spec_hash": self.spec_hash,
            "executor_trace": build_executor_trace(self),
        }


def flatten_step_results(batches: list[BatchResult]) -> list[StepResult]:
    return [result for batch in batches for result in batch.step_results]


def _dump_model(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return dict(value)
    return {}


def build_execution_budget(config: Any = None) -> ExecutionBudget:
    return ExecutionBudget(
        per_tool_timeout_ms=int(getattr(config, "per_tool_timeout_ms", 8000)),
        per_tool_retry_limit=int(getattr(config, "per_tool_retry_limit", 1)),
        max_steps=int(getattr(config, "max_steps", 8)),
        total_timeout_ms=int(getattr(config, "total_timeout_ms", 25000)),
        max_replans=int(getattr(config, "max_replans", 1)),
        max_concurrency=int(getattr(config, "executor_max_concurrency", 6)),
        per_api_family_limit=int(getattr(config, "executor_per_api_family_limit", 2)),
        min_interval_ms=int(getattr(config, "executor_min_interval_ms", 150)),
    )


async def run_tushare_v2_pipeline(
    *,
    rewrite_result: Any,
    active_entity: Any = None,
    trace_id: str = "",
    config: Any = None,
    registry: ExecutableToolRegistry | None = None,
) -> SkillRunnerV2Result:
    registry = registry or build_default_registry()
    budget = build_execution_budget(config)
    resolver = ToolDiscoveryResolver(registry=registry)
    discovery = resolver.resolve(rewrite_result, active_entity=active_entity)
    plan = TusharePlanner(registry=registry).plan(
        rewrite_result=rewrite_result,
        discovery_result=discovery,
        active_entity=active_entity,
        trace_id=trace_id,
    )
    return await _run_plan_with_verification(
        plan=plan,
        discovery=discovery,
        active_entity=active_entity,
        budget=budget,
        registry=registry,
        config=config,
        allow_replan=True,
    )


async def run_sop_v2_pipeline(
    *,
    skill_name: str,
    skill_spec: dict[str, Any],
    user_message: str,
    rewrite_result: Any = None,
    active_entity: Any = None,
    trace_id: str = "",
    config: Any = None,
    registry: ExecutableToolRegistry | None = None,
) -> SkillRunnerV2Result:
    registry = registry or build_default_registry()
    budget = build_execution_budget(config)
    resolver = ToolDiscoveryResolver(registry=registry)
    discovery = resolver.resolve(rewrite_result or {"effective_query": user_message}, active_entity=active_entity)
    loader_artifacts: list[dict[str, Any]] = []
    registry_version = ""
    skill_version = ""
    spec_hash = ""
    if bool(getattr(config, "enable_skill_loader_v2", False)):
        try:
            from src.skills.skill_registry import get_skill_registry

            skill_registry = get_skill_registry()
            snapshot = skill_registry.get_active_snapshot()
            entry = snapshot.get(skill_name)
            registry_version = snapshot.registry_version
            skill_version = entry.skill_version if entry else ""
            spec_hash = entry.spec_hash if entry else ""
            loader = skill_registry.get_loader(
                token_budget_per_stage=int(getattr(config, "skill_loader_token_budget_per_stage", 2048))
            )
            rewrite_context = loader.load_for_rewrite(skill_name, query=user_message)
            planner_context = loader.load_for_planner(skill_name, query=user_message)
            synthesis_context = loader.load_for_synthesis(skill_name, query=user_message)
            loader_artifacts = [
                rewrite_context.artifact(),
                planner_context.artifact(),
                synthesis_context.artifact(),
            ]
            # planner 阶段以 loader 产出的 spec 为准；为空时保留旧入参，确保兼容。
            skill_spec = planner_context.spec or skill_spec
        except Exception as exc:  # pragma: no cover - loader failures must not break legacy path
            loader_artifacts = [{"stage": "loader", "error": str(exc)}]
    plan = SopPlanner(registry=registry).plan(
        skill_name=skill_name,
        skill_spec=skill_spec,
        user_message=user_message,
        rewrite_result=rewrite_result,
        discovery_result=discovery,
        trace_id=trace_id,
    )
    return await _run_plan_with_verification(
        plan=plan,
        discovery=discovery,
        active_entity=active_entity,
        budget=budget,
        registry=registry,
        config=config,
        allow_replan=False,
        skill_loader_artifacts=loader_artifacts,
        registry_version=registry_version,
        skill_version=skill_version,
        spec_hash=spec_hash,
    )


async def _run_plan_with_verification(
    *,
    plan: ToolPlanV2,
    discovery: ToolDiscoveryResult,
    active_entity: Any,
    budget: ExecutionBudget,
    registry: ExecutableToolRegistry,
    config: Any,
    allow_replan: bool,
    skill_loader_artifacts: list[dict[str, Any]] | None = None,
    registry_version: str = "",
    skill_version: str = "",
    spec_hash: str = "",
) -> SkillRunnerV2Result:
    validation = PlanValidator(registry=registry, max_steps=budget.max_steps).validate(plan, discovery_result=discovery)
    events: list[dict[str, Any]] = [
        {"type": "plan_preview", "plan_id": plan.plan_id, "items": [_dump_model(item) for item in validation.plan_preview]}
    ]

    async def on_step_status(step, status, result):
        events.append(
            {
                "type": "step_status",
                "plan_id": plan.plan_id,
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "status": status,
                **({"result": _dump_model(result)} if result is not None else {}),
            }
        )

    scheduler = ExecutionScheduler(registry=registry, budget=budget)
    batches = await scheduler.run(plan, on_step_status=on_step_status)
    step_results = flatten_step_results(batches)
    verifier = EvidenceVerifier(
        sufficient_threshold=int(getattr(config, "verifier_sufficient_threshold", 80)),
        partial_threshold=int(getattr(config, "verifier_partial_threshold", 60)),
    )
    verification = verifier.verify(plan=plan, step_results=step_results)
    budget_state = RuntimeBudgetState(budget=budget)
    controller = RuntimeController().decide(
        verification=verification,
        budget_state=budget_state,
        step_results=step_results,
    )
    replans: list[ToolPlanV2] = []

    if allow_replan and controller.action == "replan" and budget_state.can_replan():
        budget_state.replan_attempts += 1
        replan_context = ReplanContext(
            plan_id=plan.plan_id,
            trace_id=plan.trace_id,
            attempt=budget_state.replan_attempts - 1,
            completed_steps=[item for item in step_results if item.status == "succeeded"],
            failed_steps=[item for item in step_results if item.status != "succeeded"],
            accepted_evidences=verification.accepted_evidences,
            rejected_evidences=verification.rejected_evidences,
            missing_dimensions=verification.missing_dimensions,
            action_fingerprints=[item.action_fingerprint for item in step_results],
            budget_remaining_ms=budget_state.remaining_ms(),
            verifier_suggested=verification.suggested_next_action,
            user_intent_summary=plan.objective,
        )
        replan_result = TushareReplanner(registry=registry, budget=budget).replan(
            context=replan_context,
            discovery_result=discovery,
            active_entity=active_entity,
        )
        if replan_result.added_plan is not None:
            replans.append(replan_result.added_plan)
            events.append({"type": "replan_started", "plan_id": replan_result.added_plan.plan_id})
            extra_batches = await scheduler.run(replan_result.added_plan, on_step_status=on_step_status)
            batches.extend(extra_batches)
            step_results = flatten_step_results(batches)
            verification = verifier.verify(plan=plan, step_results=step_results)
            controller = RuntimeController().decide(
                verification=verification,
                budget_state=budget_state,
                step_results=step_results,
            )

    events.append({"type": "verification_summary", "plan_id": plan.plan_id, "verification": _dump_model(verification)})
    return SkillRunnerV2Result(
        plan=plan,
        discovery=discovery,
        validation=validation,
        batches=batches,
        step_status_events=events,
        verification=verification,
        controller=controller,
        replans=replans,
        skill_loader_artifacts=skill_loader_artifacts or [],
        registry_version=registry_version,
        skill_version=skill_version,
        spec_hash=spec_hash,
    )


def build_executor_trace(result: SkillRunnerV2Result) -> dict[str, Any]:
    step_results = flatten_step_results(result.batches)
    tools_attempted = [item.tool_name for item in step_results]
    tools_used = [item.tool_name for item in step_results if item.status == "succeeded"]
    return {
        "selected_skill_family": result.plan.route,
        "selected_skill": result.plan.skill_id or result.plan.route,
        "skill_name": result.plan.skill_id,
        "analysis_mode": "general_chat",
        "execution_policy": "plan_execute_v2",
        "reply_mode": "skill",
        "used_tools": bool(tools_used),
        "planned_tools": [step.tool_name for step in result.plan.steps],
        "prefetched_tool_names": tools_attempted,
        "tools_attempted": tools_attempted,
        "tools_used": tools_used,
        "evidence_ok": result.verification.status == "sufficient",
        "allowed_claim_level": result.verification.allowed_claim_level,
        "evidence_allowed_claim_level": result.verification.allowed_claim_level,
        "accepted_evidences": list(result.verification.accepted_evidences),
        "rejected_evidences": list(result.verification.rejected_evidences),
        "evidence_missing_dimensions": list(result.verification.missing_dimensions),
        "missing_evidence_reasons": list(result.verification.missing_dimensions),
        "plan_id": result.plan.plan_id,
        "discovery_trace_id": result.discovery.discovery_trace_id,
        "plan_preview": [_dump_model(item) for item in result.validation.plan_preview],
        "verification": _dump_model(result.verification),
        "controller": _dump_model(result.controller),
        "step_status_events": list(result.step_status_events),
        "skill_loader_artifacts": list(result.skill_loader_artifacts),
        "registry_version": result.registry_version,
        "skill_version": result.skill_version,
        "spec_hash": result.spec_hash,
    }


__all__ = [
    "SkillRunnerV2Result",
    "build_execution_budget",
    "flatten_step_results",
    "run_sop_v2_pipeline",
    "run_tushare_v2_pipeline",
]
