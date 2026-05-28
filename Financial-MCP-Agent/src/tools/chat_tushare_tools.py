from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urlparse
import uuid

try:
    from langchain.tools import tool
except Exception:  # pragma: no cover - optional import path
    def tool(*args, **kwargs):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def _decorator(func):
            return func
        return _decorator

from src.tools.tushare_client import TushareClientError, get_tushare_client
from src.tools.skill_trace import log_tool_call, new_evidence_id

try:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    _DDGS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    DDGS = None  # type: ignore[assignment]
    _DDGS_AVAILABLE = False

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
_FUND_GENERIC_TERMS = ("基金", "etf", "lof", "qdii", "联接基金", "联接")
_SECTOR_SUFFIX_RE = re.compile(r"(板块|行业|概念|赛道|主题|方向|产业链|板块股|行情|走势|最近|近期|今天|今日|怎么样|如何)$")
_SECTOR_FILLER_RE = re.compile(r"^(请|帮我|想看|看看|分析|说说|聊聊|再说说|麻烦|给我看看)+")
_SECTOR_CATALOG_TTL_SECONDS = 6 * 60 * 60
_SECTOR_ALIAS_RULES: dict[str, dict[str, Any]] = {
    "新能源": {
        "preferred": "电力设备",
        "candidates": ["电力设备", "汽车", "公用事业"],
        "confidence": 0.84,
    },
    "新能源设备": {
        "preferred": "电力设备",
        "candidates": ["电力设备"],
        "confidence": 0.92,
    },
    "新能源车": {
        "preferred": "汽车",
        "candidates": ["汽车"],
        "confidence": 0.92,
    },
    "智能汽车": {
        "preferred": "汽车",
        "candidates": ["汽车"],
        "confidence": 0.9,
    },
    "光伏": {
        "preferred": "电力设备",
        "candidates": ["电力设备"],
        "confidence": 0.92,
    },
    "风电": {
        "preferred": "电力设备",
        "candidates": ["电力设备"],
        "confidence": 0.92,
    },
    "储能": {
        "preferred": "电力设备",
        "candidates": ["电力设备"],
        "confidence": 0.92,
    },
    "锂电": {
        "preferred": "电力设备",
        "candidates": ["电力设备"],
        "confidence": 0.9,
    },
    "军工": {
        "preferred": "国防军工",
        "candidates": ["国防军工"],
        "confidence": 0.95,
    },
    "半导体": {
        "preferred": "半导体",
        "candidates": ["半导体"],
        "confidence": 0.96,
    },
    "人工智能": {
        "preferred": None,
        "candidates": ["计算机", "电子", "通信", "传媒"],
        "confidence": 0.0,
    },
    "科技": {
        "preferred": None,
        "candidates": ["电子", "计算机", "通信", "传媒"],
        "confidence": 0.0,
    },
}
_SECTOR_CATALOG_CACHE: list[dict[str, Any]] | None = None
_SECTOR_CATALOG_CACHED_AT = 0.0
_TOOL_EVIDENCE_TYPE_MAP = {
    "stock_basic": "stock_basic",
    "daily": "stock_daily",
    "fina_indicator": "financial_indicator",
    "income": "income_statement",
    "balancesheet": "balance_sheet",
    "cashflow": "cashflow_statement",
    "pro_bar": "stock_market",
    "index_pro_bar": "index_daily",
    "sw_daily": "sector_snapshot",
    "index_member": "sector_constituents",
    "fund_basic": "fund_basic",
    "fund_nav": "fund_nav",
    "fund_daily": "fund_daily",
    "fund_share": "fund_share",
    "ddgs_text": "web_news",
    "tavily_search": "web_news",
    "duckduckgo_search": "web_news",
    "web_search_v2": "web_news",
}
_API_FAMILY_MAP = {
    "stock_basic": "stock_basic",
    "daily": "stock_market",
    "pro_bar": "stock_market",
    "index_pro_bar": "index_market",
    "sw_daily": "sector_market",
    "index_member": "sector_market",
    "fund_basic": "fund_basic",
    "fund_nav": "fund_market",
    "fund_daily": "fund_market",
    "fund_share": "fund_market",
    "fina_indicator": "stock_fundamental",
    "income": "stock_fundamental",
    "balancesheet": "stock_fundamental",
    "cashflow": "stock_fundamental",
    "ddgs_text": "web_news",
    "tavily_search": "web_news",
    "duckduckgo_search": "web_news",
    "web_search_v2": "web_news",
}
_SUSPICIOUS_DOMAIN_PATTERN = re.compile(
    r"\.(cc|tk|ml|ga|cf|gq|xyz|top|work|click|link|pw|buzz)(/|$)",
    re.I,
)
_RANDOM_DOMAIN_PATTERN = re.compile(r"^[a-z0-9]{10,}$", re.I)
_FINANCE_NEWS_HINTS = ("涨", "跌", "异动", "拉升", "跳水", "公告", "消息", "利好", "利空", "新闻")


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _new_tool_result_id() -> str:
    return f"toolr_{uuid.uuid4().hex}"


def _to_tushare_ts_code(symbol: str) -> str:
    """Delegate to canonical implementation for consistent symbol formatting."""
    try:
        from backend.services.stock_resolver import canonicalize_symbol
        return canonicalize_symbol(symbol)
    except ImportError:
        raw = (symbol or "").strip()
        if not raw:
            return ""
        upper = raw.upper()
        if "." in upper and upper.endswith((".SH", ".SZ", ".BJ")) and len(upper.split(".", 1)[0]) == 6:
            return upper
        return upper


def _symbol_code_part(symbol: str) -> str:
    clean = _to_tushare_ts_code(symbol)
    if "." in clean:
        return clean.split(".", 1)[0]
    return "".join(ch for ch in clean if ch.isdigit())


