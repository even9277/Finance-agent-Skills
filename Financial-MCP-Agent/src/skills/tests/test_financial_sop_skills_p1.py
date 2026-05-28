from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.agents.skill_evidence import _TOOL_EVIDENCE_TYPES, validate_evidence
from src.agents.skill_spec_planner import build_skill_tool_plan
from src.skills.skill_registry import get_skill_registry
from src.tools.chat_tushare_tools import get_tushare_toolkit

SKILLS_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SKILL_SECTIONS = [
    "Purpose",
    "When to Use",
    "When Not to Use",
    "Required Inputs",
    "Workflow",
    "Tool Use Guide",
    "Evidence Rules",
    "Degrade Policy",
    "Output Contract",
    "References",
]
P6_SPEC_FIELDS = [
    "depends_on_tools",
    "min_tool_schema_version",
    "output_schema_version",
    "skill_md_section_map",
    "requires_web_news",
]
REFERENCE_FRONTMATTER_FIELDS = [
    "title",
    "category",
    "stages",
    "evidence_types",
    "updated_at",
    "source",
]

SKILL_CASES: dict[str, dict[str, Any]] = {
    "stock-first-pass": {
        "message": "帮我看下贵州茅台最近还值不值得继续跟踪？",
        "resolved_entities": ["600519.SH"],
        "expected_tools": {
            "get_stock_basic_info",
            "get_market_bars",
            "get_fina_indicator",
            "get_income",
        },
        "evidences": [
            ("get_stock_basic_info", "stock_basic", "600519.SH"),
            ("get_market_bars", "stock_market", "600519.SH"),
            ("get_fina_indicator", "financial_indicator", "600519.SH"),
            ("get_income", "income_statement", "600519.SH"),
        ],
    },
    "fund-compare": {
        "message": "对比华安黄金ETF和博时黄金ETF，哪个更适合我？",
        "resolved_entities": ["518880.SH", "159937.SZ"],
        "expected_tools": {
            "get_fund_basic_info",
            "get_fund_nav",
            "get_fund_market_bars",
            "get_fund_share",
        },
        "evidences": [
            ("get_fund_basic_info", "fund_basic", "518880.SH"),
            ("get_fund_nav", "fund_nav", "518880.SH"),
            ("get_fund_basic_info", "fund_basic", "159937.SZ"),
            ("get_fund_share", "fund_share", "159937.SZ"),
        ],
    },
    "etf-screen": {
        "message": "帮我筛几只黄金 ETF，偏稳一点。",
        "resolved_entities": [],
        "expected_tools": {
            "get_fund_basic_info",
            "get_fund_nav",
            "get_fund_market_bars",
            "get_fund_share",
        },
        "evidences": [
            ("get_fund_basic_info", "fund_basic", "518880.SH"),
            ("get_fund_nav", "fund_nav", "518880.SH"),
        ],
    },
    "sector-hotspot-brief": {
        "message": "半导体板块最近强不强，龙头是谁？",
        "resolved_entities": [],
        "skill_params": {"sector_name": "半导体", "effective_query": "半导体板块最近强不强，龙头是谁？"},
        "expected_tools": {
            "get_sector_snapshot",
            "get_sector_constituents",
            "get_index_bars",
        },
        "evidences": [
            ("get_sector_snapshot", "sector_snapshot", ""),
            ("get_sector_constituents", "sector_constituents", ""),
        ],
    },
    "market-move-explain": {
        "message": "贵州茅台今天为什么跌？",
        "resolved_entities": ["600519.SH"],
        "expected_tools": {
            "get_stock_basic_info",
            "get_market_bars",
            "search_web_news",
        },
        "evidences": [
            ("get_market_bars", "stock_market", "600519.SH"),
            ("search_web_news", "web_news", "600519.SH"),
        ],
    },
}


