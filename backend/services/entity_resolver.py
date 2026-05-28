from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_AGENT_ROOT = _PROJECT_ROOT / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.tools.chat_tushare_tools import _search_fund_candidates, resolve_sector_request
from src.tools.tushare_client import TushareClientError, get_tushare_client

logger = logging.getLogger("entity_resolver")

AssetType = Literal["stock", "fund", "sector", "index"]

_INDEX_ALIAS_MAP = {
    "上证指数": "000001.SH",
    "上证综指": "000001.SH",
    "沪深300": "000300.SH",
    "创业板指": "399006.SZ",
    "深证成指": "399001.SZ",
    "中证500": "000905.SH",
    "科创50": "000688.SH",
    "上证50": "000016.SH",
}
_FUND_HINTS = ("基金", "etf", "lof", "qdii", "联接")
_SECTOR_HINTS = ("板块", "行业", "概念", "赛道", "主题")
_FOLLOWUP_HINTS = ("它", "这只", "这个标的", "该股", "刚才", "继续", "前面那只", "那家公司")
_QUERY_FILLER_RE = re.compile(
    r"(帮我|请|麻烦|分析一下|分析|研究一下|研究|看看|看下|聊聊|说说|最近|近期|今天|今日|现在|走势|行情|基本面|财报|估值|如何|怎么样|值不值得|能买吗|可以买吗|呢)"
)
_TEXT_NOISE_RE = re.compile(r"[\s\-_()/（）【】\[\]，。！？,.!?:：；;]+")
_STOCK_SYMBOL_RE = re.compile(r"\b(?:[A-Za-z]{2}\.?)?\d{6}(?:\.(?:SH|SZ|BJ))?\b", re.IGNORECASE)
_STOCK_CATALOG_TTL_SECONDS = 6 * 60 * 60
_FUND_CATALOG_TTL_SECONDS = 6 * 60 * 60

_STOCK_CATALOG_CACHE: list[dict[str, Any]] | None = None
_STOCK_CATALOG_CACHED_AT = 0.0
_FUND_CATALOG_CACHE: list[dict[str, Any]] | None = None
_FUND_CATALOG_CACHED_AT = 0.0
_STOCK_NAME_ALIAS_MAP: dict[str, str] = {}


@dataclass(slots=True)
class EntityResolutionResult:
    display_name: str = ""
    asset_type: AssetType | None = None
    symbol: str = ""
    exchange: str = ""
    confidence: float = 0.0
    resolver_stage: str = ""
    resolver_source: str = ""
    warnings: list[str] = field(default_factory=list)
    failure_code: str = ""
    corrected_from: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.asset_type and (self.symbol or self.display_name))


def _canonicalize_symbol(raw: str | None) -> str:
    from backend.services.stock_resolver import canonicalize_symbol

    return canonicalize_symbol(raw)


def _parse_symbol_to_parts(raw: str | None) -> tuple[str, str]:
    from backend.services.stock_resolver import parse_symbol_to_parts

    return parse_symbol_to_parts(raw or "")


def _normalize_search_text(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = _TEXT_NOISE_RE.sub("", normalized)
    return normalized


def _query_tokens(query: str) -> list[str]:
    text = (query or "").strip().lower()
    if not text:
        return []
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", text)
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:12]


def _clean_query_core(text: str) -> str:
    candidate = (text or "").strip()
    candidate = _QUERY_FILLER_RE.sub("", candidate)
    candidate = candidate.strip("，。！？,.!?：:；;()（）[]【】 ")
    if "的" in candidate:
        candidate = candidate.split("的", 1)[0].strip()
    return candidate.strip()


def _extract_symbol_candidates(query: str) -> list[str]:
    candidates: list[str] = []
    for match in _STOCK_SYMBOL_RE.findall(query or ""):
        symbol = _canonicalize_symbol(match)
        if symbol and symbol not in candidates:
            candidates.append(symbol)
    return candidates


def _looks_like_fund_query(query: str) -> bool:
    lowered = (query or "").lower()
    return any(token in lowered for token in _FUND_HINTS)


def _looks_like_sector_query(query: str) -> bool:
    return any(token in (query or "") for token in _SECTOR_HINTS)


