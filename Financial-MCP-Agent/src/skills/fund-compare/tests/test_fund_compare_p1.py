from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml

from src.agents.skill_evidence import validate_evidence
from src.agents.skill_router_node import RouteTushare, route_chat_skill, user_explicit_sop_decision
from src.agents.skill_spec_planner import build_skill_tool_plan
from src.skills.skill_registry import get_skill_registry
from src.tools.chat_tushare_tools import _fund_semantic_tokens, _score_fund_row

FUND_COMPARE_ROOT = Path(__file__).resolve().parents[1]
P6_SPEC_FIELDS = {
    "depends_on_tools",
    "min_tool_schema_version",
    "output_schema_version",
    "skill_md_section_map",
    "requires_web_news",
}
REFERENCE_FRONTMATTER_FIELDS = {
    "title",
    "category",
    "stages",
    "evidence_types",
    "updated_at",
    "source",
}


def _read_reference_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    assert match, f"{path} missing YAML frontmatter"
    frontmatter = yaml.safe_load(match.group(1))
    assert isinstance(frontmatter, dict)
    return frontmatter


def test_fund_compare_user_explicit_decision_hits_financial_sop() -> None:
    route = user_explicit_sop_decision("fund-compare")
    assert route is not None
    assert route.route == "sop"
    assert route.skill_id == "fund-compare"
    assert route.execution_policy == "deterministic"


def test_fund_compare_router_now_stays_in_binary_mode() -> None:
    with patch(
        "src.agents.skill_router_node._llm_route",
        new=AsyncMock(return_value=RouteTushare(route="tushare")),
    ):
        route = asyncio.run(
            route_chat_skill(
                "请对比华安黄金ETF和博时黄金ETF，按收益、规模、费率和流动性给一个结构化结论",
                conversation_context="",
            )
        )
    assert route.route in {"tushare", "fallback"}
    assert route.skill_id is None


def test_fund_compare_planner_only_uses_spec_tools() -> None:
    registry = get_skill_registry(refresh=True)
    spec = registry.load_skill_spec("fund-compare")
    assert spec is not None

    plan = build_skill_tool_plan(
        skill_name="fund-compare",
        skill_spec=spec,
        user_message="对比华安黄金ETF和博时黄金ETF，哪个更适合我？",
        resolved_entities=["华安黄金ETF", "博时黄金ETF"],
    )
    assert plan.planner_type == "skill_planner"
    planned_tools = {item.tool_name for item in plan.tool_calls}
    assert planned_tools
    assert planned_tools.issubset(set(spec.get("allowed_tools") or []))
    assert "get_fund_basic_info" in planned_tools
    assert "get_fund_nav" in planned_tools


def test_fund_compare_p6_asset_metadata_is_parseable() -> None:
    registry = get_skill_registry(refresh=True)
    spec = registry.load_skill_spec("fund-compare")
    assert spec is not None

    assert P6_SPEC_FIELDS.issubset(spec)
    assert spec["depends_on_tools"] == spec["allowed_tools"]
    assert isinstance(spec["min_tool_schema_version"], str)
    assert isinstance(spec["output_schema_version"], str)
    assert spec["requires_web_news"] is False

    section_map = spec["skill_md_section_map"]
    assert isinstance(section_map, dict)
    for section in ("Purpose", "Workflow", "Evidence Rules", "Output Contract", "References"):
        assert section in set(section_map.values())

    for path in sorted((FUND_COMPARE_ROOT / "references").glob("*.md")):
        frontmatter = _read_reference_frontmatter(path)
        assert REFERENCE_FRONTMATTER_FIELDS.issubset(frontmatter)
        assert frontmatter["category"] == "financial_sop_reference"
        assert frontmatter["stages"] == ["fund_compare"]
        assert frontmatter["evidence_types"]


