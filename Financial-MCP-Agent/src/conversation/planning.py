"""为 M2 单股快照生成确定性、可复现的工具计划。"""

from __future__ import annotations

from .contracts import (
    Entity,
    EvidenceDimension,
    EvidenceRequirement,
    ToolPlan,
    ToolPlanStep,
)
from .permissions import tool_for_dimension

_STEP_IDS = {
    EvidenceDimension.BASIC_PROFILE: "fetch-basic-profile",
    EvidenceDimension.MARKET_SNAPSHOT: "fetch-market-snapshot",
}


class DeterministicPlanner:
    """只描述目标、工具和证据，不执行任何外部调用。"""

    def plan(
        self,
        entity: Entity,
        dimensions: tuple[EvidenceDimension, ...],
    ) -> ToolPlan:
        """为单股证据需求创建无副作用计划。

        Args:
            entity: 已权威解析的股票实体。
            dimensions: rewrite 阶段请求的证据维度。

        Returns:
            未经校验、必须交给 PlanValidator 的工具计划。
        """
        steps = tuple(
            ToolPlanStep(
                step_id=_STEP_IDS[dimension],
                tool_name=tool_for_dimension(dimension),
                symbol=entity.symbol,
                evidence_dimension=dimension,
                required=True,
            )
            for dimension in dimensions
        )
        requirements = tuple(
            EvidenceRequirement(dimension=dimension, required=True) for dimension in dimensions
        )
        return ToolPlan(
            plan_id="plan-stock-snapshot-v1",
            entity=entity,
            steps=steps,
            requirements=requirements,
        )
