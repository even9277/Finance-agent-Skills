"""冻结五个金融 SOP Skill 的四层资产与机器合同。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
SKILLS_ROOT = AGENT_ROOT / "src" / "skills"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402

SKILL_NAMES = (
    "stock-first-pass",
    "fund-compare",
    "etf-screen",
    "sector-hotspot-brief",
    "market-move-explain",
)
REQUIRED_SECTIONS = (
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
)
REQUIRED_SPEC_FIELDS = (
    "skill_name",
    "skill_family",
    "version",
    "execution_policy",
    "depends_on_tools",
    "min_tool_schema_version",
    "output_schema_version",
    "skill_md_section_map",
    "requires_web_news",
    "route_metadata",
    "input_contract",
    "allowed_tools",
    "tool_plan_steps",
    "required_evidence",
    "output_template",
    "degrade_policy",
    "concurrency",
)
REQUIRED_ROUTE_FIELDS = (
    "when_to_use",
    "when_not_to_use",
    "positive_examples",
    "negative_examples",
    "supported_entity_types",
)
REQUIRED_REFERENCE_FIELDS = (
    "title",
    "category",
    "stages",
    "tags",
    "evidence_types",
    "source_note",
    "updated_at",
)
KNOWN_EVIDENCE_TYPES = {
    "stock_basic",
    "stock_market",
    "financial_indicator",
    "income_statement",
    "balance_sheet",
    "cashflow_statement",
    "fund_basic",
    "etf_basic",
    "fund_nav",
    "fund_daily",
    "fund_share",
    "index_daily",
    "sector_snapshot",
    "sector_constituents",
    "web_news",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    """读取 YAML mapping，并把资产格式错误报告为合同失败。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} root must be a mapping"
    return payload


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """读取 Markdown YAML frontmatter。"""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, flags=re.S)
    assert match, f"{path} missing YAML frontmatter"
    payload = yaml.safe_load(match.group(1))
    assert isinstance(payload, dict), f"{path} frontmatter must be a mapping"
    return payload


def _required_evidence_types(payload: dict[str, Any]) -> set[str]:
    """汇总机器合同声明的所有证据类型。"""
    values: set[str] = set()
    for key in ("must_have_all", "must_have_any", "per_symbol_must_have_any"):
        values.update(str(item) for item in payload.get(key) or [])
    return values


@pytest.mark.contract
@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_financial_skill_asset_has_complete_human_and_machine_contract(skill_name: str) -> None:
    """每个 Skill 必须同时具备完整说明、spec、references 和 cases。"""
    skill_dir = SKILLS_ROOT / skill_name
    skill_path = skill_dir / "SKILL.md"
    spec_path = skill_dir / "skill_spec.yaml"
    cases_path = skill_dir / "tests" / "cases.md"

    assert skill_path.is_file(), f"{skill_name} missing SKILL.md"
    assert spec_path.is_file(), f"{skill_name} missing skill_spec.yaml"
    assert cases_path.is_file(), f"{skill_name} missing tests/cases.md"

    markdown = skill_path.read_text(encoding="utf-8")
    frontmatter = _read_frontmatter(skill_path)
    spec = _read_yaml(spec_path)
    missing_sections = [section for section in REQUIRED_SECTIONS if f"## {section}" not in markdown]
    missing_fields = [field for field in REQUIRED_SPEC_FIELDS if field not in spec]

    assert frontmatter.get("name") == skill_name
    assert str(frontmatter.get("description") or "").strip()
    assert not missing_sections, f"{skill_name} missing sections: {missing_sections}"
    assert not missing_fields, f"{skill_name} missing spec fields: {missing_fields}"
    assert spec["skill_name"] == skill_name
    assert spec["skill_family"] == "financial-sop"
    assert set(frontmatter.get("allowed_tools") or []) == set(spec["allowed_tools"])
    assert set(spec["depends_on_tools"]) <= set(spec["allowed_tools"])
    assert isinstance(spec["requires_web_news"], bool)
    assert spec["requires_web_news"] == ("search_web_news" in set(spec["allowed_tools"]))
    assert set(REQUIRED_SECTIONS) <= set(spec["skill_md_section_map"].values())
    assert set(REQUIRED_ROUTE_FIELDS) <= set(spec["route_metadata"])
    assert spec["input_contract"].get("required_slots")


@pytest.mark.contract
@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_financial_skill_tools_evidence_and_references_are_closed(skill_name: str) -> None:
    """Skill 只能使用治理目录工具、已知证据和目录内的分阶段 reference。"""
    skill_dir = SKILLS_ROOT / skill_name
    spec = _read_yaml(skill_dir / "skill_spec.yaml")
    executable_tools = {policy.tool_name for policy in ToolGovernanceCatalog.default().policies}
    # Web News 在对应实现里程碑加入同一治理目录；测试先冻结这一权限边界。
    executable_tools.add("search_web_news")

    allowed_tools = set(str(item) for item in spec.get("allowed_tools") or [])
    assert allowed_tools
    assert allowed_tools <= executable_tools
    assert all(step.get("tool") in allowed_tools for step in spec.get("tool_plan_steps") or [])

    evidence_types = _required_evidence_types(spec.get("required_evidence") or {})
    assert evidence_types
    assert evidence_types <= KNOWN_EVIDENCE_TYPES

    references = sorted((skill_dir / "references").rglob("*.md"))
    assert references, f"{skill_name} must provide at least one reference"
    for reference in references:
        reference.resolve().relative_to(skill_dir.resolve())
        metadata = _read_frontmatter(reference)
        missing = [field for field in REQUIRED_REFERENCE_FIELDS if field not in metadata]
        assert not missing, f"{reference} missing reference metadata: {missing}"
        assert metadata["category"] == "financial_sop_reference"
        assert set(metadata["stages"]) <= {"rewrite", "planner", "synthesis"}
        assert metadata["stages"]
        assert metadata["tags"]
        assert set(metadata["evidence_types"]) <= KNOWN_EVIDENCE_TYPES