def test_fund_compare_planner_strips_question_suffix_from_subject() -> None:
    subjects = build_skill_tool_plan(
        skill_name="fund-compare",
        skill_spec=get_skill_registry(refresh=True).load_skill_spec("fund-compare") or {},
        user_message="易方达沪深300ETF和华泰柏瑞沪深300ETF有什么区别？",
    )
    queries = [item.arguments.get("query") for item in subjects.tool_calls if item.tool_name == "get_fund_basic_info"]
    assert "易方达沪深300ETF" in queries
    assert "华泰柏瑞沪深300ETF" in queries
    assert "华泰柏瑞沪深300ETF有什么区别" not in queries


def test_fund_compare_evidence_requires_two_symbols() -> None:
    registry = get_skill_registry(refresh=True)
    spec = registry.load_skill_spec("fund-compare")
    assert spec is not None

    response = {
        "messages": [
            type(
                "ToolMsg",
                (),
                {
                    "type": "tool",
                    "name": "get_fund_basic_info",
                    "content": json.dumps(
                        {
                            "ok": True,
                            "tool_result_id": "toolr_a",
                            "source_api": "fund_basic",
                            "evidence_type": "fund_basic",
                            "symbol": "518880.SH",
                            "payload": [{"ts_code": "518880.SH"}],
                        },
                        ensure_ascii=False,
                    ),
                },
            )(),
            type(
                "ToolMsg",
                (),
                {
                    "type": "tool",
                    "name": "get_fund_nav",
                    "content": json.dumps(
                        {
                            "ok": True,
                            "tool_result_id": "toolr_b",
                            "source_api": "fund_nav",
                            "evidence_type": "fund_nav",
                            "symbol": "518880.SH",
                            "payload": [{"ts_code": "518880.SH", "end_date": "20260331"}],
                        },
                        ensure_ascii=False,
                    ),
                },
            )(),
            type(
                "ToolMsg",
                (),
                {
                    "type": "tool",
                    "name": "get_fund_basic_info",
                    "content": json.dumps(
                        {
                            "ok": True,
                            "tool_result_id": "toolr_c",
                            "source_api": "fund_basic",
                            "evidence_type": "fund_basic",
                            "symbol": "159937.SZ",
                            "payload": [{"ts_code": "159937.SZ"}],
                        },
                        ensure_ascii=False,
                    ),
                },
            )(),
            type(
                "ToolMsg",
                (),
                {
                    "type": "tool",
                    "name": "get_fund_share",
                    "content": json.dumps(
                        {
                            "ok": True,
                            "tool_result_id": "toolr_d",
                            "source_api": "fund_share",
                            "evidence_type": "fund_share",
                            "symbol": "159937.SZ",
                            "payload": [{"ts_code": "159937.SZ", "end_date": "20260331"}],
                        },
                        ensure_ascii=False,
                    ),
                },
            )(),
        ]
    }

    result = validate_evidence(
        analysis_mode="fund_compare",
        resolved_symbol=None,
        response=response,
        skill_spec=spec,
    )
    assert result.evidence_ok is True
    assert len(result.accepted_evidences) == 4
    assert result.missing_evidence_reasons == []


def test_fund_semantic_tokens_keep_brand_and_theme() -> None:
    tokens = _fund_semantic_tokens("华安黄金ETF")
    assert "华安黄金" in tokens
    assert "华安" in tokens
    assert "黄金" in tokens
    assert "etf" not in tokens


def test_fund_scoring_prefers_true_gold_etf_over_generic_etf() -> None:
    target_row = {
        "name": "华安易富黄金ETF",
        "management": "华安基金",
        "benchmark": "黄金现货合约",
    }
    wrong_row = {
        "name": "货币ETF易方达",
        "management": "易方达基金",
        "benchmark": "货币市场工具",
    }
    target_score, target_matches = _score_fund_row(target_row, "华安黄金ETF")
    wrong_score, wrong_matches = _score_fund_row(wrong_row, "华安黄金ETF")

    assert target_matches >= 1
    assert wrong_matches == 0
    assert target_score > wrong_score
