from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@dataclass(slots=True)
class WebSearchSettings:
    enabled: bool = False
    shadow_mode: bool = True
    provider: str = "duckduckgo"
    timeout_ms: int = 4000
    max_results: int = 5
    default_lookback_days: int = 7
    cache_ttl_min: int = 15
    rate_limit_per_min: int = 20
    daily_quota: int = 100
    tavily_api_key: str = ""
    tavily_include_domains: list[str] = field(default_factory=list)
    tavily_exclude_domains: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "WebSearchSettings":
        return cls(
            enabled=os.getenv("ENABLE_WEB_SEARCH_V2", "false").strip().lower() in {"1", "true", "yes", "on"},
            shadow_mode=os.getenv("WEB_SEARCH_SHADOW_MODE", "true").strip().lower() in {"1", "true", "yes", "on"},
            provider=os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo").strip().lower(),
            timeout_ms=int(os.getenv("WEB_SEARCH_TIMEOUT_MS", "4000") or 4000),
            max_results=int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5") or 5),
            default_lookback_days=int(os.getenv("WEB_SEARCH_DEFAULT_LOOKBACK_DAYS", "7") or 7),
            cache_ttl_min=int(os.getenv("WEB_SEARCH_CACHE_TTL_MIN", "15") or 15),
            rate_limit_per_min=int(os.getenv("WEB_SEARCH_RATE_LIMIT_PER_MIN", "20") or 20),
            daily_quota=int(os.getenv("WEB_SEARCH_DAILY_QUOTA", "100") or 100),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            tavily_include_domains=_csv(os.getenv("TAVILY_INCLUDE_DOMAINS", "")),
            tavily_exclude_domains=_csv(os.getenv("TAVILY_EXCLUDE_DOMAINS", "")),
        )


__all__ = ["WebSearchSettings"]
