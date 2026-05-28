from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SearchDecision = Literal["required", "optional", "skip"]


@dataclass(slots=True)
class SearchRequest:
    query: str
    max_results: int = 5
    freshness_days: int = 7
    provider: str = "tavily"
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    timeout_ms: int = 4000


@dataclass(slots=True)
class WebSearchResult:
    title: str
    url: str
    domain: str
    snippet: str = ""
    published_at: str = ""
    retrieved_at: str = ""
    source_type: str = "web"
    score: float = 0.0
    rank: int = 0
    injection_suspected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["SearchDecision", "SearchRequest", "WebSearchResult"]
