from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

REQUIRED_ROOT_FIELDS = {
    "skill_name",
    "skill_family",
    "version",
    "input_contract",
    "allowed_tools",
    "tool_plan_steps",
    "required_evidence",
    "output_template",
    "degrade_policy",
}


@dataclass(frozen=True, slots=True)
class SchemaGateIssue:
    code: str
    message: str
    severity: str = "error"
    field: str = ""


@dataclass(slots=True)
class SkillValidationReport:
    skill_name: str
    status: str
    issues: list[SchemaGateIssue] = field(default_factory=list)
    spec_hash: str = ""
    reference_hash: str = ""

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def disabled_reason(self) -> str:
        if self.passed:
            return ""
        return ";".join(issue.code for issue in self.issues if issue.severity == "error")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _required_evidence_types(required_evidence: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    for key in ("must_have_all", "must_have_any", "optional"):
        types.update(str(item) for item in _as_list(required_evidence.get(key)) if str(item).strip())
    return types


def validate_skill(
    spec: dict[str, Any] | None,
    *,
    allowed_tool_names: Iterable[str],
    evidence_types: Iterable[str],
    spec_hash: str = "",
    reference_hash: str = "",
) -> SkillValidationReport:
    payload = dict(spec or {})
    skill_name = str(payload.get("skill_name") or payload.get("name") or "").strip()
    issues: list[SchemaGateIssue] = []
    allowed_tools = set(str(item) for item in allowed_tool_names)
    known_evidence_types = set(str(item) for item in evidence_types)

    for field_name in sorted(REQUIRED_ROOT_FIELDS):
        if field_name not in payload:
            issues.append(SchemaGateIssue("missing_required_field", f"missing required field: {field_name}", field=field_name))

    for tool_name in _as_list(payload.get("allowed_tools")):
        if str(tool_name) not in allowed_tools:
            issues.append(SchemaGateIssue("unknown_allowed_tool", f"unknown allowed tool: {tool_name}", field="allowed_tools"))

    for idx, step in enumerate(_as_list(payload.get("tool_plan_steps"))):
        if not isinstance(step, dict):
            issues.append(SchemaGateIssue("invalid_plan_step", f"tool_plan_steps[{idx}] must be mapping", field="tool_plan_steps"))
            continue
        tool_name = str(step.get("tool") or "").strip()
        if not tool_name:
            issues.append(SchemaGateIssue("plan_step_missing_tool", f"tool_plan_steps[{idx}] missing tool", field="tool_plan_steps"))
        elif tool_name not in allowed_tools:
            issues.append(SchemaGateIssue("plan_step_tool_not_allowed", f"tool not allowed: {tool_name}", field="tool_plan_steps"))

    required_evidence = payload.get("required_evidence") or {}
    if not isinstance(required_evidence, dict):
        issues.append(SchemaGateIssue("invalid_required_evidence", "required_evidence must be mapping", field="required_evidence"))
    else:
        for evidence_type in sorted(_required_evidence_types(required_evidence)):
            if evidence_type not in known_evidence_types:
                issues.append(SchemaGateIssue("unknown_evidence_type", f"unknown evidence type: {evidence_type}", field="required_evidence"))

    status = "active" if not any(issue.severity == "error" for issue in issues) else "disabled"
    return SkillValidationReport(
        skill_name=skill_name or "unknown",
        status=status,
        issues=issues,
        spec_hash=spec_hash,
        reference_hash=reference_hash,
    )


__all__ = ["SchemaGateIssue", "SkillValidationReport", "validate_skill"]
