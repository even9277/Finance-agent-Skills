from __future__ import annotations

from typing import Any, Literal
import json

from pydantic import BaseModel, Field

from src.agents.planner.plan_preview import PlanPreviewItem, build_plan_preview
from src.agents.tool_discovery.executable_registry import (
    ExecutableToolRegistry,
    InputFieldSpec,
    build_default_registry,
)

ValidationLayer = Literal["governance", "structure", "semantic", "quality"]
ValidationSeverity = Literal["error", "warning"]

PLAN_VALIDATION_CODES = {
    "tool_not_in_registry",
    "tool_not_in_shortlist",
    "tool_disabled",
    "empty_plan",
    "self_dependency",
    "dependency_cycle",
    "step_id_duplicate",
    "depends_on_unknown_step",
    "arg_schema_violation",
    "missing_required_arg",
    "entity_type_mismatch",
    "time_scope_unsupported",
    "comparison_subjects_insufficient",
    "evidence_type_mismatch",
    "duplicate_action_fingerprint",
    "weak_evidence_only",
    "step_lacks_goal",
    "step_count_exceeds_max",
}


class ToolPlanStepV2(BaseModel):
    step_id: str
    goal: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_observation: str = ""
    required: bool = True
    evidence_type: str


class ToolPlanV2(BaseModel):
    plan_id: str
    trace_id: str = ""
    discovery_trace_id: str = ""
    route: Literal["tushare-data", "financial-sop"]
    skill_id: str | None = None
    objective: str
    entity: dict[str, Any] | None = None
    time_scope: dict[str, Any] = Field(default_factory=dict)
    steps: list[ToolPlanStepV2] = Field(default_factory=list)
    planner_model: str = "deterministic"
    prompt_version: str = "p5_validator_v1"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    layer: ValidationLayer
    severity: ValidationSeverity
    step_id: str | None = None
    code: str
    message: str


class ValidatedToolPlan(BaseModel):
    plan: ToolPlanV2
    warnings: list[ValidationIssue] = Field(default_factory=list)
    plan_preview: list[PlanPreviewItem] = Field(default_factory=list)


class PlanValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        message = "; ".join(f"{item.code}:{item.step_id or '-'}" for item in issues)
        super().__init__(message or "plan validation failed")


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _entity_type(entity: Any) -> str:
    payload = _model_dump(entity)
    raw = payload.get("asset_type") or payload.get("entity_type") or payload.get("type") or ""
    value = str(raw).strip().lower()
    if value in {"stock", "fund", "sector", "index"}:
        return value
    return "none"


def _fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"


