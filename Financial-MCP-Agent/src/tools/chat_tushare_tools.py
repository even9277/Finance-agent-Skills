from __future__ import annotations

from datetime import datetime, timezone
import re
import time
from typing import Any
import uuid

try:
    # 本项目仅依赖 langchain-core；从稳定的核心入口导入，避免要求安装完整 langchain。
    from langchain_core.tools import tool
except Exception:  # pragma: no cover - 仅供未安装 LangChain 的轻量环境
    def tool(func=None, *args, **kwargs):
        """在可选依赖缺失时保留被装饰函数，兼容 ``@tool`` 与 ``@tool()``。"""
        if callable(func):
            return func

        def _decorator(inner_func):
            return inner_func

        return _decorator

from src.tools.tushare_client import TushareClientError, get_tushare_client
from src.tools.skill_trace import log_tool_call, new_evidence_id

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
_FUND_GENERIC_TERMS = ("基金", "etf", "lof", "qdii", "联接基金", "联接")
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
    "etf_basic": "fund_basic",
    "fund_nav": "fund_nav",
    "fund_daily": "fund_daily",
    "fund_share": "fund_share",
}


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _new_tool_result_id() -> str:
    return f"toolr_{uuid.uuid4().hex}"


def _to_tushare_ts_code(symbol: str) -> str:
    raw = (symbol or "").strip()
    if not raw:
        return ""

    upper = raw.upper()
    if "." in upper and upper.endswith((".SH", ".SZ", ".BJ")) and len(upper.split(".", 1)[0]) == 6:
        return upper

    lowered = raw.lower()
    if lowered.startswith(("sh.", "sz.", "bj.")):
        exchange, code = lowered.split(".", 1)
        return f"{code}.{exchange.upper()}"

    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 6:
        if digits.startswith("6"):
            return f"{digits}.SH"
        if digits.startswith(("0", "3")):
            return f"{digits}.SZ"
        if digits.startswith(("4", "8")):
            return f"{digits}.BJ"
    return upper


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
) -> dict[str, Any]:
    return {
        "ok": error is None,
        "source": "tushare",
        "source_api": source_api,
        "evidence_type": evidence_type,
        "evidence_id": new_evidence_id(),
        "tool_result_id": _new_tool_result_id(),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "cache_hit": cache_hit,
        "retry_count": retry_count,
        "trade_date": _pick_trade_date(payload),
        "data_time": _now_text(),
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


async def _resolve_sector_code(query: str = "", sector_name: str = "") -> tuple[str | None, str | None]:
    requested = _first_non_empty(sector_name, query)
    if not requested:
        return None, None

    client = get_tushare_client()
    try:
        data = await client.index_classify(src="SW2021")
        payload = _df_to_payload(data)
        if not isinstance(payload, list):
            return None, None
    except Exception:
        return None, None

    normalized_request = requested.replace("板块", "").replace("行业", "").strip()
    for row in payload:
        if not isinstance(row, dict):
            continue
        industry_name = str(row.get("industry_name") or "").strip()
        index_code = str(row.get("index_code") or "").strip()
        if not industry_name or not index_code:
            continue
        if normalized_request in industry_name or industry_name in requested:
            return industry_name, index_code
    return None, None


async def _resolve_symbol(query: str = "", symbol: str = "") -> tuple[str | None, str | None, str | None]:
    clean_symbol = (symbol or "").strip()
    if clean_symbol:
        clean_symbol = _to_tushare_ts_code(clean_symbol)
        return None, clean_symbol, None

    clean_query = (query or "").strip()
    if not clean_query:
        return None, None, "missing stock query"

    try:
        from backend.services.stock_resolver import resolve_stock
    except Exception as exc:  # pragma: no cover - import safety
        return None, None, f"stock resolver unavailable: {exc}"

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
    prefer_etf: bool = False,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    clean_symbol = _to_tushare_ts_code(symbol)
    clean_query = (query or "").strip()
    client = get_tushare_client()
    rows: list[dict[str, Any]] = []

    try:
        if clean_symbol:
            if prefer_etf:
                try:
                    etf_raw = await client.etf_basic(ts_code=clean_symbol)
                    rows.extend(_df_to_payload(etf_raw) or [])
                except Exception:
                    pass
            fund_raw = await client.fund_basic(ts_code=clean_symbol)
            rows.extend(_df_to_payload(fund_raw) or [])
        else:
            if prefer_etf:
                try:
                    etf_raw = await client.etf_basic(list_status="L")
                    rows.extend(_df_to_payload(etf_raw) or [])
                except Exception:
                    pass
            fund_raw = await client.fund_basic(market="E", status="L")
            rows.extend(_df_to_payload(fund_raw) or [])
    except TushareClientError as exc:
        return [], None, str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return [], None, f"Unexpected error: {exc}"

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
                return [], None, "unable to confidently resolve fund symbol"

    if limit > 0:
        normalized_rows = normalized_rows[:limit]

    top_name = _first_non_empty(
        normalized_rows[0].get("name") if normalized_rows else None,
        normalized_rows[0].get("csname") if normalized_rows else None,
        normalized_rows[0].get("extname") if normalized_rows else None,
    )
    return normalized_rows, top_name, None


async def _resolve_fund_symbol(
    *,
    query: str = "",
    symbol: str = "",
    prefer_etf: bool = False,
) -> tuple[str | None, str | None, str | None]:
    candidates, top_name, error = await _search_fund_candidates(
        query=query,
        symbol=symbol,
        prefer_etf=prefer_etf,
        limit=5,
    )
    if error:
        return None, None, error
    if not candidates:
        return None, None, "unable to resolve fund symbol"
    top = candidates[0]
    return top_name, str(top.get("ts_code") or ""), None


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
    resolved_name, index_code = await _resolve_sector_code(query=query, sector_name=sector_name)
    if not index_code:
        return _timed_response(
            symbol=sector_name or query,
            payload={},
            error="unable to resolve sector index",
            source_api="sw_daily",
            evidence_type="sector_snapshot",
            started_at=started_at,
            started_perf=started_perf,
        )

    client = get_tushare_client()
    try:
        with log_tool_call("sw_daily", symbol=index_code, query=query, sector_name=resolved_name):
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
    resolved_name, index_code = await _resolve_sector_code(query=query, sector_name=sector_name)
    if not index_code:
        return _timed_response(
            symbol=sector_name or query,
            payload={},
            error="unable to resolve sector index",
            source_api="index_member",
            evidence_type="sector_constituents",
            started_at=started_at,
            started_perf=started_perf,
        )

    client = get_tushare_client()
    try:
        with log_tool_call("index_member", symbol=index_code, query=query, sector_name=resolved_name, limit=limit):
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
    prefer_etf: bool = False,
) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    try:
        with log_tool_call("etf_basic" if prefer_etf else "fund_basic", symbol=symbol, query=query, limit=limit):
            rows, top_name, error = await _search_fund_candidates(
                query=query,
                symbol=symbol,
                prefer_etf=prefer_etf,
                limit=limit,
            )
            if error:
                return _timed_response(
                    symbol=symbol or query,
                    payload={},
                    error=error,
                    source_api="etf_basic" if prefer_etf else "fund_basic",
                    evidence_type="fund_basic",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            if not rows:
                return _timed_response(
                    symbol=symbol or query,
                    payload=[],
                    error="empty result from Tushare",
                    source_api="etf_basic" if prefer_etf else "fund_basic",
                    evidence_type="fund_basic",
                    started_at=started_at,
                    started_perf=started_perf,
                )
            response = _timed_response(
                symbol=str(rows[0].get("ts_code") or query),
                payload=rows,
                error=None,
                source_api="etf_basic" if prefer_etf else "fund_basic",
                evidence_type="fund_basic",
                started_at=started_at,
                started_perf=started_perf,
            )
            if top_name:
                response["fund_name"] = top_name
            return response
    except Exception as exc:  # pragma: no cover
        return _timed_response(
            symbol=symbol or query,
            payload={},
            error=f"Unexpected error: {exc}",
            source_api="etf_basic" if prefer_etf else "fund_basic",
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
    prefer_etf: bool = False,
) -> dict[str, Any]:
    started_at = _now_text()
    started_perf = time.perf_counter()
    fund_name, resolved_symbol, resolve_error = await _resolve_fund_symbol(
        query=query,
        symbol=symbol,
        prefer_etf=prefer_etf,
    )
    if not resolved_symbol:
        return _timed_response(
            symbol=symbol or query,
            payload={},
            error=resolve_error or "unable to resolve fund symbol",
            source_api=method_name,
            evidence_type=_TOOL_EVIDENCE_TYPE_MAP.get(method_name, "unknown"),
            started_at=started_at,
            started_perf=started_perf,
        )

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
    """Search listed public funds using Tushare fund_basic. Useful for ETF/fund recommendation and discovery."""
    return await _run_fund_list_tool(symbol=symbol, query=query, limit=limit, prefer_etf=False)


@tool
async def get_etf_basic_info(symbol: str = "", query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search ETF metadata using Tushare etf_basic when available."""
    return await _run_fund_list_tool(symbol=symbol, query=query, limit=limit, prefer_etf=True)


@tool
async def get_fund_nav(symbol: str = "", query: str = "", limit: int = 10) -> dict[str, Any]:
    """Get recent fund NAV data from Tushare fund_nav."""
    return await _run_fund_data_tool("fund_nav", symbol=symbol, query=query, limit=limit, prefer_etf=False)


@tool
async def get_fund_market_bars(symbol: str = "", query: str = "", limit: int = 20) -> dict[str, Any]:
    """Get recent ETF daily bars from Tushare fund_daily."""
    return await _run_fund_data_tool("fund_daily", symbol=symbol, query=query, limit=limit, prefer_etf=True)


@tool
async def get_fund_share(symbol: str = "", query: str = "", limit: int = 10) -> dict[str, Any]:
    """Get fund or ETF share/size data from Tushare fund_share."""
    return await _run_fund_data_tool("fund_share", symbol=symbol, query=query, limit=limit, prefer_etf=False)


def get_tushare_toolkit() -> list[Any]:
    return [
        get_stock_basic_info,
        get_daily_bars,
        get_market_bars,
        get_index_bars,
        get_sector_snapshot,
        get_sector_constituents,
        get_fund_basic_info,
        get_etf_basic_info,
        get_fund_nav,
        get_fund_market_bars,
        get_fund_share,
        get_fina_indicator,
        get_income,
        get_balance_sheet,
        get_cashflow,
    ]
