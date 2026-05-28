import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.web_search.query_builder import classify_search_trigger, minimize_query  # noqa: E402


def test_search_trigger_respects_skill_requires_web_news():
    assert classify_search_trigger("普通问题", requires_web_news=True) == "required"


def test_search_trigger_detects_news_intent():
    assert classify_search_trigger("贵州茅台今天为什么跌，有什么消息") == "optional"


def test_query_builder_removes_sensitive_terms_and_adds_news_context():
    query, warnings = minimize_query("帮我分析贵州茅台，我的持仓金额和 token 不要泄露", freshness_days=2)
    assert "token" not in query.lower()
    assert "持仓" not in query
    assert "公告" in query
    assert "今日" in query
    assert "forbidden_term_removed" in warnings
