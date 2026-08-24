"""解析显式、多实体、歧义和安全指代继承的权威实体。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import (
    ContextPacket,
    Entity,
    EntityResolutionResult,
    EntityType,
    ErrorCode,
)

_CODE_PATTERN = re.compile(
    r"(?<!\d)(?:(?P<prefix>SH|SZ)[.]?)?(?P<digits>\d{6})(?:[.](?P<suffix>SH|SZ))?(?!\d)",
    re.IGNORECASE,
)
_FOLLOW_UP_PATTERN = re.compile(r"(它|这只|这个|该股|刚才|继续|前面|那只|那个)")
_SWITCH_PATTERN = re.compile(r"(换成|别看|不要看|改看|换一个)")


@dataclass(frozen=True, slots=True)
class _CatalogEntry:
    """代码内冻结的最小离线实体目录项。"""

    entity: Entity
    aliases: tuple[str, ...]


_CATALOG = (
    _CatalogEntry(Entity("600519.SH", "贵州茅台", EntityType.STOCK), ("贵州茅台", "茅台")),
    _CatalogEntry(Entity("002594.SZ", "比亚迪", EntityType.STOCK), ("比亚迪",)),
    _CatalogEntry(Entity("300750.SZ", "宁德时代", EntityType.STOCK), ("宁德时代",)),
    _CatalogEntry(Entity("000001.SZ", "平安银行", EntityType.STOCK), ("平安银行",)),
    _CatalogEntry(Entity("601318.SH", "中国平安", EntityType.STOCK), ("中国平安",)),
    _CatalogEntry(
        Entity("518880.SH", "华安黄金ETF", EntityType.FUND),
        ("华安黄金ETF", "华安黄金 ETF"),
    ),
    _CatalogEntry(
        Entity("159937.SZ", "博时黄金ETF", EntityType.FUND),
        ("博时黄金ETF", "博时黄金 ETF"),
    ),
    _CatalogEntry(
        Entity("sector:新能源", "新能源板块", EntityType.SECTOR),
        ("新能源板块", "新能源"),
    ),
    _CatalogEntry(
        Entity("sector:半导体", "半导体板块", EntityType.SECTOR),
        ("半导体板块", "半导体"),
    ),
    _CatalogEntry(Entity("000300.SH", "沪深300", EntityType.INDEX), ("沪深300", "沪深 300")),
)
_ENTITY_BY_SYMBOL = {item.entity.symbol: item.entity for item in _CATALOG}
_PING_AN_CANDIDATES = (
    _ENTITY_BY_SYMBOL["000001.SZ"],
    _ENTITY_BY_SYMBOL["601318.SH"],
)


class AuthoritativeEntityResolver:
    """以当前轮显式实体优先，必要时才从单一历史实体安全继承。"""

    def resolve(self, packet: ContextPacket) -> EntityResolutionResult:
        """解析当前问题的权威实体集合。

        Args:
            packet: 当前轮优先、历史窗口已裁剪的上下文包。

        Returns:
            单实体、多实体、澄清候选或无实体结果；Router 不得修改该结果。
        """
        explicit = _extract_explicit_entities(packet.current_message)
        if explicit:
            return EntityResolutionResult(
                entity=explicit[0],
                candidates=explicit,
                resolved_entities=explicit,
                inherited=False,
                confidence=1.0 if _contains_exchange_code(packet.current_message) else 0.98,
            )

        compact = _compact(packet.current_message)
        if "平安" in compact:
            return _ambiguous_result(_PING_AN_CANDIDATES)

        if _is_static_fund_concept(packet.current_message):
            return EntityResolutionResult(
                entity=None,
                candidates=(),
                resolved_entities=(),
                inherited=False,
                confidence=1.0,
            )

        if _allows_entityless_routing(packet.current_message):
            return EntityResolutionResult(
                entity=None,
                candidates=(),
                resolved_entities=(),
                inherited=False,
                confidence=0.9,
            )

        if _FOLLOW_UP_PATTERN.search(packet.current_message) and not _SWITCH_PATTERN.search(
            packet.current_message
        ):
            if packet.working_entity is not None:
                return EntityResolutionResult(
                    entity=packet.working_entity,
                    candidates=(packet.working_entity,),
                    resolved_entities=(packet.working_entity,),
                    inherited=True,
                    confidence=0.9,
                )
            if len(packet.working_candidates) == 1:
                entity = packet.working_candidates[0]
                return EntityResolutionResult(
                    entity=entity,
                    candidates=(entity,),
                    resolved_entities=(entity,),
                    inherited=True,
                    confidence=0.86,
                )
            if len(packet.working_candidates) > 1:
                return _ambiguous_result(packet.working_candidates)
            inherited_candidates = _entities_from_history(packet.recent_messages)
            if len(inherited_candidates) == 1:
                entity = inherited_candidates[0]
                return EntityResolutionResult(
                    entity=entity,
                    candidates=(entity,),
                    resolved_entities=(entity,),
                    inherited=True,
                    confidence=0.82,
                )
            if len(inherited_candidates) > 1:
                return _ambiguous_result(inherited_candidates)

        return EntityResolutionResult(
            entity=None,
            candidates=(),
            resolved_entities=(),
            inherited=False,
            confidence=0.0,
            clarification="请提供明确的股票、基金、指数或板块名称/代码后再查询。",
            error_code=ErrorCode.ENTITY_REQUIRED,
        )


def _extract_explicit_entities(text: str) -> tuple[Entity, ...]:
    """按文本出现顺序提取并去重离线可验证实体。"""
    compact = _compact(text)
    positioned: list[tuple[int, Entity]] = []

    for entry in _CATALOG:
        positions = [compact.find(_compact(alias)) for alias in entry.aliases]
        positions = [position for position in positions if position >= 0]
        if positions:
            positioned.append((min(positions), entry.entity))

    for match in _CODE_PATTERN.finditer(text):
        symbol = _normalize_symbol(
            match.group("digits"),
            exchange=match.group("suffix") or match.group("prefix"),
        )
        entity = _ENTITY_BY_SYMBOL.get(
            symbol,
            Entity(symbol=symbol, name=symbol, entity_type=EntityType.STOCK),
        )
        positioned.append((match.start(), entity))

    positioned.sort(key=lambda item: item[0])
    unique: list[Entity] = []
    seen: set[str] = set()
    for _, entity in positioned:
        if entity.symbol not in seen:
            seen.add(entity.symbol)
            unique.append(entity)
    return tuple(unique)


def _entities_from_history(messages: tuple[str, ...]) -> tuple[Entity, ...]:
    """从最近窗口提取不同实体；多于一个时禁止猜测指代。"""
    ordered: list[Entity] = []
    seen: set[str] = set()
    for message in messages:
        for entity in _extract_explicit_entities(message):
            if entity.symbol not in seen:
                seen.add(entity.symbol)
                ordered.append(entity)
    return tuple(ordered)


def _ambiguous_result(candidates: tuple[Entity, ...]) -> EntityResolutionResult:
    names = " / ".join(f"{item.name}（{item.symbol}）" for item in candidates[:3])
    return EntityResolutionResult(
        entity=None,
        candidates=candidates,
        resolved_entities=(),
        inherited=False,
        confidence=0.45,
        clarification=f"你指的是 {names} 中的哪一个？",
        error_code=ErrorCode.AMBIGUOUS_ENTITY,
    )


def _normalize_symbol(digits: str, *, exchange: str | None) -> str:
    normalized_exchange = (exchange or "").upper()
    if not normalized_exchange:
        normalized_exchange = "SH" if digits.startswith(("5", "6", "9")) else "SZ"
    return f"{digits}.{normalized_exchange}"


def _contains_exchange_code(text: str) -> bool:
    return any(match.group("prefix") or match.group("suffix") for match in _CODE_PATTERN.finditer(text))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def _is_static_fund_concept(text: str) -> bool:
    compact = _compact(text)
    return "ETF" in compact and "LOF" in compact and any(
        token in compact for token in ("区别", "是什么", "概念", "原理")
    )


def _allows_entityless_routing(text: str) -> bool:
    """识别可由筛选、市场或知识路由继续处理的无单一实体问题。"""
    compact = _compact(text)
    has_universe = any(token in compact for token in ("ETF", "基金", "板块", "行业", "大盘", "市场"))
    has_task = any(
        token in compact
        for token in ("筛", "推荐", "候选", "热点", "龙头", "行情", "走势", "区别", "是什么")
    )
    return has_universe and has_task
