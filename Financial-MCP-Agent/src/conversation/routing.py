"""执行 Stage1 SOP 优先、Stage2 当前事实兜底的两阶段路由。"""

from __future__ import annotations

from .contracts import (
    ContextPacket,
    EntityResolutionResult,
    RouteDecision,
    RouteFamily,
    RouteSource,
    RouteStage1Outcome,
    SkillCatalogSnapshot,
)
from .errors import ContractViolationError
from .skill_discovery import SkillDiscovery

_CURRENT_FACT_HINTS = (
    "今天",
    "今日",
    "最近",
    "近期",
    "最新",
    "现在",
    "当前",
    "行情",
    "走势",
    "涨跌",
    "估值",
    "财报",
    "财务",
    "净值",
    "资金流",
    "基础信息",
)
_STATIC_CONCEPT_HINTS = ("区别", "是什么", "概念", "原理", "方法", "怎么理解")


class TwoStageRouter:
    """先选择高价值 SOP，再判断是否需要当前可核对金融事实。"""

    def __init__(self, snapshot: SkillCatalogSnapshot) -> None:
        self._snapshot = snapshot
        self._discovery = SkillDiscovery(snapshot)

    def route(
        self,
        packet: ContextPacket,
        entity_result: EntityResolutionResult,
        *,
        explicit_skill: str | None = None,
    ) -> RouteDecision:
        """产生不包含实体副本和供应商字段的最终路由。

        Args:
            packet: 当前轮上下文。
            entity_result: 上游权威实体结果，只读使用。
            explicit_skill: 用户在请求边界显式选择的 Skill 名。

        Returns:
            带 Stage1/Stage2 来源、置信度和确认语义的路由合同。
        """
        if explicit_skill:
            try:
                descriptor = self._snapshot.require(explicit_skill)
            except ContractViolationError:
                return RouteDecision(
                    family=RouteFamily.FALLBACK,
                    analysis_mode="general_chat",
                    confidence=0.0,
                    reason="explicit skill is not present in the frozen snapshot",
                    route_source=RouteSource.USER_EXPLICIT,
                )
            return RouteDecision(
                family=RouteFamily.FINANCIAL_SOP,
                analysis_mode=descriptor.name.replace("-", "_"),
                confidence=1.0,
                reason="user selected a skill from the frozen snapshot",
                skill_name=descriptor.name,
                route_source=RouteSource.USER_EXPLICIT,
                stage1_outcome=RouteStage1Outcome.HIT_HIGH,
                shortlist=(descriptor.name,),
                requires_current_facts=True,
            )

        entities = entity_result.resolved_entities
        if not entities and entity_result.entity is not None:
            entities = (entity_result.entity,)
        stage1 = self._discovery.discover(packet.current_message, entities=entities)
        if stage1.outcome is not RouteStage1Outcome.MISS and stage1.skill_name:
            low_confidence = stage1.outcome is RouteStage1Outcome.HIT_LOW
            return RouteDecision(
                family=RouteFamily.FINANCIAL_SOP,
                analysis_mode=stage1.skill_name.replace("-", "_"),
                confidence=stage1.confidence,
                reason=stage1.reason,
                skill_name=stage1.skill_name,
                requires_confirmation=low_confidence,
                route_source=(RouteSource.STAGE1_LOW if low_confidence else RouteSource.STAGE1_HIGH),
                stage1_outcome=stage1.outcome,
                shortlist=stage1.shortlist,
                requires_current_facts=True,
            )

        return self._route_stage2(packet, entity_result, stage1.shortlist)

    @staticmethod
    def _route_stage2(
        packet: ContextPacket,
        entity_result: EntityResolutionResult,
        shortlist: tuple[str, ...],
    ) -> RouteDecision:
        text = packet.current_message
        has_current_fact_hint = any(token.lower() in text.lower() for token in _CURRENT_FACT_HINTS)
        is_static_concept = any(token in text for token in _STATIC_CONCEPT_HINTS)
        if is_static_concept and not has_current_fact_hint:
            return RouteDecision(
                family=RouteFamily.FALLBACK,
                analysis_mode="general_chat",
                confidence=0.96,
                reason="static explanation does not require current financial facts",
                route_source=RouteSource.STAGE2,
                shortlist=shortlist,
            )

        has_entity = entity_result.entity is not None or bool(entity_result.resolved_entities)
        if has_current_fact_hint or has_entity:
            dimensions = _infer_fact_dimensions(text)
            return RouteDecision(
                family=RouteFamily.TUSHARE_DATA,
                analysis_mode=_infer_analysis_mode(text),
                confidence=0.9 if has_current_fact_hint else 0.82,
                reason="answer requires current or entity-specific financial facts",
                route_source=RouteSource.STAGE2,
                shortlist=shortlist,
                requires_current_facts=True,
                fact_dimensions=dimensions,
            )

        return RouteDecision(
            family=RouteFamily.FALLBACK,
            analysis_mode="general_chat",
            confidence=0.7,
            reason="no stable SOP or current-fact requirement matched",
            route_source=RouteSource.STAGE2,
            shortlist=shortlist,
        )


def _infer_fact_dimensions(text: str) -> tuple[str, ...]:
    dimensions: list[str] = []
    if any(token in text for token in ("基础", "公司", "信息")):
        dimensions.append("basic_profile")
    if any(token in text for token in ("行情", "走势", "涨", "跌", "最近", "近期", "现在")):
        dimensions.append("market_snapshot")
    if any(token.lower() in text.lower() for token in ("估值", "财报", "财务", "PE", "PB")):
        dimensions.append("fundamental_or_valuation")
    if any(token.lower() in text.lower() for token in ("基金", "ETF", "净值")):
        dimensions.append("fund_nav_or_market")
    if any(token in text for token in ("板块", "行业", "概念")):
        dimensions.append("sector_snapshot")
    return tuple(dict.fromkeys(dimensions or ["current_financial_facts"]))


def _infer_analysis_mode(text: str) -> str:
    if any(token in text for token in ("板块", "行业", "概念")):
        return "sector_market"
    if any(token.lower() in text.lower() for token in ("基金", "ETF", "LOF")):
        return "fund_data"
    return "single_stock_snapshot"
