from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agents.web_search.models import WebSearchResult
from src.agents.web_search.source_policy import SourcePolicy, normalize_domain

_INJECTION_TERMS = (
    "ignore previous",
    "system prompt",
    "developer message",
    "泄露",
    "忽略上文",
    "调用工具",
)


def normalize_results(raw_results: list[dict[str, Any]], *, policy: SourcePolicy, max_results: int) -> list[WebSearchResult]:
    retrieved_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    seen: set[str] = set()
    normalized: list[WebSearchResult] = []
    for idx, item in enumerate(raw_results, start=1):
        url = str(item.get("url") or item.get("href") or "").strip()
        domain = normalize_domain(url)
        if not url or not domain or not policy.domain_allowed(domain):
            continue
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("content") or item.get("body") or item.get("snippet") or "").strip()
        key = f"{domain}:{title[:80]}"
        if key in seen:
            continue
        seen.add(key)
        haystack = f"{title}\n{snippet}".lower()
        normalized.append(
            WebSearchResult(
                title=title,
                url=url,
                domain=domain,
                snippet=snippet[:600],
                published_at=str(item.get("published_date") or item.get("date") or ""),
                retrieved_at=retrieved_at,
                source_type=policy.source_type(domain),
                score=float(item.get("score") or 0.0),
                rank=idx,
                injection_suspected=any(term in haystack for term in _INJECTION_TERMS),
                metadata={"raw_provider_keys": sorted(item.keys())[:12]},
            )
        )
        if len(normalized) >= max(1, max_results):
            break
    return normalized


__all__ = ["normalize_results"]