def _looks_like_index_query(query: str) -> bool:
    text = (query or "").strip()
    if any(alias in text for alias in _INDEX_ALIAS_MAP):
        return True
    return "指数" in text and not _looks_like_sector_query(text)


def _is_followup_reference(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    if any(token in text for token in _FOLLOWUP_HINTS):
        return True
    return not _extract_symbol_candidates(text) and text in {"继续", "继续说", "继续分析", "再展开一下", "再说说"}


def _failure_result(
    failure_code: str,
    *,
    asset_type: AssetType | None = None,
    warnings: list[str] | None = None,
    audit: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> EntityResolutionResult:
    return EntityResolutionResult(
        asset_type=asset_type,
        failure_code=failure_code,
        warnings=list(warnings or []),
        audit=dict(audit or {}),
        candidates=list(candidates or []),
    )


async def _load_stock_catalog(*, refresh: bool = False) -> list[dict[str, Any]]:
    global _STOCK_CATALOG_CACHE, _STOCK_CATALOG_CACHED_AT

    now = time.time()
    if (
        not refresh
        and _STOCK_CATALOG_CACHE is not None
        and (now - _STOCK_CATALOG_CACHED_AT) < _STOCK_CATALOG_TTL_SECONDS
    ):
        return list(_STOCK_CATALOG_CACHE)

    client = get_tushare_client()
    fields = "ts_code,symbol,name,fullname,cnspell,exchange,market,list_status"
    rows: list[dict[str, Any]] = []
    for status in ("L", "D", "P"):
        try:
            data = await client.stock_basic(exchange="", list_status=status, fields=fields)
        except TushareClientError:
            continue
        payload = data.to_dict(orient="records") if hasattr(data, "to_dict") else data
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, dict))

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        ts_code = _canonicalize_symbol(str(row.get("ts_code") or ""))
        if not ts_code:
            continue
        item = dict(row)
        item["ts_code"] = ts_code
        item["symbol"] = str(item.get("symbol") or "")
        item["name"] = str(item.get("name") or "").strip()
        item["fullname"] = str(item.get("fullname") or "").strip()
        item["cnspell"] = str(item.get("cnspell") or "").strip().lower()
        item["_normalized_name"] = _normalize_search_text(item["name"])
        item["_normalized_fullname"] = _normalize_search_text(item["fullname"])
        deduped[ts_code] = item

    catalog = list(deduped.values())
    _STOCK_CATALOG_CACHE = catalog
    _STOCK_CATALOG_CACHED_AT = now
    return list(catalog)


async def _load_fund_catalog(*, refresh: bool = False) -> list[dict[str, Any]]:
    global _FUND_CATALOG_CACHE, _FUND_CATALOG_CACHED_AT

    now = time.time()
    if (
        not refresh
        and _FUND_CATALOG_CACHE is not None
        and (now - _FUND_CATALOG_CACHED_AT) < _FUND_CATALOG_TTL_SECONDS
    ):
        return list(_FUND_CATALOG_CACHE)

    client = get_tushare_client()
    rows: list[dict[str, Any]] = []
    for market in ("E", "O"):
        try:
            data = await client.fund_basic(market=market, status="L")
        except TushareClientError:
            continue
        payload = data.to_dict(orient="records") if hasattr(data, "to_dict") else data
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, dict))

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        ts_code = _canonicalize_symbol(str(row.get("ts_code") or ""))
        if not ts_code:
            continue
        item = dict(row)
        item["ts_code"] = ts_code
        deduped[ts_code] = item

    catalog = list(deduped.values())
    _FUND_CATALOG_CACHE = catalog
    _FUND_CATALOG_CACHED_AT = now
    return list(catalog)


