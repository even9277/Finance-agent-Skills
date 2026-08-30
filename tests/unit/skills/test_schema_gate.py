"""验证金融 SOP Skill schema gate 的通过与 fail-closed 行为。"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
SKILLS_ROOT = AGENT_ROOT / "src" / "skills"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.skills.lifecycle import SkillStatus  # noqa: E402
from src.skills.schema_gate import validate_skill, validate_skill_directory  # noqa: E402

SKILL_NAMES = (
    "stock-first-pass",
    "fund-compare",
    "etf-screen",
    "sector-hotspot-brief",
    "market-move-explain",
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


def _governed_tools() -> set[str]:
    """返回本里程碑允许的现有工具目录和已批准 Web News 名称。"""
    tools = {policy.tool_name for policy in ToolGovernanceCatalog.default().policies}
    tools.add("search_web_news")
    return tools


def _read_spec(skill_name: str) -> dict[str, Any]:
    """读取测试用 Skill spec mapping。"""
    payload = yaml.safe_load(
        (SKILLS_ROOT / skill_name / "skill_spec.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


@pytest.mark.unit
@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_all_financial_sop_directories_pass_typed_schema_gate(skill_name: str) -> None:
    """五类 Skill 四层资产必须得到类型化 spec 和稳定内容哈希。"""
    report = validate_skill_directory(
        SKILLS_ROOT / skill_name,
        allowed_tool_names=_governed_tools(),
        evidence_types=KNOWN_EVIDENCE_TYPES,
    )

    assert report.passed, report.issues
    assert report.status is SkillStatus.ACTIVE
    assert report.typed_spec is not None
    assert report.typed_spec.skill_name == skill_name
    assert len(report.spec_hash) == 64
    assert len(report.document_hash) == 64
    assert len(report.reference_hash) == 64


@pytest.mark.unit
def test_schema_gate_rejects_unknown_tool_and_evidence_without_expanding_permissions() -> None:
    """资产不能借 spec 声明扩大工具或证据治理目录。"""
    spec = copy.deepcopy(_read_spec("stock-first-pass"))
    spec["allowed_tools"].append("run_untrusted_script")
    spec["depends_on_tools"].append("run_untrusted_script")
    spec["tool_plan_steps"].append(
        {"step": "escape", "tool": "run_untrusted_script", "required": True, "arguments": {}}
    )
    spec["required_evidence"]["optional"] = ["model_guess"]

    report = validate_skill(
        spec,
        allowed_tool_names=_governed_tools(),
        evidence_types=KNOWN_EVIDENCE_TYPES,
        expected_skill_name="stock-first-pass",
    )

    assert report.passed is False
    assert report.status is SkillStatus.DISABLED
    assert {issue.code for issue in report.issues} == {
        "unknown_allowed_tool",
        "unknown_evidence_type",
    }


@pytest.mark.unit
def test_schema_gate_rejects_name_mismatch_and_incomplete_section_map() -> None:
    """目录身份和完整 SKILL 章节映射都属于发布前强约束。"""
    spec = copy.deepcopy(_read_spec("stock-first-pass"))
    spec["skill_name"] = "fund-compare"
    spec["skill_md_section_map"].pop("references")

    report = validate_skill(
        spec,
        allowed_tool_names=_governed_tools(),
        evidence_types=KNOWN_EVIDENCE_TYPES,
        expected_skill_name="stock-first-pass",
    )

    assert report.passed is False
    assert any(issue.code == "invalid_skill_spec" for issue in report.issues)


@pytest.mark.unit
def test_schema_gate_rejects_malformed_reference_frontmatter(tmp_path: Path) -> None:
    """缺少阶段和来源元数据的 reference 必须让整个 Skill fail closed。"""
    source_dir = SKILLS_ROOT / "stock-first-pass"
    target_dir = tmp_path / "stock-first-pass"
    target_dir.mkdir()
    (target_dir / "tests").mkdir()
    (target_dir / "references").mkdir()
    (target_dir / "SKILL.md").write_text(
        (source_dir / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (target_dir / "skill_spec.yaml").write_text(
        (source_dir / "skill_spec.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (target_dir / "tests" / "cases.md").write_text("# cases\n", encoding="utf-8")
    (target_dir / "references" / "bad.md").write_text(
        "---\ntitle: bad\ncategory: financial_sop_reference\n---\n# bad\n",
        encoding="utf-8",
    )

    report = validate_skill_directory(
        target_dir,
        allowed_tool_names=_governed_tools(),
        evidence_types=KNOWN_EVIDENCE_TYPES,
    )

    assert report.passed is False
    assert any(issue.code == "invalid_reference" for issue in report.issues)
