"""在执行前校验权限、实体、DAG 和证据覆盖。"""

from __future__ import annotations

from .contracts import (
    PlanValidationResult,
    ToolPermissionSnapshot,
    ToolPlan,
    ValidatedToolPlan,
    ValidationIssue,
    ValidationIssueCode,
)


class PlanValidator:
    """纯领域计划校验器，不读取网络或注册表运行态。"""

    def validate(
        self,
        plan: ToolPlan,
        permissions: ToolPermissionSnapshot,
    ) -> PlanValidationResult:
        """阻断越权、重复、悬空、成环和缺证据计划。

        Args:
            plan: Planner 生成的未校验计划。
            permissions: Planner 与 Executor 共享的权限快照。

        Returns:
            结构化问题列表；无问题时包含可执行计划。
        """
        issues: list[ValidationIssue] = []
        step_ids = [step.step_id for step in plan.steps]
        known_steps = set(step_ids)

        seen: set[str] = set()
        for step in plan.steps:
            if step.step_id in seen:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.DUPLICATE_STEP,
                        message="step_id must be unique",
                        step_id=step.step_id,
                    )
                )
            seen.add(step.step_id)
            if step.tool_name not in permissions.allowed_tools:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.TOOL_NOT_ALLOWED,
                        message="tool is outside the permission snapshot",
                        step_id=step.step_id,
                    )
                )
            if step.symbol != plan.entity.symbol:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.ENTITY_MISMATCH,
                        message="step symbol differs from the authoritative entity",
                        step_id=step.step_id,
                    )
                )
            for dependency in step.depends_on:
                if dependency not in known_steps:
                    issues.append(
                        ValidationIssue(
                            code=ValidationIssueCode.UNKNOWN_DEPENDENCY,
                            message="step dependency does not exist",
                            step_id=step.step_id,
                        )
                    )

        if self._contains_cycle(plan):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.CYCLIC_DEPENDENCY,
                    message="plan dependencies contain a cycle",
                )
            )

        covered = {step.evidence_dimension for step in plan.steps}
        for requirement in plan.requirements:
            if requirement.required and requirement.dimension not in covered:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.MISSING_REQUIRED_EVIDENCE,
                        message="required evidence dimension is not covered",
                    )
                )

        if issues:
            return PlanValidationResult(
                is_valid=False,
                issues=tuple(issues),
                validated_plan=None,
            )
        return PlanValidationResult(
            is_valid=True,
            issues=(),
            validated_plan=ValidatedToolPlan(
                plan=plan,
                permission_hash=permissions.snapshot_hash,
            ),
        )

    @staticmethod
    def _contains_cycle(plan: ToolPlan) -> bool:
        graph = {step.step_id: step.depends_on for step in plan.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in visiting:
                return True
            if step_id in visited:
                return False
            visiting.add(step_id)
            for dependency in graph.get(step_id, ()):
                if dependency in graph and visit(dependency):
                    return True
            visiting.remove(step_id)
            visited.add(step_id)
            return False

        return any(visit(step_id) for step_id in graph)