def _read_frontmatter(skill_name: str) -> dict[str, Any]:
    text = (SKILLS_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    assert match, f"{skill_name} SKILL.md missing frontmatter"
    payload = yaml.safe_load(match.group(1))
    assert isinstance(payload, dict)
    return payload


def _skill_markdown(skill_name: str) -> str:
    return (SKILLS_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")


def _read_markdown_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    assert match, f"{path} missing YAML frontmatter"
    payload = yaml.safe_load(match.group(1))
    assert isinstance(payload, dict), f"{path} frontmatter must be a mapping"
    return payload


def _tool_message(tool_name: str, evidence_type: str, symbol: str) -> Any:
    return type(
        "ToolMsg",
        (),
        {
            "type": "tool",
            "name": tool_name,
            "content": json.dumps(
                {
                    "ok": True,
                    "tool_result_id": f"toolr_{tool_name}_{symbol or 'na'}",
                    "source_api": evidence_type,
                    "evidence_type": evidence_type,
                    "symbol": symbol,
                    "payload": [{"ts_code": symbol or "NA", "trade_date": "20260506"}],
                },
                ensure_ascii=False,
            ),
        },
    )()


def _required_evidence_types(required_evidence: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("must_have_all", "must_have_any", "per_symbol_must_have_any"):
        values.update(str(item) for item in required_evidence.get(key) or [])
    return values


def test_sop_skill_markdown_contracts_match_specs() -> None:
    registry = get_skill_registry(refresh=True)
    executable_tool_names = {
        str(getattr(tool, "name", "") or getattr(tool, "__name__", ""))
        for tool in get_tushare_toolkit()
    }
    known_evidence_types = set(_TOOL_EVIDENCE_TYPES.values())

    for skill_name in SKILL_CASES:
        spec = registry.load_skill_spec(skill_name)
        assert spec is not None, f"{skill_name} missing skill_spec.yaml"
        frontmatter = _read_frontmatter(skill_name)
        markdown = _skill_markdown(skill_name)

        assert frontmatter.get("name") == skill_name
        assert frontmatter.get("description")
        for field in P6_SPEC_FIELDS:
            assert field in spec, f"{skill_name} missing {field}"
        assert spec["depends_on_tools"]
        assert set(spec["depends_on_tools"]).issubset(set(spec.get("allowed_tools") or []))
        assert isinstance(spec["min_tool_schema_version"], str)
        assert isinstance(spec["output_schema_version"], str)
        assert isinstance(spec["requires_web_news"], bool)
        assert spec["requires_web_news"] == ("search_web_news" in set(spec.get("allowed_tools") or []))

        section_map = spec["skill_md_section_map"]
        assert isinstance(section_map, dict)
        for section in REQUIRED_SKILL_SECTIONS:
            assert f"## {section}" in markdown, f"{skill_name} missing ## {section}"
            assert section in set(section_map.values()), f"{skill_name} section map missing {section}"

        allowed_tools = set(spec.get("allowed_tools") or [])
        assert allowed_tools
        assert allowed_tools.issubset(executable_tool_names)
        assert set(frontmatter.get("allowed_tools") or []) == allowed_tools

        for step in spec.get("tool_plan_steps") or []:
            assert step.get("tool") in allowed_tools

        evidence_types = _required_evidence_types(spec.get("required_evidence") or {})
        assert evidence_types
        assert evidence_types.issubset(known_evidence_types)

        for ref_path in re.findall(r"`(references/[^`]+\.md)`", markdown):
            full_path = SKILLS_ROOT / skill_name / ref_path
            assert full_path.exists(), f"missing reference {ref_path}"
            ref_frontmatter = _read_markdown_frontmatter(full_path)
            for field in REFERENCE_FRONTMATTER_FIELDS:
                assert field in ref_frontmatter, f"{ref_path} missing {field}"
            assert ref_frontmatter["title"]
            assert ref_frontmatter["category"] == "financial_sop_reference"
            assert ref_frontmatter["stages"]
            assert ref_frontmatter["evidence_types"]
            assert ref_frontmatter["updated_at"]
            assert ref_frontmatter["source"]


def test_sop_skill_plans_are_generated_from_machine_contracts() -> None:
    registry = get_skill_registry(refresh=True)

    for skill_name, case in SKILL_CASES.items():
        spec = registry.load_skill_spec(skill_name)
        assert spec is not None
        plan = build_skill_tool_plan(
            skill_name=skill_name,
            skill_spec=spec,
            user_message=case["message"],
            resolved_entities=case.get("resolved_entities") or [],
            skill_params=case.get("skill_params") or None,
        )

        planned_tools = {item.tool_name for item in plan.tool_calls}
        assert plan.planner_type == "skill_planner"
        assert planned_tools
        assert planned_tools.issubset(set(spec.get("allowed_tools") or []))
        assert case["expected_tools"].issubset(planned_tools)


def test_sop_skill_required_evidence_validates_in_strict_mode(monkeypatch: Any) -> None:
    monkeypatch.setenv("ENABLE_SKILL_EVIDENCE_VALIDATION", "1")
    registry = get_skill_registry(refresh=True)

    for skill_name, case in SKILL_CASES.items():
        spec = registry.load_skill_spec(skill_name)
        assert spec is not None
        response = {
            "messages": [
                _tool_message(tool_name, evidence_type, symbol)
                for tool_name, evidence_type, symbol in case["evidences"]
            ]
        }
        result = validate_evidence(
            analysis_mode=skill_name.replace("-", "_"),
            resolved_symbol=None,
            response=response,
            skill_spec=spec,
        )
        assert result.evidence_ok is True, result.missing_evidence_reasons
        assert result.accepted_evidences


def test_market_move_web_news_is_supplementary_evidence(monkeypatch: Any) -> None:
    monkeypatch.setenv("ENABLE_SKILL_EVIDENCE_VALIDATION", "1")
    registry = get_skill_registry(refresh=True)
    spec = registry.load_skill_spec("market-move-explain")
    assert spec is not None

    response = {
        "messages": [
            _tool_message("get_market_bars", "stock_market", "600519.SH"),
            _tool_message("search_web_news", "web_news", "600519.SH"),
        ]
    }
    result = validate_evidence(
        analysis_mode="market_move_explain",
        resolved_symbol=None,
        response=response,
        skill_spec=spec,
    )

    accepted_types = {item["evidence_type"] for item in result.accepted_evidences}
    assert result.evidence_ok is True
    assert "stock_market" in accepted_types
    assert "web_news" in accepted_types
    assert "web_news" not in set(spec["required_evidence"].get("must_have_any") or [])
