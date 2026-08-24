"""提供不改变实体的 M2 确定性两类路由基线。"""

from __future__ import annotations

from .contracts import ContextPacket, EntityResolutionResult, RouteDecision, RouteFamily


class DeterministicRouter:
    """把实时单股问题路由到数据链，把概念问题路由到 fallback。"""

    def route(
        self,
        packet: ContextPacket,
        entity_result: EntityResolutionResult,
    ) -> RouteDecision:
        """产生不带供应商字段的路由决定。

        Args:
            packet: 当前轮上下文。
            entity_result: 已完成的实体解析结果。

        Returns:
            可被 rewrite 阶段消费的统一路由合同。
        """
        if entity_result.entity is not None:
            return RouteDecision(
                family=RouteFamily.TUSHARE_DATA,
                analysis_mode="single_stock_snapshot",
                confidence=0.99,
                reason="explicit stock entity requires read-only market data",
            )
        is_conceptual = "ETF" in packet.current_message.upper() and "LOF" in packet.current_message.upper()
        return RouteDecision(
            family=RouteFamily.FALLBACK,
            analysis_mode="general_chat",
            confidence=0.95 if is_conceptual else 0.6,
            reason=(
                "conceptual question does not require a financial tool"
                if is_conceptual
                else "no executable financial entity was resolved"
            ),
        )
