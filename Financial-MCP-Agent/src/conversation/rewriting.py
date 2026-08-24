"""按最终路由生成三种互斥、可校验的问题改写合同。"""

from __future__ import annotations

from .constraints import ConstraintExtractor
from .contracts import (
    ConstraintSet,
    ContextPacket,
    Entity,
    EntityResolutionResult,
    EntityType,
    EvidenceDimension,
    FallbackRewriteResult,
    RewriteResult,
    ReplyPreference,
    RouteDecision,
    RouteFamily,
    SkillCatalogSnapshot,
    SopRewriteResult,
    TimeScope,
    TushareRewriteResult,
)
from .errors import ContractViolationError
from .preferences import ReplyPreferenceExtractor

_SOP_DATA_REQUIREMENTS = {
    "fund-compare": ("fund_basic", "fund_nav_or_market"),
    "etf-screen": ("fund_basic", "fund_nav_or_market"),
    "market-move-explain": ("market_snapshot", "index_or_sector_context"),
    "sector-hotspot-brief": ("sector_snapshot", "sector_constituents"),
    "stock-first-pass": ("stock_basic", "market_snapshot", "financial_indicator"),
}


class RouteAwareRewriter:
    """保持权威实体与路由不变，只补全执行问题、约束和表达偏好。"""

    def __init__(self, snapshot: SkillCatalogSnapshot) -> None:
        self._snapshot = snapshot
        self._constraints = ConstraintExtractor()
        self._preferences = ReplyPreferenceExtractor()

    def rewrite(
        self,
        packet: ContextPacket,
        entity_result: EntityResolutionResult,
        route: RouteDecision,
    ) -> RewriteResult:
        """根据 route 判别字段返回对应 Rewrite 合同。

        Args:
            packet: 当前轮最小上下文。
            entity_result: 不可由本阶段修改的权威实体结果。
            route: 两阶段路由的最终决定。

        Returns:
            SOP、Tushare 或 Fallback 三类互斥合同之一。
        """
        entities = entity_result.resolved_entities
        if not entities and entity_result.entity is not None:
            entities = (entity_result.entity,)
        constraints = self._constraints.extract(packet.current_message)
        preference = self._preferences.extract(packet.current_message)
        time_scope = _infer_time_scope(packet.current_message)

        if route.family is RouteFamily.FINANCIAL_SOP:
            return self._rewrite_sop(
                packet,
                entities,
                route,
                constraints=constraints,
                preference=preference,
                time_scope=time_scope,
            )
        if route.family is RouteFamily.TUSHARE_DATA:
            data_requirements = route.fact_dimensions or _infer_data_requirements(
                packet.current_message
            )
            return TushareRewriteResult(
                effective_query=_effective_query(packet.current_message, entities, data_requirements),
                entity=entity_result.entity,
                entities=entities,
                requested_dimensions=_m2_dimensions(data_requirements),
                data_requirements=data_requirements,
                constraints=constraints,
                reply_preference=preference,
                time_scope=time_scope,
            )
        return FallbackRewriteResult(
            effective_query=packet.current_message.strip(),
            entity=entity_result.entity,
            entities=entities,
            requested_dimensions=(),
            constraints=constraints,
            reply_preference=preference,
            time_scope=time_scope,
        )

    def _rewrite_sop(
        self,
        packet: ContextPacket,
        entities: tuple[Entity, ...],
        route: RouteDecision,
        *,
        constraints: ConstraintSet,
        preference: ReplyPreference,
        time_scope: TimeScope,
    ) -> SopRewriteResult:
        skill_name = route.skill_name
        if not skill_name:
            return _invalid_sop(
                packet.current_message,
                entities,
                constraints,
                preference,
                time_scope,
                mismatch="financial_sop_skill_missing",
                question="当前专业任务缺少明确 Skill，请重新描述希望完成的分析。",
            )
        try:
            self._snapshot.require(skill_name)
        except ContractViolationError:
            return _invalid_sop(
                packet.current_message,
                entities,
                constraints,
                preference,
                time_scope,
                mismatch="skill_not_in_snapshot",
                question="当前选择的 Skill 不在本轮能力快照中，请重新选择。",
            )

        conflict, question = _validate_sop_subjects(skill_name, entities, packet.current_message)
        requirements = _requirements_for_sop(skill_name, entities)
        return SopRewriteResult(
            effective_query=_effective_query(packet.current_message, entities, requirements),
            entity=entities[0] if entities else None,
            entities=entities,
            requested_dimensions=_m2_dimensions(requirements),
            skill_name=skill_name,
            data_requirements=requirements,
            constraints=constraints,
            reply_preference=preference,
            time_scope=time_scope,
            needs_clarification=bool(conflict),
            clarification_question=question,
            entity_conflict=conflict,
        )