def _lookup_row_by_code(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    wanted = _canonicalize_symbol(symbol)
    if not wanted:
        return None
    for row in rows:
        if _canonicalize_symbol(str(row.get("ts_code") or "")) == wanted:
            return row
    return None


async def _lookup_stock_by_code(symbol: str, *, catalog: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    wanted = _canonicalize_symbol(symbol)
    if not wanted:
        return None

    if catalog is not None:
        row = _lookup_row_by_code(catalog, wanted)
        if row is not None:
            return row

    client = get_tushare_client()
    try:
        data = await client.stock_basic(
            ts_code=wanted,
            fields="ts_code,symbol,name,fullname,cnspell,exchange,market,list_status",
        )
    except TushareClientError:
        return None
    payload = data.to_dict(orient="records") if hasattr(data, "to_dict") else data
    if isinstance(payload, list) and payload:
        row = dict(payload[0])
        row["ts_code"] = _canonicalize_symbol(str(row.get("ts_code") or wanted))
        return row
    return None


async def _warm_stock_aliases(symbol: str) -> list[str]:
    canonical = _canonicalize_symbol(symbol)
    if not canonical:
        return []

    client = get_tushare_client()
    try:
        data = await client.namechange(
            ts_code=canonical,
            fields="ts_code,name,start_date,end_date,change_reason",
        )
    except TushareClientError:
        return []
    payload = data.to_dict(orient="records") if hasattr(data, "to_dict") else data
    aliases: list[str] = []
    if not isinstance(payload, list):
        return aliases
    for row in payload:
        if not isinstance(row, dict):
            continue
        alias = str(row.get("name") or "").strip()
        if not alias:
            continue
        normalized = _normalize_search_text(alias)
        if normalized:
            _STOCK_NAME_ALIAS_MAP[normalized] = canonical
        if alias not in aliases:
            aliases.append(alias)
    return aliases[:12]


def _match_stock_alias(query_core: str) -> str:
    return _STOCK_NAME_ALIAS_MAP.get(_normalize_search_text(query_core), "")


def _stock_candidate_score(row: dict[str, Any], query: str) -> float:
    normalized_query = _normalize_search_text(query)
    if not normalized_query:
        return 0.0

    ts_code = _canonicalize_symbol(str(row.get("ts_code") or ""))
    symbol = str(row.get("symbol") or "")
    normalized_name = str(row.get("_normalized_name") or "")
    normalized_fullname = str(row.get("_normalized_fullname") or "")
    cnspell = str(row.get("cnspell") or "").lower()

    if ts_code and normalized_query == _normalize_search_text(ts_code):
        return 1.0
    if symbol and normalized_query == _normalize_search_text(symbol):
        return 0.99
    if normalized_name and normalized_query == normalized_name:
        return 0.99
    if normalized_fullname and normalized_query == normalized_fullname:
        return 0.98
    if cnspell and normalized_query == cnspell:
        return 0.96

    if normalized_name and normalized_name in normalized_query and len(normalized_name) >= 2:
        return 0.93
    if normalized_fullname and normalized_fullname in normalized_query and len(normalized_fullname) >= 4:
        return 0.9

    ratios = [
        SequenceMatcher(None, normalized_query, candidate).ratio()
        for candidate in (normalized_name, normalized_fullname, cnspell)
        if candidate
    ]
    ratio = max(ratios) if ratios else 0.0
    token_overlap = 0.0
    for token in _query_tokens(query):
        normalized_token = _normalize_search_text(token)
        if not normalized_token:
            continue
        if normalized_token in normalized_name or normalized_token in normalized_fullname:
            token_overlap = max(token_overlap, 0.12 if len(normalized_token) >= 4 else 0.06)

    score = min(0.89, ratio * 0.82 + token_overlap)
    if str(row.get("list_status") or "").upper() == "L":
        score += 0.01
    return min(score, 0.95)


def _stock_candidate_payload(row: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "display_name": str(row.get("name") or ""),
        "symbol": _canonicalize_symbol(str(row.get("ts_code") or "")),
        "score": round(float(score), 4),
        "list_status": str(row.get("list_status") or ""),
    }


async def _resolve_stock_entity_internal(
    query: str,
    *,
    session_symbols: list[str] | None = None,
) -> EntityResolutionResult:
    clean_query = (query or "").strip()
    audit: dict[str, Any] = {"input_text": clean_query}
    if not clean_query:
        return _failure_result("stock_query_missing", asset_type="stock", audit=audit)

    if _looks_like_fund_query(clean_query) or _looks_like_sector_query(clean_query) or _looks_like_index_query(clean_query):
        return _failure_result("stock_query_non_stock", asset_type="stock", audit=audit)

    catalog = await _load_stock_catalog()
    explicit_symbols = _extract_symbol_candidates(clean_query)
    if explicit_symbols:
        symbol = explicit_symbols[0]
        row = await _lookup_stock_by_code(symbol, catalog=catalog)
        warnings: list[str] = []
        if row is None:
            code, exchange = _parse_symbol_to_parts(symbol)
            return EntityResolutionResult(
                display_name="",
                asset_type="stock",
                symbol=symbol,
                exchange=exchange,
                confidence=0.82,
                resolver_stage="explicit_symbol_unverified",
                resolver_source="symbol_regex",
                warnings=["symbol_not_verified_by_tushare"],
                audit={"input_text": clean_query, "matched_by": "explicit_symbol", "stock_code": symbol, "code": code},
            )

        aliases = await _warm_stock_aliases(symbol)
        display_name = str(row.get("name") or "")
        extra_text = _normalize_search_text(_clean_query_core(clean_query))
        if extra_text and display_name and extra_text not in _normalize_search_text(display_name) and symbol not in clean_query.upper():
            warnings.append("name_symbol_conflict_prefer_symbol")
        code, exchange = _parse_symbol_to_parts(symbol)
        return EntityResolutionResult(
            display_name=display_name,
            asset_type="stock",
            symbol=symbol,
            exchange=exchange,
            confidence=0.99,
            resolver_stage="explicit_symbol",
            resolver_source="tushare.stock_basic",
            warnings=warnings,
            audit={"input_text": clean_query, "matched_by": "explicit_symbol", "candidate_count": 1, "code": code},
            aliases=aliases,
        )

    if session_symbols and _is_followup_reference(clean_query):
        hinted = _canonicalize_symbol(session_symbols[0])
        row = await _lookup_stock_by_code(hinted, catalog=catalog)
        if row is not None:
            aliases = await _warm_stock_aliases(hinted)
            _, exchange = _parse_symbol_to_parts(hinted)
            return EntityResolutionResult(
                display_name=str(row.get("name") or hinted),
                asset_type="stock",
                symbol=hinted,
                exchange=exchange,
                confidence=0.91,
                resolver_stage="session_inherit",
                resolver_source="session_symbols",
                audit={"input_text": clean_query, "matched_by": "session_hint", "candidate_count": 1},
                aliases=aliases,
            )

    query_core = _clean_query_core(clean_query)
    alias_symbol = _match_stock_alias(query_core)
    if alias_symbol:
        row = await _lookup_stock_by_code(alias_symbol, catalog=catalog)
        if row is not None:
            aliases = await _warm_stock_aliases(alias_symbol)
            _, exchange = _parse_symbol_to_parts(alias_symbol)
            return EntityResolutionResult(
                display_name=str(row.get("name") or alias_symbol),
                asset_type="stock",
                symbol=alias_symbol,
                exchange=exchange,
                confidence=0.95,
                resolver_stage="cached_alias",
                resolver_source="tushare.namechange_cache",
                corrected_from=query_core,
                audit={"input_text": clean_query, "matched_by": "cached_alias", "candidate_count": 1},
                aliases=aliases,
            )

    matches: list[tuple[float, dict[str, Any]]] = []
    for row in catalog:
        score = _stock_candidate_score(row, query_core or clean_query)
        if score < 0.62:
            continue
        matches.append((score, row))

    matches.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("list_status") or "") != "L",
            len(str(item[1].get("name") or "")),
            str(item[1].get("name") or ""),
        )
    )
    if matches:
        top_score, top_row = matches[0]
        second_score = matches[1][0] if len(matches) > 1 else 0.0
        candidates = [_stock_candidate_payload(row, score) for score, row in matches[:5]]
        if top_score >= 0.97 or (top_score >= 0.92 and (top_score - second_score) >= 0.04):
            symbol = _canonicalize_symbol(str(top_row.get("ts_code") or ""))
            _, exchange = _parse_symbol_to_parts(symbol)
            aliases = await _warm_stock_aliases(symbol)
            return EntityResolutionResult(
                display_name=str(top_row.get("name") or ""),
                asset_type="stock",
                symbol=symbol,
                exchange=exchange,
                confidence=round(float(top_score), 4),
                resolver_stage="catalog_match",
                resolver_source="tushare.stock_basic",
                candidates=candidates,
                audit={"input_text": clean_query, "matched_by": "catalog_match", "candidate_count": len(matches[:5])},
                aliases=aliases,
            )
        if top_score >= 0.84 and (top_score - second_score) >= 0.12:
            symbol = _canonicalize_symbol(str(top_row.get("ts_code") or ""))
            _, exchange = _parse_symbol_to_parts(symbol)
            aliases = await _warm_stock_aliases(symbol)
            return EntityResolutionResult(
                display_name=str(top_row.get("name") or ""),
                asset_type="stock",
                symbol=symbol,
                exchange=exchange,
                confidence=round(float(top_score), 4),
                resolver_stage="catalog_confident",
                resolver_source="tushare.stock_basic",
                candidates=candidates,
                audit={"input_text": clean_query, "matched_by": "catalog_confident", "candidate_count": len(matches[:5])},
                aliases=aliases,
            )
        audit["candidate_count"] = len(matches[:5])
        audit["matched_by"] = "catalog_ambiguous"
        return _failure_result(
            "stock_ambiguous",
            asset_type="stock",
            audit=audit,
            candidates=candidates,
        )

    try:
        from backend.services.stock_resolver import _llm_extract
    except Exception:
        _llm_extract = None

    if _llm_extract is not None:
        company_name, symbol = await _llm_extract(clean_query)
        symbol = _canonicalize_symbol(symbol)
        if symbol:
            row = await _lookup_stock_by_code(symbol, catalog=catalog)
            display_name = str(row.get("name") or company_name or symbol) if row else str(company_name or symbol)
            _, exchange = _parse_symbol_to_parts(symbol)
            aliases = await _warm_stock_aliases(symbol)
            return EntityResolutionResult(
                display_name=display_name,
                asset_type="stock",
                symbol=symbol,
                exchange=exchange,
                confidence=0.74 if row else 0.68,
                resolver_stage="llm_fallback",
                resolver_source="llm+tushare_verify" if row else "llm_only",
                warnings=[] if row else ["llm_symbol_not_verified"],
                audit={"input_text": clean_query, "matched_by": "llm_fallback", "candidate_count": 1},
                aliases=aliases,
            )

    return _failure_result("stock_unresolved", asset_type="stock", audit=audit)


