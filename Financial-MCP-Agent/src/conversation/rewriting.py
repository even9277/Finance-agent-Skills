"""把已路由问题转换为 M2 计划器输入合同。"""

from __future__ import annotations

from .contracts import (
    ContextPacket,
    EntityResolutionResult,
    EvidenceDimension,
    RewriteResult,
    RouteDecision,
    RouteFamily,
)


class DeterministicRewriter:
    """只补全证据维度，不选工具、不重猜实体。"""

    def rewrite(
        self,
        packet: ContextPacket,
        entity_result: EntityResolutionResult,
        route: RouteDecision,
    ) -> RewriteResult:
        """生成 route-specific 的确定性执行问题。

        Args:
            packet: 当前轮上下文。
            entity_result: 权威实体结果。
            route: 已冻结的顶层路由。

        Returns:
            带实体和证据维度的计划器输入。
        """
        if route.family is RouteFamily.FALLBACK:
            return RewriteResult(
                effective_query=packet.current_message,
                entity=None,
                requested_dimensions=(),
            )

        entity = entity_result.entity
        if entity is None:
            return RewriteResult(
                effective_query=packet.current_message,
                entity=None,
                requested_dimensions=(),
                clarification="执行数据查询前需要明确股票实体。",
            )

        dimensions: list[EvidenceDimension] = []
        if any(keyword in packet.current_message for keyword in ("基础", "公司", "信息")):
            dimensions.append(EvidenceDimension.BASIC_PROFILE)
        if any(keyword in packet.current_message for keyword in ("行情", "近期", "最新", "现在")):
            dimensions.append(EvidenceDimension.MARKET_SNAPSHOT)
        if not dimensions:
            dimensions.append(EvidenceDimension.MARKET_SNAPSHOT)
        return RewriteResult(
            effective_query=f"查询 {entity.symbol} 的{'、'.join(item.value for item in dimensions)}",
            entity=entity,
            requested_dimensions=tuple(dict.fromkeys(dimensions)),
        )