def _invalid_sop(
    query: str,
    entities: tuple[Entity, ...],
    constraints: ConstraintSet,
    preference: ReplyPreference,
    time_scope: TimeScope,
    *,
    mismatch: str,
    question: str,
) -> SopRewriteResult:
    return SopRewriteResult(
        effective_query=query.strip(),
        entity=entities[0] if entities else None,
        entities=entities,
        requested_dimensions=(),
        skill_name=None,
        data_requirements=(),
        constraints=constraints,
        reply_preference=preference,
        time_scope=time_scope,
        needs_clarification=True,
        clarification_question=question,
        route_mismatch=mismatch,
    )


def _validate_sop_subjects(
    skill_name: str,
    entities: tuple[Entity, ...],
    query: str,
) -> tuple[str, str]:
    if skill_name == "fund-compare":
        funds = tuple(item for item in entities if item.entity_type is EntityType.FUND)
        if len(funds) < 2:
            return (
                "fund_compare_requires_two_entities",
                "请至少告诉我两只明确的基金或 ETF 名称/代码，我再继续比较。",
            )
    if skill_name == "stock-first-pass":
        stocks = tuple(item for item in entities if item.entity_type is EntityType.STOCK)
        if len(stocks) != 1 or len(entities) != 1:
            return (
                "stock_first_pass_requires_one_stock",
                "这个 Skill 一次只分析一只股票，请提供一个明确股票名称或代码。",
            )
    if skill_name in {"market-move-explain", "sector-hotspot-brief"} and not entities:
        if not any(token in query for token in ("板块", "行业", "概念", "指数", "ETF")):
            return ("market_subject_missing", "请补充需要分析的股票、基金、指数或板块。")
    return ("", "")


def _requirements_for_sop(skill_name: str, entities: tuple[Entity, ...]) -> tuple[str, ...]:
    requirements = _SOP_DATA_REQUIREMENTS.get(skill_name, ())
    if skill_name == "market-move-explain" and any(
        item.entity_type is EntityType.SECTOR for item in entities
    ):
        return ("sector_snapshot",)
    return requirements


def _infer_data_requirements(text: str) -> tuple[str, ...]:
    requirements: list[str] = []
    if any(token in text for token in ("基础", "公司", "信息")):
        requirements.append("basic_profile")
    if any(token in text for token in ("行情", "走势", "涨", "跌", "最近", "近期", "现在")):
        requirements.append("market_snapshot")
    if any(token.lower() in text.lower() for token in ("估值", "财报", "财务", "PE", "PB")):
        requirements.append("fundamental_or_valuation")
    if any(token in text for token in ("板块", "行业", "概念")):
        requirements.append("sector_snapshot")
    return tuple(dict.fromkeys(requirements or ["current_financial_facts"]))


def _m2_dimensions(requirements: tuple[str, ...]) -> tuple[EvidenceDimension, ...]:
    dimensions: list[EvidenceDimension] = []
    if any(item in requirements for item in ("basic_profile", "stock_basic")):
        dimensions.append(EvidenceDimension.BASIC_PROFILE)
    if any(item in requirements for item in ("market_snapshot", "stock_market")):
        dimensions.append(EvidenceDimension.MARKET_SNAPSHOT)
    return tuple(dimensions)


def _infer_time_scope(text: str) -> TimeScope:
    if any(token in text for token in ("今天", "今日", "现在", "当前", "最新")):
        return TimeScope.LATEST_TRADING_DAY
    if any(token in text for token in ("最近", "近期", "近5日", "近五日")):
        return TimeScope.RECENT_5_TRADING_DAYS
    return TimeScope.UNSPECIFIED


def _effective_query(
    original: str,
    entities: tuple[Entity, ...],
    requirements: tuple[str, ...],
) -> str:
    subjects = ",".join(item.symbol for item in entities) or "unresolved"
    dimensions = ",".join(requirements) or "none"
    return f"subjects={subjects}; requirements={dimensions}; question={original.strip()}"