def _pick_trade_date(payload: Any) -> str | None:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        for key in ("trade_date", "end_date", "ann_date", "f_ann_date"):
            value = payload[0].get(key)
            if value:
                return str(value)
    if isinstance(payload, dict):
        for key in ("trade_date", "end_date", "ann_date", "f_ann_date"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _is_suspicious_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return True
    try:
        host = (urlparse(url).netloc or "").split(":", 1)[0].lower()
        if not host:
            return True
        if _SUSPICIOUS_DOMAIN_PATTERN.search(host):
            return True
        parts = host.rsplit(".", 2)
        name = parts[0] if parts else ""
        if len(name) >= 10 and _RANDOM_DOMAIN_PATTERN.match(name):
            return True
        return False
    except Exception:  # pragma: no cover - defensive
        return False


def _host_label(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").split(":", 1)[0].lower()
        return host or ""
    except Exception:  # pragma: no cover - defensive
        return ""


def _search_timelimit(freshness_days: int) -> str | None:
    if freshness_days <= 1:
        return "d"
    if freshness_days <= 7:
        return "w"
    if freshness_days <= 31:
        return "m"
    return None


def _build_market_news_query(query: str) -> str:
    clean = str(query or "").strip()
    if not clean:
        return ""
    if any(token in clean for token in _FINANCE_NEWS_HINTS):
        return f"{clean} A股"
    return f"{clean} A股 新闻 公告"


def _normalize_web_result(item: dict[str, Any], *, rank: int) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    url = str(item.get("href") or item.get("url") or "").strip()
    snippet = str(item.get("body") or item.get("snippet") or "").strip()
    published = str(item.get("date") or item.get("published") or "").strip()
    if not title or not url or _is_suspicious_url(url):
        return None
    return {
        "rank": rank,
        "title": title,
        "url": url,
        "snippet": snippet,
        "source": _host_label(url),
        "published_at": published or None,
    }


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


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


def _normalize_search_text(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = re.sub(r"[\s\-_()/（）【】\[\]，。！？,.!?:：；;]+", "", normalized)
    return normalized


def _sector_level_rank(level: str) -> int:
    normalized = str(level or "").strip().upper()
    if normalized == "L1":
        return 0
    if normalized == "L2":
        return 1
    if normalized == "L3":
        return 2
    return 9


def _clean_sector_query(text: str) -> str:
    candidate = str(text or "").strip("，。！？,.!?：:；;()（）[]【】 ")
    if not candidate:
        return ""
    candidate = _SECTOR_FILLER_RE.sub("", candidate)
    changed = True
    while changed and candidate:
        updated = _SECTOR_SUFFIX_RE.sub("", candidate).strip("，。！？,.!?：:；;()（）[]【】 ")
        changed = updated != candidate
        candidate = updated
    return candidate.strip()


def _base_sector_resolution(requested: str, cleaned: str) -> dict[str, Any]:
    return {
        "requested_name": requested,
        "cleaned_name": cleaned,
        "normalized_sector_name": "",
        "index_code": "",
        "match_confidence": 0.0,
        "candidate_sector_names": [],
        "candidate_details": [],
        "failure_code": "",
        "error": "",
        "resolver_source": "SW2021",
    }


def _is_published_sector(row: dict[str, Any]) -> bool:
    return str(row.get("is_pub") or "1").strip() != "0"


async def _load_sw2021_sector_catalog(*, refresh: bool = False) -> list[dict[str, Any]]:
    global _SECTOR_CATALOG_CACHE, _SECTOR_CATALOG_CACHED_AT

    now = time.time()
    if (
        not refresh
        and _SECTOR_CATALOG_CACHE is not None
        and (now - _SECTOR_CATALOG_CACHED_AT) < _SECTOR_CATALOG_TTL_SECONDS
    ):
        return list(_SECTOR_CATALOG_CACHE)

    client = get_tushare_client()
    data = await client.index_classify(src="SW2021")
    payload = _df_to_payload(data)
    if not isinstance(payload, list):
        return []

    catalog: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        industry_name = str(row.get("industry_name") or "").strip()
        index_code = str(row.get("index_code") or "").strip()
        if not industry_name or not index_code:
            continue
        item = dict(row)
        item["industry_name"] = industry_name
        item["index_code"] = index_code
        item["_normalized_name"] = _normalize_search_text(industry_name)
        catalog.append(item)

    catalog.sort(
        key=lambda item: (
            _sector_level_rank(str(item.get("level") or "")),
            len(str(item.get("industry_name") or "")),
            str(item.get("industry_name") or ""),
        )
    )
    _SECTOR_CATALOG_CACHE = catalog
    _SECTOR_CATALOG_CACHED_AT = now
    return list(catalog)


def _sector_alias_rule(cleaned_name: str) -> dict[str, Any] | None:
    normalized = _clean_sector_query(cleaned_name)
    if not normalized:
        return None
    if normalized in _SECTOR_ALIAS_RULES:
        return dict(_SECTOR_ALIAS_RULES[normalized])

    matched_key = ""
    matched_rule: dict[str, Any] | None = None
    for alias, rule in _SECTOR_ALIAS_RULES.items():
        if alias in normalized and len(alias) > len(matched_key):
            matched_key = alias
            matched_rule = dict(rule)
    return matched_rule


def _score_sector_candidate(cleaned_query: str, row: dict[str, Any]) -> float:
    normalized_query = _normalize_search_text(cleaned_query)
    normalized_name = str(row.get("_normalized_name") or "")
    if not normalized_query or not normalized_name:
        return 0.0
    if normalized_query == normalized_name:
        return 1.0
    if normalized_query in normalized_name:
        score = 0.94 - max(0, len(normalized_name) - len(normalized_query)) * 0.01
        return max(0.78, min(score, 0.94))
    if normalized_name in normalized_query and len(normalized_name) >= 4:
        return 0.88

    ratio = SequenceMatcher(None, normalized_query, normalized_name).ratio()
    token_overlap = 0.0
    for token in _query_tokens(cleaned_query):
        normalized_token = _normalize_search_text(token)
        if normalized_token and normalized_token in normalized_name:
            token_overlap = max(token_overlap, 0.12 if len(normalized_token) >= 4 else 0.06)
    return min(0.89, ratio * 0.82 + token_overlap)


def _candidate_detail(row: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "sector_name": str(row.get("industry_name") or ""),
        "index_code": str(row.get("index_code") or ""),
        "level": str(row.get("level") or ""),
        "score": round(float(score), 4),
    }


def _find_named_sector_candidate(
    catalog: list[dict[str, Any]],
    sector_name: str,
) -> dict[str, Any] | None:
    normalized_target = _normalize_search_text(sector_name)
    if not normalized_target:
        return None

    exact = [
        row
        for row in catalog
        if _is_published_sector(row) and str(row.get("_normalized_name") or "") == normalized_target
    ]
    if exact:
        return exact[0]

    contains = [
        row
        for row in catalog
        if _is_published_sector(row) and normalized_target in str(row.get("_normalized_name") or "")
    ]
    if contains:
        return contains[0]
    return None


async def resolve_sector_request(query: str = "", sector_name: str = "") -> dict[str, Any]:
    requested = _first_non_empty(sector_name, query) or ""
    cleaned = _clean_sector_query(requested)
    result = _base_sector_resolution(requested, cleaned)
    if not requested:
        result["failure_code"] = "sector_missing"
        result["error"] = "missing sector query"
        return result
    if not cleaned:
        result["failure_code"] = "sector_unresolved"
        result["error"] = "unable to extract sector keyword"
        return result

    try:
        catalog = await _load_sw2021_sector_catalog()
    except Exception as exc:
        result["failure_code"] = "sector_catalog_unavailable"
        result["error"] = f"failed to load sector catalog: {exc}"
        return result

    if not catalog:
        result["failure_code"] = "sector_catalog_unavailable"
        result["error"] = "empty sector catalog"
        return result

    alias_rule = _sector_alias_rule(cleaned)
    if alias_rule:
        candidates = [str(item).strip() for item in alias_rule.get("candidates") or [] if str(item).strip()]
        result["candidate_sector_names"] = candidates[:6]
        preferred = str(alias_rule.get("preferred") or "").strip()
        if preferred:
            preferred_row = _find_named_sector_candidate(catalog, preferred)
            if preferred_row is not None:
                result["normalized_sector_name"] = str(preferred_row.get("industry_name") or preferred)
                result["index_code"] = str(preferred_row.get("index_code") or "")
                result["match_confidence"] = round(float(alias_rule.get("confidence") or 0.82), 4)
                result["candidate_details"] = [_candidate_detail(preferred_row, result["match_confidence"])]
                return result
        if candidates:
            result["failure_code"] = "sector_ambiguous"
            result["error"] = "sector alias maps to multiple candidates"
            return result

    matches: list[tuple[float, dict[str, Any]]] = []
    for row in catalog:
        if not _is_published_sector(row):
            continue
        score = _score_sector_candidate(cleaned, row)
        if score < 0.62:
            continue
        matches.append((score, row))

    matches.sort(
        key=lambda item: (
            -item[0],
            _sector_level_rank(str(item[1].get("level") or "")),
            len(str(item[1].get("industry_name") or "")),
            str(item[1].get("industry_name") or ""),
        )
    )
    if not matches:
        result["failure_code"] = "sector_unresolved"
        result["error"] = "unable to match SW2021 sector"
        return result

    top_score, top_row = matches[0]
    result["candidate_sector_names"] = [
        str(row.get("industry_name") or "")
        for _, row in matches[:5]
        if str(row.get("industry_name") or "")
    ]
    result["candidate_details"] = [_candidate_detail(row, score) for score, row in matches[:5]]

    second_score = matches[1][0] if len(matches) > 1 else 0.0
    if top_score >= 0.97 or (top_score >= 0.9 and (top_score - second_score) >= 0.03):
        result["normalized_sector_name"] = str(top_row.get("industry_name") or "")
        result["index_code"] = str(top_row.get("index_code") or "")
        result["match_confidence"] = round(float(top_score), 4)
        return result
    if top_score >= 0.8 and (top_score - second_score) >= 0.08:
        result["normalized_sector_name"] = str(top_row.get("industry_name") or "")
        result["index_code"] = str(top_row.get("index_code") or "")
        result["match_confidence"] = round(float(top_score), 4)
        return result

    result["failure_code"] = "sector_ambiguous"
    result["error"] = "multiple sector candidates matched"
    result["match_confidence"] = round(float(top_score), 4)
    return result


def _fund_semantic_tokens(query: str) -> list[str]:
    raw = (query or "").strip()
    if not raw:
        return []

    tokens: list[str] = []
    base = _normalize_search_text(raw)
    for generic in _FUND_GENERIC_TERMS:
        base = base.replace(generic.lower(), "")
    base = re.sub(r"[abc]$", "", base)
    if len(base) >= 2:
        tokens.append(base)

    chinese_parts = re.findall(r"[\u4e00-\u9fff]{2,}", raw)
    for part in chinese_parts:
        part = part.strip()
        if len(part) >= 2 and part not in tokens:
            tokens.append(part)
        compact = part
        for generic in ("基金", "联接基金", "联接"):
            compact = compact.replace(generic, "")
        if len(compact) >= 4:
            head = compact[:2]
            tail = compact[-2:]
            if head not in tokens:
                tokens.append(head)
            if tail not in tokens:
                tokens.append(tail)

    for token in _query_tokens(raw):
        if token.lower() in {"etf", "lof", "qdii"}:
            continue
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)

    return tokens[:12]


def _score_row(row: dict[str, Any], query: str, fields: tuple[str, ...]) -> int:
    tokens = _query_tokens(query)
    if not tokens:
        return 0
    score = 0
    for field in fields:
        value = str(row.get(field) or "").lower()
        if not value:
            continue
        for token in tokens:
            if token in value:
                score += 5 if token == value else 2
    return score


def _score_fund_row(row: dict[str, Any], query: str) -> tuple[int, int]:
    semantic_tokens = _fund_semantic_tokens(query)
    query_core = _normalize_search_text(query)
    for generic in _FUND_GENERIC_TERMS:
        query_core = query_core.replace(generic.lower(), "")
    query_core = re.sub(r"[abc]$", "", query_core)

    weighted_fields = (
        ("name", 10),
        ("csname", 10),
        ("extname", 10),
        ("cname", 10),
        ("fullname", 9),
        ("fund_fullname", 9),
        ("benchmark", 4),
        ("index_name", 6),
        ("management", 3),
        ("mgr_name", 2),
    )
    score = 0
    matched_tokens: set[str] = set()

    for field, weight in weighted_fields:
        value = str(row.get(field) or "").strip()
        if not value:
            continue
        normalized_value = _normalize_search_text(value)
        if query_core:
            if normalized_value == query_core:
                score += 120
            elif query_core and query_core in normalized_value:
                score += 70
            elif normalized_value and normalized_value in query_core and len(normalized_value) >= 4:
                score += 40
        for token in semantic_tokens:
            normalized_token = _normalize_search_text(token)
            if not normalized_token:
                continue
            if normalized_token in normalized_value:
                matched_tokens.add(normalized_token)
                score += weight * (4 if len(normalized_token) >= 4 else 2)

    score += _score_row(
        row,
        query,
        ("name", "csname", "extname", "cname", "fullname", "fund_fullname", "index_name", "benchmark", "management", "mgr_name"),
    )
    return score, len(matched_tokens)


def _df_to_payload(data: Any) -> Any:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        try:
            return data.to_dict(orient="records")
        except TypeError:
            return data.to_dict()
    return data


def _build_response(
    symbol: str,
    payload: Any,
    error: str | None = None,
    *,
    source_api: str = "",
    evidence_type: str = "",
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_ms: float | int | None = None,
    cache_hit: bool = False,
    retry_count: int = 0,
    api_family: str | None = None,
) -> dict[str, Any]:
    fetch_ts = ended_at or _now_text()
    return {
        "ok": error is None,
        "source": "web" if (api_family or _API_FAMILY_MAP.get(source_api)) == "web_news" else "tushare",
        "source_api": source_api,
        "api_family": api_family or _API_FAMILY_MAP.get(source_api, "unknown"),
        "evidence_type": evidence_type,
        "evidence_id": new_evidence_id(),
        "tool_result_id": _new_tool_result_id(),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "cache_hit": cache_hit,
        "retry_count": retry_count,
        "trade_date": _pick_trade_date(payload),
        "data_time": fetch_ts,
        "fetch_ts": fetch_ts,
        "symbol": symbol,
        "payload": payload,
        "error": error,
    }


def _dedupe_by_ts_code(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        key = ts_code or str(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _pick_index_code(query: str = "", symbol: str = "") -> str | None:
    clean_symbol = _to_tushare_ts_code(symbol)
    if clean_symbol:
        return clean_symbol

    text = (query or "").strip()
    for alias, index_code in _INDEX_ALIAS_MAP.items():
        if alias in text:
            return index_code

    match = re.search(r"\b\d{6}\.(?:SH|SZ)\b", text.upper())
    if match:
        return match.group(0)
    return None


async def _resolve_sector_code(query: str = "", sector_name: str = "") -> dict[str, Any]:
    return await resolve_sector_request(query=query, sector_name=sector_name)


async def _resolve_symbol(query: str = "", symbol: str = "") -> tuple[str | None, str | None, str | None]:
    clean_symbol = (symbol or "").strip()
    clean_query = (query or "").strip()

    try:
        from backend.services.stock_resolver import resolve_stock
    except Exception as exc:  # pragma: no cover - import safety
        if clean_symbol:
            return None, _to_tushare_ts_code(clean_symbol), None
        return None, None, f"stock resolver unavailable: {exc}"

    if clean_symbol:
        clean_symbol = _to_tushare_ts_code(clean_symbol)
        if not clean_query:
            return None, clean_symbol, None
        try:
            company_name, resolved_symbol = await resolve_stock(clean_query)
            resolved_symbol = _to_tushare_ts_code(resolved_symbol or "")
            if resolved_symbol:
                # Query-derived symbol is more trustworthy when the planner
                # guessed the wrong exchange suffix or produced a stale code.
                if clean_symbol != resolved_symbol:
                    return company_name, resolved_symbol, None
                return company_name, clean_symbol, None
        except Exception:
            return None, clean_symbol, None
        return None, clean_symbol, None

    if not clean_query:
        return None, None, "missing stock query"

    try:
        company_name, resolved_symbol = await resolve_stock(clean_query)
        resolved_symbol = _to_tushare_ts_code(resolved_symbol or "")
        return company_name, resolved_symbol, None if resolved_symbol else "unable to resolve stock symbol"
    except Exception as exc:  # pragma: no cover - defensive
        return None, None, f"stock resolution failed: {exc}"


async def _search_fund_candidates(
    *,
    query: str = "",
    symbol: str = "",
    limit: int = 10,
) -> tuple[list[dict[str, Any]], str | None, str | None, str | None, str]:
    clean_symbol = _to_tushare_ts_code(symbol)
    clean_query = (query or "").strip()
    client = get_tushare_client()
    rows: list[dict[str, Any]] = []
    warning: str | None = None
    source_api = "fund_basic"

    try:
        if clean_symbol:
            fund_raw = await client.fund_basic(ts_code=clean_symbol)
            rows.extend(_df_to_payload(fund_raw) or [])
        else:
            fund_raw = await client.fund_basic(market="E", status="L")
            rows.extend(_df_to_payload(fund_raw) or [])
    except TushareClientError as exc:
        return [], None, str(exc), warning, source_api
    except Exception as exc:  # pragma: no cover - defensive
        return [], None, f"Unexpected error: {exc}", warning, source_api

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["ts_code"] = _to_tushare_ts_code(str(item.get("ts_code") or ""))
        if "name" not in item:
            item["name"] = _first_non_empty(item.get("csname"), item.get("extname"), item.get("cname")) or ""
        item["_score"], item["_matched_semantic_tokens"] = _score_fund_row(
            item,
            clean_query or clean_symbol,
        )
        normalized_rows.append(item)

    normalized_rows = _dedupe_by_ts_code(normalized_rows)
    if clean_symbol:
        normalized_rows = [row for row in normalized_rows if row.get("ts_code") == clean_symbol]
    elif clean_query:
        semantic_tokens = _fund_semantic_tokens(clean_query)
        require_semantic_match = len(semantic_tokens) >= 2
        normalized_rows = [
            row
            for row in normalized_rows
            if int(row.get("_score") or 0) > 0
            and (
                not require_semantic_match
                or int(row.get("_matched_semantic_tokens") or 0) >= 1
            )
        ]
        normalized_rows.sort(key=lambda row: (-int(row.get("_score") or 0), str(row.get("ts_code") or "")))
        if normalized_rows:
            top_score = int(normalized_rows[0].get("_score") or 0)
            top_matches = int(normalized_rows[0].get("_matched_semantic_tokens") or 0)
            if top_score < 8 or (require_semantic_match and top_matches < 1):
                return [], None, "unable to confidently resolve fund symbol", warning, source_api

    if limit > 0:
        normalized_rows = normalized_rows[:limit]

    top_name = _first_non_empty(
        normalized_rows[0].get("name") if normalized_rows else None,
        normalized_rows[0].get("csname") if normalized_rows else None,
        normalized_rows[0].get("extname") if normalized_rows else None,
    )
    return normalized_rows, top_name, None, warning, source_api


async def _resolve_fund_symbol(
    *,
    query: str = "",
    symbol: str = "",
) -> tuple[str | None, str | None, str | None, str | None]:
    candidates, top_name, error, warning, _ = await _search_fund_candidates(
        query=query,
        symbol=symbol,
        limit=5,
    )
    if error:
        return None, None, error, warning
    if not candidates:
        return None, None, "unable to resolve fund symbol", warning
    top = candidates[0]
    return top_name, str(top.get("ts_code") or ""), None, warning


def _timed_response(
    *,
    symbol: str,
    payload: Any,
    error: str | None,
    source_api: str,
    evidence_type: str,
    started_at: str,
    started_perf: float,
) -> dict[str, Any]:
    return _build_response(
        symbol=symbol,
        payload=payload,
        error=error,
        source_api=source_api,
        evidence_type=evidence_type,
        started_at=started_at,
        ended_at=_now_text(),
        duration_ms=round((time.perf_counter() - started_perf) * 1000, 2),
        cache_hit=False,
        retry_count=0,
    )


async def _run_web_news_search_tool(
    *,
    query: str = "",
    max_results: int = 5,
    freshness_days: int = 7,
    region: str = "cn-zh",
) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    clean_query = str(query or "").strip()
    v2_shadow_payload: dict[str, Any] | None = None
    if not clean_query:
        return _timed_response(
            symbol="",
            payload={},
            error="missing web search query",
            source_api="ddgs_text",
            evidence_type="web_news",
            started_at=started_at,
            started_perf=started_perf,
        )
    if os.getenv("ENABLE_WEB_SEARCH_V2", "false").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from src.agents.web_search.service import execute_web_search

            v2_payload = await execute_web_search(
                query=clean_query,
                max_results=max_results,
                freshness_days=freshness_days,
                requires_web_news=True,
            )
            if os.getenv("WEB_SEARCH_SHADOW_MODE", "true").strip().lower() not in {"1", "true", "yes", "on"}:
                provider = str(v2_payload.get("provider") or "web_search_v2")
                source_api = "tavily_search" if provider == "tavily" else "duckduckgo_search"
                return _timed_response(
                    symbol="",
                    payload=v2_payload,
                    error=None if v2_payload.get("ok") else str(v2_payload.get("error") or "web_search_v2_failed"),
                    source_api=source_api,
                    evidence_type="web_news",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            # shadow 模式保留旧 DDGS 行为，但把 v2 决策放入旧 payload，方便对比而不影响线上回答。
            v2_shadow_payload = {
                "provider": v2_payload.get("provider"),
                "query_used": v2_payload.get("query_used"),
                "result_count": v2_payload.get("result_count"),
                "decision": v2_payload.get("decision"),
                "warnings": v2_payload.get("warnings") or [],
                "error": v2_payload.get("error"),
            }
        except Exception as exc:  # pragma: no cover - v2 provider depends on network/env
            v2_shadow_payload = {"error": f"web_search_v2_shadow_failed: {exc}"}
    if not _DDGS_AVAILABLE:
        return _timed_response(
            symbol="",
            payload={},
            error="ddgs not installed; install with `pip install ddgs`",
            source_api="ddgs_text",
            evidence_type="web_news",
            started_at=started_at,
            started_perf=started_perf,
        )

    query_used = _build_market_news_query(clean_query)
    timelimit = _search_timelimit(max(1, int(freshness_days or 7)))

    def _do_search() -> list[dict[str, Any]]:
        ddgs = DDGS()
        kwargs = {
            "query": query_used,
            "max_results": max(3, min(int(max_results or 5) * 2, 12)),
            "region": region,
            "safesearch": "off",
        }
        if timelimit:
            kwargs["timelimit"] = timelimit
        return list(ddgs.text(**kwargs))

    try:
        with log_tool_call(
            "ddgs_text",
            query=query_used,
            original_query=clean_query,
            max_results=max_results,
            freshness_days=freshness_days,
            region=region,
        ):
            raw_results = await asyncio.to_thread(_do_search)
    except Exception as exc:  # pragma: no cover - network/dep dependent
        return _timed_response(
            symbol="",
            payload={},
            error=f"web search failed: {exc}",
            source_api="ddgs_text",
            evidence_type="web_news",
            started_at=started_at,
            started_perf=started_perf,
        )

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            continue
        converted = _normalize_web_result(item, rank=idx)
        if converted is None:
            continue
        normalized.append(converted)
        if len(normalized) >= max(1, min(int(max_results or 5), 8)):
            break

    payload = {
        "query_used": query_used,
        "results": normalized,
        "result_count": len(normalized),
        "freshness_days": max(1, int(freshness_days or 7)),
    }
    if v2_shadow_payload is not None:
        payload["web_search_v2_shadow"] = v2_shadow_payload
    error = None if normalized else "no usable web news results"
    return _timed_response(
        symbol="",
        payload=payload,
        error=error,
        source_api="ddgs_text",
        evidence_type="web_news",
        started_at=started_at,
        started_perf=started_perf,
    )


async def _run_tool(method_name: str, symbol: str = "", query: str = "", **kwargs) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    company_name, resolved_symbol, resolve_error = await _resolve_symbol(query=query, symbol=symbol)
    if not resolved_symbol:
        return _timed_response(
            symbol=symbol or query,
            payload={},
            error=resolve_error or "unable to resolve stock symbol",
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )

    client = get_tushare_client()
    try:
        with log_tool_call(method_name, symbol=resolved_symbol, query=query, company_name=company_name, **kwargs):
            method = getattr(client, method_name)
            raw = await method(ts_code=resolved_symbol, **kwargs)
            payload = _df_to_payload(raw)
            if payload in (None, [], {}):
                return _timed_response(
                    symbol=resolved_symbol,
                    payload=payload,
                    error="empty result from Tushare",
                    source_api=method_name,
                    evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=resolved_symbol,
                payload=payload,
                error=None,
                source_api=method_name,
                evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
                started_at=started_at,
                started_perf=started_perf,
            )
            if company_name:
                response["company_name"] = company_name
            return response
    except TushareClientError as exc:
        return _timed_response(
            symbol=resolved_symbol,
            payload={},
            error=str(exc),
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _timed_response(
            symbol=resolved_symbol,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )


async def _run_market_tool(symbol: str = "", query: str = "", limit: int = 30) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    company_name, resolved_symbol, resolve_error = await _resolve_symbol(query=query, symbol=symbol)
    if not resolved_symbol:
        return _timed_response(
            symbol=symbol or query,
            payload={},
            error=resolve_error or "unable to resolve stock symbol",
            source_api="pro_bar",
            evidence_type="stock_market",
            started_at=started_at,
            started_perf=started_perf,
        )

    client = get_tushare_client()
    try:
        with log_tool_call("pro_bar", symbol=resolved_symbol, query=query, company_name=company_name, limit=limit):
            raw = await client.pro_bar(ts_code=resolved_symbol, asset="E", freq="D")
            payload = _df_to_payload(raw)
            if isinstance(payload, list) and limit > 0:
                payload = payload[:limit]
            if payload in (None, [], {}):
                return _timed_response(
                    symbol=resolved_symbol,
                    payload=payload,
                    error="empty result from Tushare",
                    source_api="pro_bar",
                    evidence_type="stock_market",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=resolved_symbol,
                payload=payload,
                error=None,
                source_api="pro_bar",
                evidence_type="stock_market",
                started_at=started_at,
                started_perf=started_perf,
            )
            if company_name:
                response["company_name"] = company_name
            return response
    except TushareClientError as exc:
        return _timed_response(
            symbol=resolved_symbol,
            payload={},
            error=str(exc),
            source_api="pro_bar",
            evidence_type="stock_market",
            started_at=started_at,
            started_perf=started_perf,
        )
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=resolved_symbol,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api="pro_bar",
            evidence_type="stock_market",
            started_at=started_at,
            started_perf=started_perf,
        )


async def _run_index_tool(symbol: str = "", query: str = "", limit: int = 30) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    index_code = _pick_index_code(query=query, symbol=symbol)
    if not index_code:
        return _timed_response(
            symbol=symbol or query,
            payload={},
            error="unable to resolve index code",
            source_api="index_pro_bar",
            evidence_type="index_daily",
            started_at=started_at,
            started_perf=started_perf,
        )

    client = get_tushare_client()
    try:
        with log_tool_call("index_pro_bar", symbol=index_code, query=query, limit=limit):
            raw = await client.pro_bar(ts_code=index_code, asset="I", freq="D")
            payload = _df_to_payload(raw)
            if isinstance(payload, list) and limit > 0:
                payload = payload[:limit]
            if payload in (None, [], {}):
                return _timed_response(
                    symbol=index_code,
                    payload=payload,
                    error="empty result from Tushare",
                    source_api="index_pro_bar",
                    evidence_type="index_daily",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            return _timed_response(
                symbol=index_code,
                payload=payload,
                error=None,
                source_api="index_pro_bar",
                evidence_type="index_daily",
                started_at=started_at,
                started_perf=started_perf,
            )
    except TushareClientError as exc:
        return _timed_response(
            symbol=index_code,
            payload={},
            error=str(exc),
            source_api="index_pro_bar",
            evidence_type="index_daily",
            started_at=started_at,
            started_perf=started_perf,
        )
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=index_code,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api="index_pro_bar",
            evidence_type="index_daily",
            started_at=started_at,
            started_perf=started_perf,
        )


async def _run_sector_snapshot_tool(query: str = "", sector_name: str = "") -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    sector_resolution = await _resolve_sector_code(query=query, sector_name=sector_name)
    resolved_name = str(sector_resolution.get("normalized_sector_name") or "").strip()
    index_code = str(sector_resolution.get("index_code") or "").strip()
    if not index_code:
        response = _timed_response(
            symbol=sector_name or query,
            payload={},
            error=str(sector_resolution.get("error") or "unable to resolve sector index"),
            source_api="sw_daily",
            evidence_type="sector_snapshot",
            started_at=started_at,
            started_perf=started_perf,
        )
        response["failure_code"] = str(sector_resolution.get("failure_code") or "sector_unresolved")
        response["candidate_sector_names"] = list(sector_resolution.get("candidate_sector_names") or [])
        response["match_confidence"] = float(sector_resolution.get("match_confidence") or 0.0)
        response["raw_sector_query"] = str(sector_resolution.get("requested_name") or sector_name or query)
        return response

    client = get_tushare_client()
    try:
        with log_tool_call(
            "sw_daily",
            symbol=index_code,
            query=query,
            sector_name=resolved_name,
            match_confidence=sector_resolution.get("match_confidence"),
        ):
            raw = await client.sw_daily(ts_code=index_code)
            payload = _df_to_payload(raw)
            if isinstance(payload, list):
                payload = payload[:10]
            if payload in (None, [], {}):
                return _timed_response(
                    symbol=index_code,
                    payload=payload,
                    error="empty result from Tushare",
                    source_api="sw_daily",
                    evidence_type="sector_snapshot",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=index_code,
                payload=payload,
                error=None,
                source_api="sw_daily",
                evidence_type="sector_snapshot",
                started_at=started_at,
                started_perf=started_perf,
            )
            response["sector_name"] = resolved_name
            response["match_confidence"] = float(sector_resolution.get("match_confidence") or 0.0)
            response["raw_sector_query"] = str(sector_resolution.get("requested_name") or sector_name or query)
            response["candidate_sector_names"] = list(sector_resolution.get("candidate_sector_names") or [])
            return response
    except TushareClientError as exc:
        return _timed_response(
            symbol=index_code,
            payload={},
            error=str(exc),
            source_api="sw_daily",
            evidence_type="sector_snapshot",
            started_at=started_at,
            started_perf=started_perf,
        )
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=index_code,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api="sw_daily",
            evidence_type="sector_snapshot",
            started_at=started_at,
            started_perf=started_perf,
        )


async def _run_sector_constituents_tool(query: str = "", sector_name: str = "", limit: int = 20) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    sector_resolution = await _resolve_sector_code(query=query, sector_name=sector_name)
    resolved_name = str(sector_resolution.get("normalized_sector_name") or "").strip()
    index_code = str(sector_resolution.get("index_code") or "").strip()
    if not index_code:
        response = _timed_response(
            symbol=sector_name or query,
            payload={},
            error=str(sector_resolution.get("error") or "unable to resolve sector index"),
            source_api="index_member",
            evidence_type="sector_constituents",
            started_at=started_at,
            started_perf=started_perf,
        )
        response["failure_code"] = str(sector_resolution.get("failure_code") or "sector_unresolved")
        response["candidate_sector_names"] = list(sector_resolution.get("candidate_sector_names") or [])
        response["match_confidence"] = float(sector_resolution.get("match_confidence") or 0.0)
        response["raw_sector_query"] = str(sector_resolution.get("requested_name") or sector_name or query)
        return response

    client = get_tushare_client()
    try:
        with log_tool_call(
            "index_member",
            symbol=index_code,
            query=query,
            sector_name=resolved_name,
            limit=limit,
            match_confidence=sector_resolution.get("match_confidence"),
        ):
            raw = await client.index_member(index_code=index_code)
            payload = _df_to_payload(raw)
            if isinstance(payload, list):
                payload = payload[:limit]
            if payload in (None, [], {}):
                return _timed_response(
                    symbol=index_code,
                    payload=payload,
                    error="empty result from Tushare",
                    source_api="index_member",
                    evidence_type="sector_constituents",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=index_code,
                payload=payload,
                error=None,
                source_api="index_member",
                evidence_type="sector_constituents",
                started_at=started_at,
                started_perf=started_perf,
            )
            response["sector_name"] = resolved_name
            response["match_confidence"] = float(sector_resolution.get("match_confidence") or 0.0)
            response["raw_sector_query"] = str(sector_resolution.get("requested_name") or sector_name or query)
            response["candidate_sector_names"] = list(sector_resolution.get("candidate_sector_names") or [])
            return response
    except TushareClientError as exc:
        return _timed_response(
            symbol=index_code,
            payload={},
            error=str(exc),
            source_api="index_member",
            evidence_type="sector_constituents",
            started_at=started_at,
            started_perf=started_perf,
        )
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=index_code,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api="index_member",
            evidence_type="sector_constituents",
            started_at=started_at,
            started_perf=started_perf,
        )


async def _run_fund_list_tool(
    *,
    query: str = "",
    symbol: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    try:
        with log_tool_call("fund_basic", symbol=symbol, query=query, limit=limit):
            rows, top_name, error, warning, source_api = await _search_fund_candidates(
                query=query,
                symbol=symbol,
                limit=limit,
            )
            if error:
                return _timed_response(
                    symbol=symbol or query,
                    payload={},
                    error=error,
                    source_api=source_api,
                    evidence_type="fund_basic",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            if not rows:
                return _timed_response(
                    symbol=symbol or query,
                    payload=[],
                    error="empty result from Tushare",
                    source_api=source_api,
                    evidence_type="fund_basic",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=str(rows[0].get("ts_code") or query),
                payload=rows,
                error=None,
                source_api=source_api,
                evidence_type="fund_basic",
                started_at=started_at,
                started_perf=started_perf,
            )
            if top_name:
                response["fund_name"] = top_name
            if warning:
                response["warning"] = warning
            return response
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=symbol or query,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api="fund_basic",
            evidence_type="fund_basic",
            started_at=started_at,
            started_perf=started_perf,
        )


async def _run_fund_data_tool(
    method_name: str,
    *,
    query: str = "",
    symbol: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    fund_name, resolved_symbol, resolve_error, resolve_warning = await _resolve_fund_symbol(
        query=query,
        symbol=symbol,
    )
    if not resolved_symbol:
        response = _timed_response(
            symbol=symbol or query,
            payload={},
            error=resolve_error or "unable to resolve fund symbol",
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )
        if resolve_warning:
            response["warning"] = resolve_warning
        return response

    client = get_tushare_client()
    try:
        with log_tool_call(method_name, symbol=resolved_symbol, query=query, fund_name=fund_name, limit=limit):
            method = getattr(client, method_name)
            raw = await method(ts_code=resolved_symbol)
            payload = _df_to_payload(raw)
            if isinstance(payload, list) and limit > 0:
                payload = payload[:limit]
            if payload in (None, [], {}):
                return _timed_response(
                    symbol=resolved_symbol,
                    payload=payload,
                    error="empty result from Tushare",
                    source_api=method_name,
                    evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=resolved_symbol,
                payload=payload,
                error=None,
                source_api=method_name,
                evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
                started_at=started_at,
                started_perf=started_perf,
            )
            if fund_name:
                response["fund_name"] = fund_name
            if resolve_warning:
                response["warning"] = resolve_warning
            return response
    except TushareClientError as exc:
        return _timed_response(
            symbol=resolved_symbol,
            payload={},
            error=str(exc),
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=resolved_symbol,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )


@tool
async def get_stock_basic_info(symbol: str = "", query: str = "") -> dict[str, Any]:
    """Get stock basic information from Tushare. You can pass a ts_code in symbol or a natural-language stock question in query."""
    return await _run_tool(
        "stock_basic",
        symbol=symbol,
        query=query,
        fields="ts_code,symbol,name,area,industry,list_date,market",
    )


@tool
async def get_daily_bars(symbol: str = "", query: str = "", limit: int = 20) -> dict[str, Any]:
    """Get recent daily bar data from Tushare. You can pass a ts_code in symbol or a natural-language stock question in query."""
    return await _run_tool("daily", symbol=symbol, query=query, limit=limit)


@tool
async def get_fina_indicator(symbol: str = "", query: str = "", limit: int = 4) -> dict[str, Any]:
    """Get recent financial indicators from Tushare. You can pass a ts_code in symbol or a natural-language stock question in query."""
    return await _run_tool("fina_indicator", symbol=symbol, query=query, limit=limit)


@tool
async def get_income(symbol: str = "", query: str = "", limit: int = 2) -> dict[str, Any]:
    """Get income statement data from Tushare. You can pass a ts_code in symbol or a natural-language stock question in query."""
    return await _run_tool("income", symbol=symbol, query=query, limit=limit)


@tool
async def get_balance_sheet(symbol: str = "", query: str = "", limit: int = 2) -> dict[str, Any]:
    """Get balance sheet data from Tushare. You can pass a ts_code in symbol or a natural-language stock question in query."""
    return await _run_tool("balancesheet", symbol=symbol, query=query, limit=limit)


@tool
async def get_cashflow(symbol: str = "", query: str = "", limit: int = 2) -> dict[str, Any]:
    """Get cashflow statement data from Tushare. You can pass a ts_code in symbol or a natural-language stock question in query."""
    return await _run_tool("cashflow", symbol=symbol, query=query, limit=limit)


@tool
async def get_market_bars(symbol: str = "", query: str = "", limit: int = 30) -> dict[str, Any]:
    """Get recent market bars using Tushare pro_bar. Useful for today/recent market questions."""
    return await _run_market_tool(symbol=symbol, query=query, limit=limit)


@tool
async def get_index_bars(symbol: str = "", query: str = "", limit: int = 30) -> dict[str, Any]:
    """Get index market bars from Tushare. Supports common A-share indices by natural language or ts_code."""
    return await _run_index_tool(symbol=symbol, query=query, limit=limit)


@tool
async def get_sector_snapshot(query: str = "", sector_name: str = "") -> dict[str, Any]:
    """Get sector or industry snapshot using Tushare SW industry daily data."""
    return await _run_sector_snapshot_tool(query=query, sector_name=sector_name)


@tool
async def get_sector_constituents(query: str = "", sector_name: str = "", limit: int = 20) -> dict[str, Any]:
    """Get representative constituents for a sector or industry index."""
    return await _run_sector_constituents_tool(query=query, sector_name=sector_name, limit=limit)


@tool
async def get_fund_basic_info(symbol: str = "", query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search listed public funds and ETFs using Tushare fund_basic (incl. market=E for ETF universe)."""
    return await _run_fund_list_tool(symbol=symbol, query=query, limit=limit)


@tool
async def get_fund_nav(symbol: str = "", query: str = "", limit: int = 10) -> dict[str, Any]:
    """Get recent fund NAV data from Tushare fund_nav."""
    return await _run_fund_data_tool("fund_nav", symbol=symbol, query=query, limit=limit)


@tool
async def get_fund_market_bars(symbol: str = "", query: str = "", limit: int = 20) -> dict[str, Any]:
    """Get recent ETF daily bars from Tushare fund_daily."""
    return await _run_fund_data_tool("fund_daily", symbol=symbol, query=query, limit=limit)


@tool
async def get_fund_share(symbol: str = "", query: str = "", limit: int = 10) -> dict[str, Any]:
    """Get fund or ETF share/size data from Tushare fund_share."""
    return await _run_fund_data_tool("fund_share", symbol=symbol, query=query, limit=limit)


@tool
async def search_web_news(query: str = "", max_results: int = 5, freshness_days: int = 7) -> dict[str, Any]:
    """Search recent finance web/news pages for catalyst clues. Use as supplementary evidence only; do not replace Tushare market data."""
    return await _run_web_news_search_tool(
        query=query,
        max_results=max_results,
        freshness_days=freshness_days,
    )


def get_tushare_toolkit() -> list[Any]:
    return [
        get_stock_basic_info,
        get_daily_bars,
        get_market_bars,
        get_index_bars,
        get_sector_snapshot,
        get_sector_constituents,
        get_fund_basic_info,
        get_fund_nav,
        get_fund_market_bars,
        get_fund_share,
        get_fina_indicator,
        get_income,
        get_balance_sheet,
        get_cashflow,
        search_web_news,
    ]
