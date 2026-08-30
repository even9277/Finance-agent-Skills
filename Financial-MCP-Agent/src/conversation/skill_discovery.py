"""基于冻结 routing view 执行确定性检索和可选 typed rerank。"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import re

from .contracts import (
    Entity,
    EntityType,
    RouteConfidenceBand,
    RouteStage1Outcome,
    SkillCatalogSnapshot,
    SkillMatch,
    SkillRerankRequest,
    SkillRouteCandidate,
    SkillRoutingDescriptor,
)
from .ports import SkillRerankerPort

logger = logging.getLogger(__name__)

_COMPARE_HINTS = ("对比", "比较", "PK", "VS", "哪个好", "哪个适合", "适合", "二选一", "怎么选")
_SCREEN_HINTS = ("筛选", "筛", "推荐", "候选", "配置", "选几个", "找几只", "shortlist")
_MOVE_HINTS = ("为什么涨", "为什么跌", "为什么突然", "异动", "拉升", "跳水", "大涨", "大跌")
_HOTSPOT_HINTS = (
    "热点",
    "热度",
    "强势",
    "强不强",
    "弱势",
    "龙头",
    "轮动",
    "还能追",
    "继续看",
    "板块强",
)
_FIRST_PASS_HINTS = (
    "能买吗",
    "还能买吗",
    "值不值得",
    "基本面",
    "快速看",
    "财报怎么看",
    "核心风险",
    "继续跟踪",
)
_GENERIC_ANALYSIS_HINTS = ("分析一下", "分析", "怎么看", "研判一下")
_FUND_TOKEN = re.compile(r"(ETF|基金|LOF|QDII)", re.IGNORECASE)
_STOCK_CODE = re.compile(r"(?<!\d)\d{6}(?:\.(?:SH|SZ))?(?!\d)", re.IGNORECASE)
_TEXT_TOKEN = re.compile(r"[A-Z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SkillRoutingPolicy:
    """集中保存路由分层阈值和候选预算。"""

    high_threshold: float = 0.82
    mid_threshold: float = 0.48
    high_min_margin: float = 0.12
    default_top_k: int = 3

    def __post_init__(self) -> None:
        if not 0.0 < self.mid_threshold < self.high_threshold <= 1.0:
            raise ValueError("routing thresholds must satisfy 0 < mid < high <= 1")
        if not 0.0 <= self.high_min_margin <= 1.0:
            raise ValueError("high_min_margin must be between 0 and 1")
        if not 1 <= self.default_top_k <= 5:
            raise ValueError("default_top_k must be between 1 and 5")


class SkillDiscovery:
    """只消费 routing view，以默认离线策略检索五类已登记 SOP。"""

    def __init__(
        self,
        snapshot: SkillCatalogSnapshot,
        *,
        reranker: SkillRerankerPort | None = None,
        policy: SkillRoutingPolicy | None = None,
        top_k: int | None = None,
    ) -> None:
        self._routing_view = snapshot.routing_view()
        self._reranker = reranker
        self._policy = policy or SkillRoutingPolicy()
        self._top_k = top_k or self._policy.default_top_k
        if not 1 <= self._top_k <= 5:
            raise ValueError("top_k must be between 1 and 5")

    def discover(self, query: str, *, entities: tuple[Entity, ...]) -> SkillMatch:
        """检索候选并根据集中阈值返回高置信、确认或未命中。

        Args:
            query: 当前轮有效问题；可选 rerank 只接收该字段，不接收会话历史。
            entities: 实体阶段已经确认的实体，只用于类型兼容加权。

        Returns:
            带候选分数、版本和解释的稳定路由结果。
        """
        text = (query or "").strip()
        candidates = tuple(
            sorted(
                (self._score_candidate(text, item, entities) for item in self._routing_view),
                key=lambda item: (-item.score, item.skill_name),
            )[: self._top_k]
        )
        rerank_fallback = False
        if self._reranker is not None and text and candidates:
            try:
                candidates = self._apply_rerank(text, candidates)
            except Exception as exc:
                # Provider 失败只保留低基数错误类型，不记录原始 query 或候选文本。
                logger.warning("skill_rerank_fallback error_type=%s", type(exc).__name__)
                rerank_fallback = True

        return self._classify(candidates, rerank_fallback=rerank_fallback)

    def _score_candidate(
        self,
        query: str,
        descriptor: SkillRoutingDescriptor,
        entities: tuple[Entity, ...],
    ) -> SkillRouteCandidate:
        positive = _best_similarity(query, descriptor.positive_examples)
        boundary = _best_similarity(query, descriptor.when_to_use)
        negative = max(
            _best_similarity(query, descriptor.negative_examples),
            _best_similarity(query, descriptor.when_not_to_use),
        )
        rule_score, rule_reason = _rule_score(descriptor.name, query, entities)
        metadata_score = min(0.76, 0.08 + positive * 0.48 + boundary * 0.24)
        score = max(rule_score, metadata_score)
        reasons: list[str] = []
        if rule_reason:
            reasons.append(rule_reason)
        if positive >= 0.30:
            reasons.append(f"positive_example={positive:.2f}")
        if boundary >= 0.25:
            reasons.append(f"when_to_use={boundary:.2f}")

        if entities:
            actual_types = {_route_entity_type(item.entity_type) for item in entities}
            supported = set(descriptor.supported_entity_types)
            if actual_types & supported:
                score = min(1.0, score + 0.04)
                reasons.append("entity_type_compatible")
            elif descriptor.name == "etf-screen" and _FUND_TOKEN.search(query):
                # 主题/行业实体在 ETF 筛选中是过滤条件，不是待执行的基金主体。
                reasons.append("entity_used_as_screening_scope")
            elif supported:
                score = max(0.0, score - 0.32)
                reasons.append("entity_type_incompatible")

        if negative >= 0.66:
            score = min(score, 0.24)
            reasons.append(f"negative_boundary={negative:.2f}")
        if descriptor.name == "market-move-explain" and _is_quantity_only_move(query):
            score = min(score, 0.24)
            reasons.append("quantity_only_move")

        return SkillRouteCandidate(
            skill_name=descriptor.name,
            version=descriptor.version,
            description=descriptor.description,
            score=round(max(0.0, min(score, 1.0)), 4),
            reasons=tuple(reasons or ("metadata_overlap_below_threshold",)),
            when_to_use=descriptor.when_to_use,
            when_not_to_use=descriptor.when_not_to_use,
            positive_examples=descriptor.positive_examples,
            negative_examples=descriptor.negative_examples,
            supported_entity_types=descriptor.supported_entity_types,
        )

    def _apply_rerank(
        self,
        query: str,
        candidates: tuple[SkillRouteCandidate, ...],
    ) -> tuple[SkillRouteCandidate, ...]:
        reranker = self._reranker
        if reranker is None:
            raise RuntimeError("reranker is not configured")
        result = reranker.rerank(SkillRerankRequest(query=query, candidates=candidates))
        by_name = {item.skill_name: item for item in candidates}
        if {item.skill_name for item in result.scores} != set(by_name):
            raise ValueError("rerank must return every top-k candidate exactly once")
        reranked = tuple(
            replace(
                by_name[item.skill_name],
                score=item.score,
                reasons=(*by_name[item.skill_name].reasons, f"rerank={item.reason}"),
            )
            for item in result.scores
        )
        return tuple(sorted(reranked, key=lambda item: (-item.score, item.skill_name)))

    def _classify(
        self,
        candidates: tuple[SkillRouteCandidate, ...],
        *,
        rerank_fallback: bool,
    ) -> SkillMatch:
        if not candidates:
            return SkillMatch(
                skill_name=None,
                confidence=0.0,
                outcome=RouteStage1Outcome.MISS,
                shortlist=(),
                reason="no active Skill routing metadata",
            )

        best = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = best.score - second_score
        suffix = "; rerank failure fallback" if rerank_fallback else ""
        if best.score >= self._policy.high_threshold and margin >= self._policy.high_min_margin:
            return SkillMatch(
                skill_name=best.skill_name,
                confidence=best.score,
                outcome=RouteStage1Outcome.HIT_HIGH,
                shortlist=tuple(item.skill_name for item in candidates),
                reason=f"high confidence metadata route; margin={margin:.2f}{suffix}",
                confidence_band=RouteConfidenceBand.HIGH,
                candidates=candidates,
            )
        if best.score >= self._policy.mid_threshold:
            near = tuple(
                item for item in candidates if best.score - item.score <= self._policy.high_min_margin
            )
            selected = best.skill_name if len(near) == 1 else None
            return SkillMatch(
                skill_name=selected,
                confidence=best.score,
                outcome=RouteStage1Outcome.HIT_LOW,
                shortlist=tuple(item.skill_name for item in candidates),
                reason=(
                    "mid confidence metadata route requires confirmation; "
                    f"margin={margin:.2f}{suffix}"
                ),
                confidence_band=RouteConfidenceBand.MID,
                candidates=candidates,
                requires_confirmation=True,
            )
        return SkillMatch(
            skill_name=None,
            confidence=best.score,
            outcome=RouteStage1Outcome.MISS,
            shortlist=tuple(item.skill_name for item in candidates),
            reason=f"low confidence metadata route falls back; margin={margin:.2f}{suffix}",
            confidence_band=RouteConfidenceBand.LOW,
            candidates=candidates,
        )


def _rule_score(
    skill_name: str,
    text: str,
    entities: tuple[Entity, ...],
) -> tuple[float, str]:
    """应用少量稳定意图规则，metadata 继续负责边界和相邻样例。"""
    checks = {
        "fund-compare": (_is_fund_compare(text, entities), 0.94, "rule=fund_compare"),
        "market-move-explain": (_is_market_move(text), 0.94, "rule=market_move"),
        "etf-screen": (_is_etf_screen(text), 0.92, "rule=etf_screen"),
        "sector-hotspot-brief": (_is_sector_hotspot(text), 0.92, "rule=sector_hotspot"),
        "stock-first-pass": (
            _is_stock_first_pass(text, entities),
            0.92,
            "rule=stock_first_pass",
        ),
    }
    matched, score, reason = checks.get(skill_name, (False, 0.0, ""))
    if matched:
        return score, reason

    if skill_name == "stock-first-pass" and _has_stock(text, entities):
        if any(token in text for token in _GENERIC_ANALYSIS_HINTS):
            return 0.64, "rule=generic_stock_analysis"
    if any(token in text.upper() for token in ("黄金", "基金", "ETF", "产品")) and any(
        token in text for token in _GENERIC_ANALYSIS_HINTS
    ):
        if skill_name == "fund-compare":
            return 0.58, "rule=generic_fund_product"
        if skill_name == "etf-screen":
            return 0.56, "rule=generic_fund_product"
    return 0.0, ""


def _normalize(text: str) -> str:
    return "".join(_TEXT_TOKEN.findall((text or "").upper()))


def _bigrams(text: str) -> set[str]:
    normalized = _normalize(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _similarity(left: str, right: str) -> float:
    left_tokens = _bigrams(left)
    right_tokens = _bigrams(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return 2.0 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))


def _best_similarity(query: str, examples: tuple[str, ...]) -> float:
    return max((_similarity(query, example) for example in examples), default=0.0)


def _route_entity_type(entity_type: EntityType) -> str:
    return entity_type.value


def _is_fund_compare(text: str, entities: tuple[Entity, ...] = ()) -> bool:
    """识别比较意图，允许单一已解析基金进入 input-contract 澄清。"""
    fund_subject_count = sum(item.entity_type is EntityType.FUND for item in entities)
    has_fund_subject = len(_FUND_TOKEN.findall(text)) >= 2 or fund_subject_count >= 1
    return has_fund_subject and any(token in text for token in _COMPARE_HINTS)


def _is_etf_screen(text: str) -> bool:
    if _is_fund_compare(text):
        return False
    return bool(_FUND_TOKEN.search(text)) and any(token in text for token in _SCREEN_HINTS)


def _is_market_move(text: str) -> bool:
    has_object = any(
        token in text
        for token in ("股票", "个股", "ETF", "指数", "板块", "行业", "茅台", "宁德时代")
    ) or bool(_STOCK_CODE.search(text))
    return has_object and any(token in text for token in _MOVE_HINTS)


def _is_sector_hotspot(text: str) -> bool:
    return any(token in text for token in ("板块", "行业", "概念", "主题")) and any(
        token in text for token in _HOTSPOT_HINTS
    )


def _has_stock(text: str, entities: tuple[Entity, ...]) -> bool:
    return any(item.entity_type is EntityType.STOCK for item in entities) or any(
        token in text for token in ("股票", "个股", "茅台", "比亚迪", "宁德时代")
    ) or bool(_STOCK_CODE.search(text))


def _is_stock_first_pass(text: str, entities: tuple[Entity, ...]) -> bool:
    if _FUND_TOKEN.search(text) or any(token in text for token in ("板块", "行业", "概念")):
        return False
    return _has_stock(text, entities) and any(token in text for token in _FIRST_PASS_HINTS)


def _is_quantity_only_move(text: str) -> bool:
    return "多少" in text and not any(token in text for token in ("为什么", "原因", "消息", "异动"))


__all__ = ["SkillDiscovery", "SkillRoutingPolicy"]
