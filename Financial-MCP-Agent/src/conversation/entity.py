"""以确定性优先、模型后置和目录回查解析金融实体。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .contracts import (
    ContextPacket,
    Entity,
    EntityCatalogStatus,
    EntityModelRequest,
    EntityResolutionResult,
    EntityResolverPath,
    EntityType,
    ErrorCode,
)
from .errors import (
    EntityCatalogUnavailableError,
    EntityModelContractError,
    EntityModelUnavailableError,
)
from .ports import EntityCatalogPort, EntityResolutionModelPort

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
    _CatalogEntry(Entity("600519.SH", "贵州茅台", EntityType.STOCK), ("茅台",)),
    _CatalogEntry(Entity("002594.SZ", "比亚迪", EntityType.STOCK), ()),
    _CatalogEntry(Entity("300750.SZ", "宁德时代", EntityType.STOCK), ()),
    _CatalogEntry(Entity("000001.SZ", "平安银行", EntityType.STOCK), ()),
    _CatalogEntry(Entity("601318.SH", "中国平安", EntityType.STOCK), ()),
    _CatalogEntry(Entity("518880.SH", "华安黄金ETF", EntityType.FUND), ("华安黄金 ETF",)),
    _CatalogEntry(Entity("159937.SZ", "博时黄金ETF", EntityType.FUND), ("博时黄金 ETF",)),
    _CatalogEntry(Entity("sector:新能源", "新能源板块", EntityType.SECTOR), ("新能源",)),
    _CatalogEntry(Entity("sector:半导体", "半导体板块", EntityType.SECTOR), ("半导体",)),
    _CatalogEntry(Entity("000300.SH", "沪深300", EntityType.INDEX), ("沪深 300",)),
)
_ENTRY_BY_SYMBOL = {item.entity.symbol: item for item in _CATALOG}
_ENTITY_BY_SYMBOL = {symbol: item.entity for symbol, item in _ENTRY_BY_SYMBOL.items()}
_PING_AN_CANDIDATES = (_ENTITY_BY_SYMBOL["000001.SZ"], _ENTITY_BY_SYMBOL["601318.SH"])


class AuthoritativeEntityResolver:
    """解析唯一 canonical 实体，并把模型候选约束在权威目录内。

    Args:
        model: 可选长尾候选模型；未注入时确定性未命中会要求澄清。
        catalog: 可选外部权威目录；本地冻结目录始终优先且离线可用。
        fuzzy_threshold: 本地别名模糊匹配的最低相似度。
        fuzzy_margin: 第一与第二候选必须达到的最小分差。
    """

    def __init__(
        self,
        *,
        model: EntityResolutionModelPort | None = None,
        catalog: EntityCatalogPort | None = None,
        fuzzy_threshold: float = 0.75,
        fuzzy_margin: float = 0.08,
    ) -> None:
        if not 0.0 < fuzzy_threshold <= 1.0:
            raise ValueError("fuzzy_threshold must be within (0, 1]")
        if not 0.0 <= fuzzy_margin <= 1.0:
            raise ValueError("fuzzy_margin must be within [0, 1]")
        self._model = model
        self._catalog = catalog
        self._fuzzy_threshold = fuzzy_threshold
        self._fuzzy_margin = fuzzy_margin

    async def resolve(self, packet: ContextPacket) -> EntityResolutionResult:
        """按显式代码、名称、别名、模糊、继承和模型兜底顺序解析。

        Args:
            packet: 当前轮优先、历史窗口已裁剪的上下文包。

        Returns:
            单实体、多实体、澄清或稳定失败结果；Router 不得修改该结果。

        Notes:
            模型只提出候选。非本地候选必须由外部目录确认名称、代码和类型，
            目录不可用或语义不一致时采用 fail-closed，不信任模型输出。
        """
        text = packet.current_message
        named_entities, named_path = _extract_named_entities(text)
        code_symbols = _extract_code_symbols(text)

        # 显式代码优先，但同一轮同时出现的名称必须与代码集合一致。
        if code_symbols:
            code_result = await self._resolve_explicit_codes(code_symbols)
            if code_result.error_code is not None:
                return code_result
            code_entities = code_result.resolved_entities
            code_set = {item.symbol for item in code_entities}
            if named_entities and any(item.symbol not in code_set for item in named_entities):
                return _failure_result(
                    path=EntityResolverPath.CONFLICT,
                    error_code=ErrorCode.ENTITY_CONFLICT,
                    clarification="名称与证券代码不一致，请确认要查询的标的。",
                )
            return code_result

        if named_entities:
            return _resolved_result(
                named_entities,
                path=named_path,
                confidence=1.0 if named_path is EntityResolverPath.EXACT_NAME else 0.98,
                catalog_status=EntityCatalogStatus.LOCAL,
            )

        compact = _compact(text)
        if "平安" in compact:
            return _ambiguous_result(_PING_AN_CANDIDATES, path=EntityResolverPath.AMBIGUOUS)

        if _is_static_fund_concept(text) or _allows_entityless_routing(text):
            return EntityResolutionResult(
                entity=None,
                candidates=(),
                resolved_entities=(),
                inherited=False,
                confidence=1.0 if _is_static_fund_concept(text) else 0.9,
                resolver_path=EntityResolverPath.ENTITYLESS,
            )

        inherited = _inherit_entity(packet)
        if inherited is not None:
            return inherited

        fuzzy_candidates = _fuzzy_candidates(
            text,
            threshold=self._fuzzy_threshold,
            margin=self._fuzzy_margin,
        )
        if len(fuzzy_candidates) == 1:
            return _resolved_result(
                fuzzy_candidates,
                path=EntityResolverPath.FUZZY,
                confidence=self._fuzzy_threshold,
                catalog_status=EntityCatalogStatus.LOCAL,
            )
        if len(fuzzy_candidates) > 1:
            return _ambiguous_result(fuzzy_candidates, path=EntityResolverPath.AMBIGUOUS)

        if self._model is None:
            return _failure_result(
                path=EntityResolverPath.UNRESOLVED,
                error_code=ErrorCode.ENTITY_REQUIRED,
                clarification="请提供明确的股票、基金、指数或板块名称/代码后再查询。",
            )
        return await self._resolve_with_model(text)

    async def _resolve_explicit_codes(
        self,
        symbols: tuple[str, ...],
    ) -> EntityResolutionResult:
        """逐个回查显式代码；任何无效代码都会阻断整组结果。"""
        entities: list[Entity] = []
        used_external_catalog = False
        for symbol in symbols:
            local = _ENTITY_BY_SYMBOL.get(symbol)
            if local is not None:
                entities.append(local)
                continue
            if self._catalog is None:
                return _catalog_failure(EntityResolverPath.EXPLICIT_CODE, unavailable=False)
            try:
                catalog_entity = await self._catalog.lookup(symbol)
            except EntityCatalogUnavailableError:
                return _catalog_failure(EntityResolverPath.EXPLICIT_CODE, unavailable=True)
            if catalog_entity is None:
                return _catalog_failure(EntityResolverPath.EXPLICIT_CODE, unavailable=False)
            entities.append(catalog_entity)
            used_external_catalog = True
        return _resolved_result(
            tuple(entities),
            path=EntityResolverPath.EXPLICIT_CODE,
            confidence=1.0,
            catalog_status=(
                EntityCatalogStatus.VERIFIED if used_external_catalog else EntityCatalogStatus.LOCAL
            ),
        )

    async def _resolve_with_model(self, text: str) -> EntityResolutionResult:
        """调用一次逻辑模型兜底并对每个候选执行目录语义回查。"""
        assert self._model is not None
        try:
            decision = await self._model.resolve(EntityModelRequest(message=text))
        except EntityModelContractError as exc:
            return _failure_result(
                path=EntityResolverPath.MODEL_FALLBACK,
                error_code=ErrorCode.ENTITY_MODEL_CONTRACT_INVALID,
                clarification="实体解析结果格式异常，请换一种方式描述标的。",
                model_calls=exc.model_calls,
                repair_count=exc.repair_count,
            )
        except EntityModelUnavailableError as exc:
            return _failure_result(
                path=EntityResolverPath.MODEL_FALLBACK,
                error_code=ErrorCode.ENTITY_MODEL_UNAVAILABLE,
                clarification="实体解析服务暂时不可用，请稍后重试。",
                model_calls=exc.model_calls,
                repair_count=exc.repair_count,
            )

        model_calls = int(decision.model_calls)
        repair_count = int(decision.repair_count)
        grounded: list[Entity] = []
        used_external_catalog = False
        for candidate in decision.candidates:
            local = _ENTITY_BY_SYMBOL.get(candidate.symbol)
            if local is not None:
                if _candidate_matches_catalog(candidate, local):
                    grounded.append(local)
                continue
            if self._catalog is None:
                continue
            try:
                catalog_entity = await self._catalog.lookup(candidate.symbol)
            except EntityCatalogUnavailableError:
                return _failure_result(
                    path=EntityResolverPath.MODEL_FALLBACK,
                    error_code=ErrorCode.ENTITY_CATALOG_UNAVAILABLE,
                    clarification="证券目录暂时不可用，无法确认模型候选。",
                    model_calls=model_calls,
                    repair_count=repair_count,
                    catalog_status=EntityCatalogStatus.UNAVAILABLE,
                )
            if catalog_entity is not None and _candidate_matches_catalog(candidate, catalog_entity):
                grounded.append(catalog_entity)
                used_external_catalog = True

        unique = _deduplicate(tuple(grounded))
        if not unique:
            return _failure_result(
                path=EntityResolverPath.MODEL_FALLBACK,
                error_code=ErrorCode.ENTITY_NOT_FOUND,
                clarification="未能在权威目录中确认该标的，请提供证券代码或完整名称。",
                model_calls=model_calls,
                repair_count=repair_count,
                catalog_status=EntityCatalogStatus.NOT_FOUND,
            )
        catalog_status = (
            EntityCatalogStatus.VERIFIED if used_external_catalog else EntityCatalogStatus.LOCAL
        )
        if len(unique) > 1:
            return _ambiguous_result(
                unique,
                path=EntityResolverPath.MODEL_FALLBACK,
                model_calls=model_calls,
                repair_count=repair_count,
                catalog_status=catalog_status,
            )
        return _resolved_result(
            unique,
            path=EntityResolverPath.MODEL_FALLBACK,
            confidence=float(decision.confidence),
            model_calls=model_calls,
            repair_count=repair_count,
            catalog_status=catalog_status,
        )


def _extract_named_entities(text: str) -> tuple[tuple[Entity, ...], EntityResolverPath]:
    """按文本出现顺序提取本地精确名称或别名。"""
    compact = _compact(text)
    positioned: list[tuple[int, Entity, EntityResolverPath]] = []
    for entry in _CATALOG:
        canonical_position = compact.find(_compact(entry.entity.name))
        if canonical_position >= 0:
            positioned.append((canonical_position, entry.entity, EntityResolverPath.EXACT_NAME))
            continue
        alias_positions = [compact.find(_compact(alias)) for alias in entry.aliases]
        alias_positions = [position for position in alias_positions if position >= 0]
        if alias_positions:
            positioned.append((min(alias_positions), entry.entity, EntityResolverPath.ALIAS))
    positioned.sort(key=lambda item: item[0])
    entities = _deduplicate(tuple(item[1] for item in positioned))
    path = (
        EntityResolverPath.EXACT_NAME
        if any(item[2] is EntityResolverPath.EXACT_NAME for item in positioned)
        else EntityResolverPath.ALIAS
    )
    return entities, path


def _extract_code_symbols(text: str) -> tuple[str, ...]:
    """提取并规范化显式证券代码，保持首次出现顺序。"""
    symbols = tuple(
        _normalize_symbol(
            match.group("digits"),
            exchange=match.group("suffix") or match.group("prefix"),
        )
        for match in _CODE_PATTERN.finditer(text)
    )
    return tuple(dict.fromkeys(symbols))


def _inherit_entity(packet: ContextPacket) -> EntityResolutionResult | None:
    """仅在明确指代、无切换语义时继承单一已确认候选。"""
    if not _FOLLOW_UP_PATTERN.search(packet.current_message) or _SWITCH_PATTERN.search(
        packet.current_message
    ):
        return None
    if packet.working_entity is not None:
        candidates, confidence = (packet.working_entity,), 0.9
    elif len(packet.working_candidates) == 1:
        candidates, confidence = packet.working_candidates, 0.86
    elif len(packet.working_candidates) > 1:
        return _ambiguous_result(packet.working_candidates, path=EntityResolverPath.AMBIGUOUS)
    else:
        candidates, confidence = _entities_from_history(packet.recent_messages), 0.82
    if len(candidates) == 1:
        return _resolved_result(
            candidates,
            path=EntityResolverPath.INHERITED,
            confidence=confidence,
            inherited=True,
            catalog_status=EntityCatalogStatus.LOCAL,
        )
    if len(candidates) > 1:
        return _ambiguous_result(candidates, path=EntityResolverPath.AMBIGUOUS)
    return None


def _entities_from_history(messages: tuple[str, ...]) -> tuple[Entity, ...]:
    """从最近窗口提取本地已知实体；多于一个时禁止猜测指代。"""
    ordered: list[Entity] = []
    for message in messages:
        named, _ = _extract_named_entities(message)
        ordered.extend(named)
        ordered.extend(
            entity
            for symbol in _extract_code_symbols(message)
            if (entity := _ENTITY_BY_SYMBOL.get(symbol)) is not None
        )
    return _deduplicate(tuple(ordered))


def _fuzzy_candidates(
    text: str,
    *,
    threshold: float,
    margin: float,
) -> tuple[Entity, ...]:
    """用局部窗口计算别名相似度，并对近分候选保持歧义。"""
    compact = _compact(text)
    scores: list[tuple[float, Entity]] = []
    for entry in _CATALOG:
        mentions = (entry.entity.name, *entry.aliases)
        score = max(_mention_similarity(compact, _compact(mention)) for mention in mentions)
        scores.append((score, entry.entity))
    scores.sort(key=lambda item: item[0], reverse=True)
    if not scores or scores[0][0] < threshold:
        return ()
    top_score = scores[0][0]
    close = tuple(
        entity for score, entity in scores if score >= threshold and top_score - score < margin
    )
    return _deduplicate(close)


def _mention_similarity(text: str, mention: str) -> float:
    """计算 mention 与文本局部窗口的最大编辑相似度。"""
    if not mention or len(mention) < 3 or len(text) < 2:
        return 0.0
    if mention in text:
        return 1.0
    lengths = range(max(2, len(mention) - 1), min(len(text), len(mention) + 1) + 1)
    return max(
        (
            SequenceMatcher(None, mention, text[start : start + length]).ratio()
            for length in lengths
            for start in range(0, len(text) - length + 1)
        ),
        default=0.0,
    )


def _candidate_matches_catalog(candidate: Entity, catalog_entity: Entity) -> bool:
    """校验模型候选与目录代码、类型、名称或已知别名一致。"""
    if candidate.symbol != catalog_entity.symbol or candidate.entity_type is not catalog_entity.entity_type:
        return False
    names = {_compact(catalog_entity.name)}
    entry = _ENTRY_BY_SYMBOL.get(catalog_entity.symbol)
    if entry is not None:
        names.update(_compact(alias) for alias in entry.aliases)
    return _compact(candidate.name) in names


def _resolved_result(
    entities: tuple[Entity, ...],
    *,
    path: EntityResolverPath,
    confidence: float,
    inherited: bool = False,
    model_calls: int = 0,
    repair_count: int = 0,
    catalog_status: EntityCatalogStatus = EntityCatalogStatus.NOT_REQUIRED,
) -> EntityResolutionResult:
    """构造单一或多实体成功结果。"""
    return EntityResolutionResult(
        entity=entities[0],
        candidates=entities,
        resolved_entities=entities,
        inherited=inherited,
        confidence=confidence,
        resolver_path=path,
        model_calls=model_calls,
        repair_count=repair_count,
        catalog_status=catalog_status,
    )


def _ambiguous_result(
    candidates: tuple[Entity, ...],
    *,
    path: EntityResolverPath,
    model_calls: int = 0,
    repair_count: int = 0,
    catalog_status: EntityCatalogStatus = EntityCatalogStatus.LOCAL,
) -> EntityResolutionResult:
    """构造不选择主实体的有限候选澄清结果。"""
    names = " / ".join(f"{item.name}（{item.symbol}）" for item in candidates[:3])
    return EntityResolutionResult(
        entity=None,
        candidates=candidates,
        resolved_entities=(),
        inherited=False,
        confidence=0.45,
        clarification=f"你指的是 {names} 中的哪一个？",
        error_code=ErrorCode.AMBIGUOUS_ENTITY,
        resolver_path=path,
        model_calls=model_calls,
        repair_count=repair_count,
        catalog_status=catalog_status,
    )


def _failure_result(
    *,
    path: EntityResolverPath,
    error_code: ErrorCode,
    clarification: str,
    model_calls: int = 0,
    repair_count: int = 0,
    catalog_status: EntityCatalogStatus = EntityCatalogStatus.NOT_REQUIRED,
) -> EntityResolutionResult:
    """构造不携带不可信候选的稳定失败结果。"""
    return EntityResolutionResult(
        entity=None,
        candidates=(),
        resolved_entities=(),
        inherited=False,
        confidence=0.0,
        clarification=clarification,
        error_code=error_code,
        resolver_path=path,
        model_calls=model_calls,
        repair_count=repair_count,
        catalog_status=catalog_status,
    )


def _catalog_failure(path: EntityResolverPath, *, unavailable: bool) -> EntityResolutionResult:
    """把目录无结果或不可用映射为稳定且可恢复的失败。"""
    return _failure_result(
        path=path,
        error_code=(
            ErrorCode.ENTITY_CATALOG_UNAVAILABLE if unavailable else ErrorCode.ENTITY_NOT_FOUND
        ),
        clarification=(
            "证券目录暂时不可用，请稍后重试。"
            if unavailable
            else "未在权威目录中找到该证券代码，请检查后重试。"
        ),
        catalog_status=(
            EntityCatalogStatus.UNAVAILABLE if unavailable else EntityCatalogStatus.NOT_FOUND
        ),
    )


def _deduplicate(entities: tuple[Entity, ...]) -> tuple[Entity, ...]:
    """按 canonical symbol 去重并保持首次出现顺序。"""
    return tuple({entity.symbol: entity for entity in entities}.values())


def _normalize_symbol(digits: str, *, exchange: str | None) -> str:
    """将六位证券代码规范化为 Tushare 风格 canonical symbol。"""
    normalized_exchange = (exchange or "").upper()
    if not normalized_exchange:
        normalized_exchange = "SH" if digits.startswith(("5", "6", "9")) else "SZ"
    return f"{digits}.{normalized_exchange}"


def _compact(text: str) -> str:
    """移除空白并统一大小写，用于受控字面比较。"""
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
