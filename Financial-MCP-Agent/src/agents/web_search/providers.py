from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any

from src.agents.web_search.models import SearchRequest


async def tavily_search(request: SearchRequest, *, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise RuntimeError("missing TAVILY_API_KEY")
    payload = {
        "api_key": api_key,
        "query": request.query,
        "max_results": max(1, min(request.max_results, 10)),
        "search_depth": "basic",
        "topic": "finance",
        "include_answer": False,
        "include_raw_content": False,
    }
    if request.include_domains:
        payload["include_domains"] = request.include_domains
    if request.exclude_domains:
        payload["exclude_domains"] = request.exclude_domains

    def _invoke():
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=max(1, request.timeout_ms / 1000)) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")

    data = await asyncio.to_thread(_invoke)
    return list(data.get("results") or [])


async def ddgs_search(request: SearchRequest) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    def _invoke():
        return list(
            DDGS().text(
                query=request.query,
                max_results=max(1, min(request.max_results, 8)),
                region="cn-zh",
                safesearch="off",
            )
        )

    return await asyncio.to_thread(_invoke)


__all__ = ["ddgs_search", "tavily_search"]