class PlanValidator:
    def __init__(self, *, registry: ExecutableToolRegistry | None = None, max_steps: int = 8) -> None:
        self.registry = registry or build_default_registry()
        self.max_steps = max_steps

    def validate(self, plan: ToolPlanV2 | dict[str, Any], *, discovery_result: Any = None) -> ValidatedToolPlan:
        plan_obj = self._normalize_plan(plan)
        discovery = _model_dump(discovery_result)
        available_tools = set(discovery.get("available_tools") or self.registry.names(planner_visible_only=True))
        issues: list[ValidationIssue] = []

        issues.extend(self._validate_governance(plan_obj, available_tools))
        issues.extend(self._validate_structure(plan_obj))
        issues.extend(self._validate_semantic(plan_obj))
        issues.extend(self._validate_quality(plan_obj))

        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise PlanValidationError(errors)
        return ValidatedToolPlan(
            plan=plan_obj,
            warnings=[issue for issue in issues if issue.severity == "warning"],
            plan_preview=build_plan_preview(plan_obj),
        )

    @staticmethod
    def _normalize_plan(plan: ToolPlanV2 | dict[str, Any]) -> ToolPlanV2:
        if isinstance(plan, ToolPlanV2):
            return plan
        if hasattr(ToolPlanV2, "model_validate"):
            return ToolPlanV2.model_validate(plan)
        return ToolPlanV2.parse_obj(plan)

    def _validate_governance(self, plan: ToolPlanV2, available_tools: set[str]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        registry_names = set(self.registry.names())
        for step in plan.steps:
            if step.tool_name not in registry_names:
                issues.append(self._issue("governance", "error", "tool_not_in_registry", step.step_id, step.tool_name))
                continue
            spec = self.registry.spec(step.tool_name)
            if not spec.planner_visible:
                issues.append(self._issue("governance", "error", "tool_disabled", step.step_id, step.tool_name))
            if step.tool_name not in available_tools:
                issues.append(self._issue("governance", "error", "tool_not_in_shortlist", step.step_id, step.tool_name))
        return issues

    def _validate_structure(self, plan: ToolPlanV2) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not plan.steps:
            return [self._issue("structure", "error", "empty_plan", None, "plan has no steps")]

        ids: set[str] = set()
        for step in plan.steps:
            if step.step_id in ids:
                issues.append(self._issue("structure", "error", "step_id_duplicate", step.step_id, step.step_id))
            ids.add(step.step_id)
            if step.step_id in step.depends_on:
                issues.append(self._issue("structure", "error", "self_dependency", step.step_id, step.step_id))
            for dep in step.depends_on:
                if dep not in ids and dep not in {item.step_id for item in plan.steps}:
                    issues.append(self._issue("structure", "error", "depends_on_unknown_step", step.step_id, dep))
            if step.tool_name in self.registry.names():
                issues.extend(self._validate_arguments(step))

        if self._has_cycle(plan):
            issues.append(self._issue("structure", "error", "dependency_cycle", None, "plan dependency cycle"))
        return issues

    def _validate_arguments(self, step: ToolPlanStepV2) -> list[ValidationIssue]:
        spec = self.registry.spec(step.tool_name)
        issues: list[ValidationIssue] = []
        for field in spec.input_fields:
            if field.required and field.name not in step.arguments:
                issues.append(self._issue("structure", "error", "missing_required_arg", step.step_id, field.name))
                continue
            if field.name not in step.arguments:
                continue
            value = step.arguments.get(field.name)
            if not self._field_matches(value, field):
                issues.append(self._issue("structure", "error", "arg_schema_violation", step.step_id, field.name))
        return issues

    @staticmethod
    def _field_matches(value: Any, field: InputFieldSpec) -> bool:
        if value is None:
            return not field.required
        if field.type == "string":
            return isinstance(value, str)
        if field.type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if field.type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if field.type == "boolean":
            return isinstance(value, bool)
        if field.type == "array":
            return isinstance(value, list)
        if field.type == "object":
            return isinstance(value, dict)
        return True

    @staticmethod
    def _has_cycle(plan: ToolPlanV2) -> bool:
        graph = {step.step_id: set(step.depends_on) for step in plan.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for dep in graph.get(node, set()):
                if dep in graph and visit(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph)

    def _validate_semantic(self, plan: ToolPlanV2) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        entity_type = _entity_type(plan.entity)
        for step in plan.steps:
            if step.tool_name not in self.registry.names():
                continue
            spec = self.registry.spec(step.tool_name)
            if entity_type != "none" and entity_type not in spec.supported_entity_types:
                issues.append(self._issue("semantic", "error", "entity_type_mismatch", step.step_id, entity_type))
            if step.evidence_type != spec.evidence_type:
                issues.append(self._issue("semantic", "error", "evidence_type_mismatch", step.step_id, step.evidence_type))
        return issues

    def _validate_quality(self, plan: ToolPlanV2) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if len(plan.steps) > self.max_steps:
            issues.append(self._issue("quality", "error", "step_count_exceeds_max", None, str(len(plan.steps))))

        seen_fingerprints: dict[str, str] = {}
        for step in plan.steps:
            if not step.goal.strip():
                issues.append(self._issue("quality", "warning", "step_lacks_goal", step.step_id, "empty goal"))
            fp = _fingerprint(step.tool_name, step.arguments)
            previous = seen_fingerprints.get(fp)
            if previous:
                issues.append(self._issue("quality", "error", "duplicate_action_fingerprint", step.step_id, previous))
            seen_fingerprints[fp] = step.step_id

        if plan.steps and all(not self.registry.spec(step.tool_name).is_primary_evidence for step in plan.steps if step.tool_name in self.registry.names()):
            issues.append(self._issue("quality", "warning", "weak_evidence_only", None, "no primary evidence step"))
        return issues

    @staticmethod
    def _issue(
        layer: ValidationLayer,
        severity: ValidationSeverity,
        code: str,
        step_id: str | None,
        message: str,
    ) -> ValidationIssue:
        if code not in PLAN_VALIDATION_CODES:
            raise ValueError(f"unknown validation code: {code}")
        return ValidationIssue(layer=layer, severity=severity, step_id=step_id, code=code, message=message)


__all__ = [
    "PLAN_VALIDATION_CODES",
    "PlanValidationError",
    "PlanValidator",
    "ToolPlanStepV2",
    "ToolPlanV2",
    "ValidatedToolPlan",
    "ValidationIssue",
]
