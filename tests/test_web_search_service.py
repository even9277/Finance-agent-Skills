import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.web_search.config import WebSearchSettings  # noqa: E402
from src.agents.web_search.service import execute_web_search, _reset_web_search_runtime_state  # noqa: E402
from src.agents.web_search.source_policy import SourcePolicy  # noqa: E402


def test_web_search_service_falls_back_from_tavily_to_ddgs(monkeypatch):
    _reset_web_search_runtime_state()

    async def fake_tavily(request, *, api_key):
        raise RuntimeError("quota")

    async def fake_ddgs(request):
        return [{"title": "贵州茅台公告", "url": "https://www.cninfo.com.cn/new", "body": "公告摘要"}]

    monkeypatch.setattr("src.agents.web_search.service.tavily_search", fake_tavily)
    monkeypatch.setattr("src.agents.web_search.service.ddgs_search", fake_ddgs)
    payload = asyncio.run(
        execute_web_search(
            query="贵州茅台为什么跌",
            settings=WebSearchSettings(provider="tavily", tavily_api_key="fake"),
            policy=SourcePolicy(allowed_domains=["cninfo.com.cn"]),
        )
    )
    assert payload["ok"] is True
    assert payload["provider"] == "duckduckgo"
    assert "fallback_to_duckduckgo" in payload["warnings"]


def test_web_search_service_uses_runtime_cache(monkeypatch):
    _reset_web_search_runtime_state()
    calls = {"ddgs": 0}

    async def fake_ddgs(request):
        calls["ddgs"] += 1
        return [{"title": "上交所公告", "url": "https://www.sse.com.cn/news", "body": "公告摘要"}]

    monkeypatch.setattr("src.agents.web_search.service.ddgs_search", fake_ddgs)
    settings = WebSearchSettings(provider="duckduckgo", cache_ttl_min=15)
    policy = SourcePolicy(allowed_domains=["sse.com.cn"])

    first = asyncio.run(
        execute_web_search(
            query="上证指数今日异动",
            requires_web_news=True,
            settings=settings,
            policy=policy,
        )
    )
    second = asyncio.run(
        execute_web_search(
            query="上证指数今日异动",
            requires_web_news=True,
            settings=settings,
            policy=policy,
        )
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["cache_hit"] is True
    assert calls["ddgs"] == 1


def test_web_search_service_rate_limits_before_provider_call(monkeypatch):
    _reset_web_search_runtime_state()
    calls = {"ddgs": 0}

    async def fake_ddgs(request):
        calls["ddgs"] += 1
        return [{"title": "公告", "url": "https://www.cninfo.com.cn/new", "body": "公告摘要"}]

    monkeypatch.setattr("src.agents.web_search.service.ddgs_search", fake_ddgs)
    settings = WebSearchSettings(provider="duckduckgo", cache_ttl_min=0, rate_limit_per_min=1)
    policy = SourcePolicy(allowed_domains=["cninfo.com.cn"])

    ok_payload = asyncio.run(
        execute_web_search(
            query="贵州茅台最新公告",
            requires_web_news=True,
            settings=settings,
            policy=policy,
        )
    )
    limited_payload = asyncio.run(
        execute_web_search(
            query="宁德时代最新公告",
            requires_web_news=True,
            settings=settings,
            policy=policy,
        )
    )

    assert ok_payload["ok"] is True
    assert limited_payload["ok"] is False
    assert limited_payload["error"] == "web_search_rate_limited"
    assert calls["ddgs"] == 1
