"""在任何外部调用前校验权限、参数、DAG、预算和证据覆盖。"""

from __future__ import annotations

from .contracts import (
    PlanValidationResult,
    RunBudget,
    ToolArgumentKind,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
    ToolSideEffect,
    ValidatedToolPlan,
    ValidationIssue,
    ValidationIssueCode,
)


class PlanValidator:
    """纯领域校验器；不读取注册表运行态，也不执行任何工具。"""

    def validate(
        self,
        plan: ToolPlan,
        permissions: ToolPermissionSnapshot,
        *,
        budget: RunBudget | None = None,
    ) -> PlanValidationResult:
        """阻断越权、非法参数、重复动作、无效 DAG 和预算超限。

        Args:
            plan: Planner 生成的未校验计划。
            permissions: Planner 使用的同一请求级权限快照。
            budget: 本轮计划和执行预算；未传入时使用安全默认值。

        Returns:
            全量结构化问题；只有零问题时生成 `ValidatedToolPlan`。
        """
        active_budget = budget or RunBudget()
        issues: list[ValidationIssue] = []
        if not plan.steps:
            issues.append(self._issue(ValidationIssueCode.EMPTY_PLAN, "plan has no steps"))
        if len(plan.steps) > active_budget.max_plan_steps:
            issues.append(
                self._issue(
                    ValidationIssueCode.STEP_LIMIT_EXCEEDED,
                    "plan exceeds the request step budget",
                )
            )

        step_ids = tuple(step.step_id for step in plan.steps)
        known_steps = set(step_ids)
        seen_ids: set[str] = set()
        seen_actions: set[str] = set()
        for step in plan.steps:
            if step.step_id in seen_ids:
                issues.append(
                    self._issue(
                        ValidationIssueCode.DUPLICATE_STEP,
                        "step_id must be unique",
                        step,
                    )
                )
            seen_ids.add(step.step_id)

            if step.idempotency_key in seen_actions:
                issues.append(
                    self._issue(
                        ValidationIssueCode.DUPLICATE_ACTION,
                        "same read action appears more than once",
                        step,
                    )
                )
            seen_actions.add(step.idempotency_key)

            if step.tool_name not in permissions.allowed_tools:
                issues.append(
                    self._issue(
                        ValidationIssueCode.TOOL_NOT_ALLOWED,
                        "tool is outside the permission snapshot",
                        step,
                    )
                )
            else:
                policy = permissions.require(step.tool_name)
                if policy.side_effect is not ToolSideEffect.READ:
                    issues.append(
                        self._issue(
                            ValidationIssueCode.WRITE_TOOL_FORBIDDEN,
                            "controlled conversation accepts read-only tools only",
                            step,
                        )
                    )
                issues.extend(self._validate_arguments(step, permissions))
                issues.extend(self._validate_entity(step, plan, permissions))

            for dependency in step.depends_on:
                if dependency not in known_steps:
                    issues.append(
                        self._issue(
                            ValidationIssueCode.UNKNOWN_DEPENDENCY,
                            "step dependency does not exist",
                            step,
                        )
                    )

        if self._contains_cycle(plan):
            issues.append(
                self._issue(
                    ValidationIssueCode.CYCLIC_DEPENDENCY,
                    "plan dependencies contain a cycle",
                )
            )

        covered = {
            (step.evidence_dimension, step.symbol or None)
            for step in plan.steps
        }
        for requirement in plan.requirements:
            key = (requirement.dimension, requirement.entity_symbol)
            dimension_covered = any(
                dimension is requirement.dimension for dimension, _ in covered
            )
            if requirement.required and (
                key not in covered
                if requirement.entity_symbol is not None
                else not dimension_covered
            ):
                issues.append(
                    self._issue(
                        ValidationIssueCode.MISSING_REQUIRED_EVIDENCE,
                        "required evidence dimension is not covered",
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
                permissions=permissions,
                execution_layers=self._execution_layers(plan),
            ),
        )

    def _validate_arguments(
        self,
        step: ToolPlanStep,
        permissions: ToolPermissionSnapshot,
    ) -> list[ValidationIssue]:
        policy = permissions.require(step.tool_name)
        specs = {item.name: item for item in policy.input_fields}
        arguments = {item.name: item.value for item in step.arguments}
        issues: list[ValidationIssue] = []
        if len(arguments) != len(step.arguments):
            issues.append(
                self._issue(
                    ValidationIssueCode.ARGUMENT_UNKNOWN,
                    "argument names must be unique",
                    step,
                )
            )
        for name in arguments:
            if name not in specs:
                issues.append(
                    self._issue(
                        ValidationIssueCode.ARGUMENT_UNKNOWN,
                        "argument is outside the tool schema",
                        step,
                    )
                )
        for spec in policy.input_fields:
            if spec.required and spec.name not in arguments:
                issues.append(
                    self._issue(
                        ValidationIssueCode.ARGUMENT_REQUIRED,
                        "required argument is missing",
                        step,
                    )
                )
                continue
            if spec.name not in arguments:
                continue
            value = arguments[spec.name]
            if not self._matches_kind(value, spec.kind):
                issues.append(
                    self._issue(
                        ValidationIssueCode.ARGUMENT_TYPE_MISMATCH,
                        "argument type does not match the tool schema",
                        step,
                    )
                )
                continue
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and (
                    (spec.minimum is not None and value < spec.minimum)
                    or (spec.maximum is not None and value > spec.maximum)
                )
            ):
                issues.append(
                    self._issue(
                        ValidationIssueCode.ARGUMENT_OUT_OF_RANGE,
                        "numeric argument is outside the allowed range",
                        step,
                    )
                )
        if not {"symbol", "query", "sector_name"} & set(arguments):
            issues.append(
                self._issue(
                    ValidationIssueCode.ARGUMENT_REQUIRED,
                    "tool action has no authoritative subject or query",
                    step,
                )
            )
        return issues

    @staticmethod
    def _matches_kind(value: object, kind: ToolArgumentKind) -> bool:
        if kind is ToolArgumentKind.STRING:
            return isinstance(value, str) and bool(value.strip())
        if kind is ToolArgumentKind.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        if kind is ToolArgumentKind.NUMBER:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if kind is ToolArgumentKind.BOOLEAN:
            return isinstance(value, bool)
        return False

    def _validate_entity(
        self,
        step: ToolPlanStep,
        plan: ToolPlan,
        permissions: ToolPermissionSnapshot,
    ) -> list[ValidationIssue]:
        if not step.symbol:
            return []
        entities = plan.entities or ((plan.entity,) if plan.entity is not None else ())
        entity = next((item for item in entities if item.symbol == step.symbol), None)
        policy = permissions.require(step.tool_name)
        if entity is None or entity.entity_type not in policy.supported_entity_types:
            return [
                self._issue(
                    ValidationIssueCode.ENTITY_MISMATCH,
                    "tool subject differs from authoritative entities or supported types",
                    step,
                )
            ]
        return []

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

    @staticmethod
    def _execution_layers(plan: ToolPlan) -> tuple[tuple[str, ...], ...]:
        by_id = {step.step_id: step for step in plan.steps}
        remaining = set(by_id)
        completed: set[str] = set()
        layers: list[tuple[str, ...]] = []
        while remaining:
            ready = tuple(
                step_id
                for step_id in sorted(remaining)
                if set(by_id[step_id].depends_on) <= completed
            )
            if not ready:
                return ()
            layers.append(ready)
            completed.update(ready)
            remaining.difference_update(ready)
        return tuple(layers)

    @staticmethod
    def _issue(
        code: ValidationIssueCode,
        message: str,
        step: ToolPlanStep | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            message=message,
            step_id=step.step_id if step is not None else None,
        )