def _index_resolution_from_alias(query: str) -> EntityResolutionResult:
    clean_query = (query or "").strip()
    for alias, symbol in _INDEX_ALIAS_MAP.items():
        if alias in clean_query:
            _, exchange = _parse_symbol_to_parts(symbol)
            return EntityResolutionResult(
                display_name=alias,
                asset_type="index",
                symbol=symbol,
                exchange=exchange,
                confidence=0.99,
                resolver_stage="index_alias",
                resolver_source="built_in_alias_map",
                audit={"input_text": clean_query, "matched_by": "index_alias", "candidate_count": 1},
            )
    return _failure_result("index_unresolved", asset_type="index", audit={"input_text": clean_query})


async def _resolve_fund_entity_internal(query: str) -> EntityResolutionResult:
    clean_query = (query or "").strip()
    audit = {"input_text": clean_query}
    if not clean_query:
        return _failure_result("fund_query_missing", asset_type="fund", audit=audit)

    rows, top_name, error, warning, source_api = await _search_fund_candidates(query=clean_query, limit=5)
    if error or not rows:
        return _failure_result(
            "fund_unresolved",
            asset_type="fund",
            warnings=[warning] if warning else [],
            audit=audit,
        )

    top = rows[0]
    symbol = _canonicalize_symbol(str(top.get("ts_code") or ""))
    _, exchange = _parse_symbol_to_parts(symbol)
    candidates = [
        {
            "display_name": str(row.get("name") or ""),
            "symbol": _canonicalize_symbol(str(row.get("ts_code") or "")),
            "score": int(row.get("_score") or 0),
        }
        for row in rows[:5]
    ]
    return EntityResolutionResult(
        display_name=str(top_name or top.get("name") or symbol),
        asset_type="fund",
        symbol=symbol,
        exchange=exchange,
        confidence=0.95,
        resolver_stage="fund_catalog",
        resolver_source=f"tushare.{source_api}",
        warnings=[warning] if warning else [],
        candidates=candidates,
        audit={"input_text": clean_query, "matched_by": "fund_catalog", "candidate_count": len(candidates)},
    )


