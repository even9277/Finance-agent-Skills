"""只针对缺失证据维度生成一次有界、去重的补证计划。"""

from __future__ import annotations

import hashlib

from .contracts import (
    Entity,
    EvidenceRequirement,
    ReplanResult,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
    VerificationResult,
)
from .planning import build_tool_arguments, tool_action_fingerprint
from .tool_governance import ToolGovernanceCatalog


class BoundedEvidenceReplanner:
    """在原权限快照内用未尝试的备用只读工具补齐明确缺口。"""

    def __init__(self, *, catalog: ToolGovernanceCatalog | None = None) -> None:
        self._catalog = catalog or ToolGovernanceCatalog.default()

    def replan(
        self,
        *,
        root_plan: ToolPlan,
        permissions: ToolPermissionSnapshot,
        verification: VerificationResult,
        attempt: int,
        attempted_fingerprints: frozenset[str],
    ) -> ReplanResult:
        """为缺失 requirement 选择不同且已授权的工具动作。

        Args:
            root_plan: 最初通过校验的根计划，提供目标、实体和 Trace。
            permissions: 根计划使用的同一冻结权限快照。
            verification: 当前验收结果，只允许补其明确缺口。
            attempt: 从 1 开始的补证轮次。
            attempted_fingerprints: 本轮已经执行或计划过的动作指纹。

        Returns:
            补证 ToolPlan；没有安全新动作时返回空计划和稳定原因。
        """
        if attempt < 1:
            return ReplanResult(plan=None, reason="invalid_replan_attempt", attempt=attempt)
        entity_by_symbol = {item.symbol: item for item in root_plan.entities}
        if root_plan.entity is not None:
            entity_by_symbol.setdefault(root_plan.entity.symbol, root_plan.entity)
        steps: list[ToolPlanStep] = []
        added: list[EvidenceRequirement] = []
        seen = set(attempted_fingerprints)
        for requirement in verification.missing_requirements:
            entity = (
                entity_by_symbol.get(requirement.entity_symbol)
                if requirement.entity_symbol
                else None
            )
            step = self._alternative_step(
                requirement=requirement,
                entity=entity,
                root_plan=root_plan,
                permissions=permissions,
                attempt=attempt,
                index=len(steps) + 1,
                seen=seen,
            )
            if step is None:
                continue
            steps.append(step)
            added.append(requirement)
            seen.add(step.idempotency_key)
        if not steps:
            return ReplanResult(
                plan=None,
                reason="no_untried_permitted_alternative",
                attempt=attempt,
            )
        seed = "|".join((root_plan.plan_id, str(attempt), *(item.idempotency_key for item in steps)))
        return ReplanResult(
            plan=ToolPlan(
                plan_id=f"{root_plan.plan_id}-replan-{hashlib.sha256(seed.encode()).hexdigest()[:8]}",
                trace_id=root_plan.trace_id,
                route_family=root_plan.route_family,
                objective=root_plan.objective,
                entity=root_plan.entity,
                entities=root_plan.entities,
                steps=tuple(steps),
                requirements=tuple(added),
            ),
            reason="missing_requirements_have_safe_alternatives",
            attempt=attempt,
            added_requirements=tuple(added),
        )

    def _alternative_step(
        self,
        *,
        requirement: EvidenceRequirement,
        entity: Entity | None,
        root_plan: ToolPlan,
        permissions: ToolPermissionSnapshot,
        attempt: int,
        index: int,
        seen: set[str],
    ) -> ToolPlanStep | None:
        for policy in permissions.permissions:
            if policy.evidence_dimension is not requirement.dimension:
                continue
            if entity is not None and entity.entity_type not in policy.supported_entity_types:
                continue
            arguments = build_tool_arguments(
                tool_name=policy.tool_name,
                entity=entity,
                query=root_plan.objective,
                catalog=self._catalog,
            )
            fingerprint = tool_action_fingerprint(policy.tool_name, arguments)
            if fingerprint in seen:
                continue
            return ToolPlanStep(
                step_id=f"r{attempt}-s{index}-{policy.tool_name}",
                tool_name=policy.tool_name,
                symbol=entity.symbol if entity is not None else "",
                evidence_dimension=requirement.dimension,
                required=requirement.required,
                arguments=arguments,
                idempotency_key=fingerprint,
            )
        return None
