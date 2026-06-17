from backend.integrations.redis.key_builder import KeyBuilder
from backend.services.report.command_hasher import compute_query_hash, normalize_command


def test_normalize_command_should_collapse_whitespace():
    assert normalize_command("  帮我   分析\t茅台\n") == "帮我 分析 茅台"


def test_query_hash_should_be_stable_for_whitespace_differences():
    assert compute_query_hash("  帮我分析茅台  ") == compute_query_hash("帮我分析茅台")


def test_query_hash_should_differ_for_different_commands():
    assert compute_query_hash("分析茅台") != compute_query_hash("分析腾讯")


def test_report_idempotency_key_should_not_include_stock_code():
    key = KeyBuilder("dev").report_idempotency_by_user_query("u1", "abc123")
    assert key == "finagent:dev:report:idempotency:u1:abc123"
