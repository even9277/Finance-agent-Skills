import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.web_search.source_policy import SourcePolicy, normalize_domain  # noqa: E402


def test_source_policy_allows_subdomains_and_blocks_explicit_domain():
    policy = SourcePolicy(allowed_domains=["cninfo.com.cn"], blocked_domains=["bad.example"])
    assert policy.domain_allowed("http://www.cninfo.com.cn/new/index")
    assert not policy.domain_allowed("https://bad.example/x")


def test_source_policy_marks_official_domains():
    policy = SourcePolicy(official_domains=["sse.com.cn"])
    assert normalize_domain("https://www.sse.com.cn/disclosure") == "sse.com.cn"
    assert policy.source_type("https://www.sse.com.cn/disclosure") == "official"