async def _resolve_sector_entity_internal(query: str) -> EntityResolutionResult:
    clean_query = (query or "").strip()
    resolution = await resolve_sector_request(query=clean_query)
    if not str(resolution.get("index_code") or "").strip():
        return _failure_result(
            str(resolution.get("failure_code") or "sector_unresolved"),
            asset_type="sector",
            audit={"input_text": clean_query, "matched_by": "sector_resolver"},
            candidates=list(resolution.get("candidate_details") or []),
        )
    symbol = str(resolution.get("index_code") or "").strip()
    return EntityResolutionResult(
        display_name=str(resolution.get("normalized_sector_name") or ""),
        asset_type="sector",
        symbol=symbol,
        exchange="SW2021",
        confidence=float(resolution.get("match_confidence") or 0.0),
        resolver_stage="sector_catalog",
        resolver_source="tushare.index_classify",
        candidates=list(resolution.get("candidate_details") or []),
        audit={"input_text": clean_query, "matched_by": "sector_catalog", "candidate_count": len(resolution.get("candidate_details") or [])},
    )


async def resolve_entity(
    query: str,
    *,
    allowed_asset_types: set[AssetType] | None = None,
    session_symbols: list[str] | None = None,
    summary_active_symbols: list[str] | None = None,
) -> EntityResolutionResult:
    allowed = set(allowed_asset_types or {"stock", "fund", "sector", "index"})
    clean_query = (query or "").strip()
    if not clean_query:
        return _failure_result("entity_query_missing", audit={"input_text": clean_query})

    merged_session_symbols: list[str] = []
    for symbol_group in (session_symbols or [], summary_active_symbols or []):
        symbol = _canonicalize_symbol(symbol_group)
        if symbol and symbol not in merged_session_symbols:
            merged_session_symbols.append(symbol)

    if "index" in allowed and _looks_like_index_query(clean_query):
        result = _index_resolution_from_alias(clean_query)
        if result.ok:
            return result

    if "sector" in allowed and _looks_like_sector_query(clean_query):
        result = await _resolve_sector_entity_internal(clean_query)
        if result.ok:
            return result

    if "fund" in allowed and _looks_like_fund_query(clean_query):
        result = await _resolve_fund_entity_internal(clean_query)
        if result.ok:
            return result

    if "stock" in allowed:
        return await _resolve_stock_entity_internal(clean_query, session_symbols=merged_session_symbols or None)

    return _failure_result("entity_type_not_allowed", audit={"input_text": clean_query})


