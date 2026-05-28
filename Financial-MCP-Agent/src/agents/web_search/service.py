from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime
from typing import Any

from src.agents.web_search.config import WebSearchSettings
from src.agents.web_search.models import SearchRequest
from src.agents.web_search.postprocess import normalize_results
from src.agents.web_search.providers import ddgs_search, tavily_search
from src.agents.web_search.query_builder import classify_search_trigger, minimize_query
from src.agents.web_search.source_policy import SourcePolicy


_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_REQUEST_TIMESTAMPS: dict[str, list[float]] = {}
_DAILY_COUNTER: dict[tuple[str, str], int] = {}


def _today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _cache_key(request: SearchRequest, policy: SourcePolicy) -> tuple[Any, ...]:
    return (
        request.provider,
        request.query,
        request.max_results,
        request.freshness_days,
        tuple(sorted(policy.allowed_domains)),
        tuple(sorted(policy.blocked_domains)),
    )


def _get_cached(key: tuple[Any, ...], *, ttl_seconds: int) -> dict[str, Any] | None:
    if ttl_seconds <= 0:
        return None
    item = _CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at < time.time():
        _CACHE.pop(key, None)
        return None
    cached = {**payload, "cache_hit": True}
    warnings = list(cached.get("warnings") or [])
    if "cache_hit" not in warnings:
        warnings.append("cache_hit")
    cached["warnings"] = warnings
    return cached


def _put_cached(key: tuple[Any, ...], payload: dict[str, Any], *, ttl_seconds: int) -> None:
    if ttl_seconds <= 0 or not payload.get("ok"):
        return
    _CACHE[key] = (time.time() + ttl_seconds, {**payload, "cache_hit": False})


def _quota_error(
    *,
    provider: str,
    query: str,
    decision: str,
    warnings: list[str],
    started: float,
    error: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "provider": provider,
        "query_used": query,
        "results": [],
        "result_count": 0,
        "decision": decision,
        "error": error,
        "warnings": warnings,
        "cache_hit": False,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _reserve_quota(settings: WebSearchSettings, provider: str) -> str | None:
    now = time.time()
    window = now - 60
    timestamps = [item for item in _REQUEST_TIMESTAMPS.get(provider, []) if item >= window]
    if settings.rate_limit_per_min > 0 and len(timestamps) >= settings.rate_limit_per_min:
        _REQUEST_TIMESTAMPS[provider] = timestamps
        return "web_search_rate_limited"

    day_key = (_today_key(), provider)
    used_today = _DAILY_COUNTER.get(day_key, 0)
    if settings.daily_quota > 0 and used_today >= settings.daily_quota:
        return "web_search_daily_quota_exceeded"

    timestamps.append(now)
    _REQUEST_TIMESTAMPS[provider] = timestamps
    _DAILY_COUNTER[day_key] = used_today + 1
    return None


def _reset_web_search_runtime_state() -> None:
    _CACHE.clear()
    _REQUEST_TIMESTAMPS.clear()
    _DAILY_COUNTER.clear()


async def execute_web_search(
    *,
    query: str,
    max_results: int = 5,
    freshness_days: int = 7,
    requires_web_news: bool = False,
    settings: WebSearchSettings | None = None,
    policy: SourcePolicy | None = None,
) -> dict[str, Any]:
    settings = settings or WebSearchSettings.from_env()
    policy = policy or SourcePolicy.from_yaml()
    started = time.perf_counter()
    decision = classify_search_trigger(query, requires_web_news=requires_web_news)
    minimized_query, warnings = minimize_query(query, freshness_days=freshness_days)
    if decision == "skip":
        return {
            "ok": False,
            "provider": settings.provider,
            "query_used": minimized_query,
            "results": [],
            "result_count": 0,
            "decision": decision,
            "error": "web_search_skipped",
            "warnings": warnings,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }

    request = SearchRequest(
        query=minimized_query,
        max_results=max_results or settings.max_results,
        freshness_days=freshness_days or settings.default_lookback_days,
        provider=settings.provider,
        include_domains=settings.tavily_include_domains or policy.allowed_domains,
        exclude_domains=settings.tavily_exclude_domains or policy.blocked_domains,
        timeout_ms=settings.timeout_ms,
    )
    key = _cache_key(request, policy)
    cached = _get_cached(key, ttl_seconds=settings.cache_ttl_min * 60)
    if cached is not None:
        cached["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return cached

    quota_error = _reserve_quota(settings, request.provider)
    if quota_error:
        warnings.append(quota_error)
        return _quota_error(
            provider=request.provider,
            query=minimized_query,
            decision=decision,
            warnings=warnings,
            started=started,
            error=quota_error,
        )

    provider_used = request.provider
    try:
        if request.provider == "tavily":
            raw = await tavily_search(request, api_key=settings.tavily_api_key)
        elif request.provider in {"duckduckgo", "ddgs"}:
            provider_used = "duckduckgo"
            raw = await ddgs_search(request)
        else:
            raise RuntimeError(f"unsupported web search provider: {request.provider}")
    except Exception as exc:  # noqa: BLE001
        if request.provider == "tavily":
            provider_used = "duckduckgo"
            try:
                raw = await ddgs_search(request)
                warnings.append("fallback_to_duckduckgo")
            except Exception as fallback_exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "provider": provider_used,
                    "query_used": minimized_query,
                    "results": [],
                    "result_count": 0,
                    "decision": decision,
                    "error": f"web_search_failed: {exc}; fallback_failed: {fallback_exc}",
                    "warnings": warnings,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
        else:
            return {
                "ok": False,
                "provider": provider_used,
                "query_used": minimized_query,
                "results": [],
                "result_count": 0,
                "decision": decision,
                "error": f"web_search_failed: {exc}",
                "warnings": warnings,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }

    normalized = normalize_results(raw, policy=policy, max_results=max_results or settings.max_results)
    payload = {
        "ok": bool(normalized),
        "provider": provider_used,
        "query_used": minimized_query,
        "results": [asdict(item) for item in normalized],
        "result_count": len(normalized),
        "decision": decision,
        "source_policy": {
            "allowed_domains": policy.allowed_domains,
            "blocked_domains": policy.blocked_domains,
        },
        "injection_suspected": any(item.injection_suspected for item in normalized),
        "warnings": warnings,
        "cache_hit": False,
        "error": None if normalized else "no_usable_web_results",
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    _put_cached(key, payload, ttl_seconds=settings.cache_ttl_min * 60)
    return payload


__all__ = ["execute_web_search", "_reset_web_search_runtime_state"]