async def gather_candidates(
    query: str,
    *,
    allowed_asset_types: set[AssetType] | None = None,
    session_symbols: list[str] | None = None,
    summary_active_symbols: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return normalized candidate entities for the authoritative resolver v2."""

    result = await resolve_entity(
        query,
        allowed_asset_types=allowed_asset_types,
        session_symbols=session_symbols,
        summary_active_symbols=summary_active_symbols,
    )
    candidates: list[dict[str, Any]] = []
    if result.ok:
        candidates.append(
            {
                "entity_type": result.asset_type,
                "canonical_id": result.symbol or result.display_name,
                "display_name": result.display_name,
                "market": result.exchange,
                "score": float(result.confidence or 0.0),
                "source": result.resolver_source or result.resolver_stage or "catalog",
                "failure_code": result.failure_code,
            }
        )
    for item in result.candidates or []:
        if not isinstance(item, dict):
            continue
        canonical_id = str(
            item.get("symbol")
            or item.get("ts_code")
            or item.get("canonical_id")
            or item.get("code")
            or ""
        ).strip()
        display_name = str(item.get("display_name") or item.get("name") or canonical_id).strip()
        asset_type = str(item.get("asset_type") or result.asset_type or "").strip()
        if not canonical_id and not display_name:
            continue
        candidate = {
            "entity_type": asset_type,
            "canonical_id": canonical_id or display_name,
            "display_name": display_name or canonical_id,
            "market": str(item.get("market") or item.get("exchange") or ""),
            "score": float(item.get("score") or item.get("confidence") or 0.0),
            "source": str(item.get("source") or result.resolver_source or "catalog"),
            "failure_code": result.failure_code,
        }
        if all(existing.get("canonical_id") != candidate["canonical_id"] for existing in candidates):
            candidates.append(candidate)
    return candidates[: max(1, int(limit or 5))]


async def resolve_stock_entity(
    query: str,
    *,
    session_symbols: list[str] | None = None,
) -> EntityResolutionResult:
    return await _resolve_stock_entity_internal(query, session_symbols=session_symbols)
