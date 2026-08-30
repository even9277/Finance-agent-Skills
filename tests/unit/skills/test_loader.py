"""验证 SkillLoader 的阶段视图、预算、artifact 和请求快照隔离。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
SKILLS_ROOT = AGENT_ROOT / "src" / "skills"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.skills.loader import SkillLoadError  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402

SKILL_NAMES = (
    "stock-first-pass",
    "fund-compare",
    "etf-screen",
    "sector-hotspot-brief",
    "market-move-explain",
)


def _copy_skill_assets(target_root: Path) -> None:
    """复制五类资产用于刷新隔离测试。"""
    for skill_name in SKILL_NAMES:
        shutil.copytree(SKILLS_ROOT / skill_name, target_root / skill_name)


@pytest.mark.unit
def test_loader_exposes_three_isolated_views_and_redacted_artifact() -> None:
    """三阶段只获得所需 spec 字段，artifact 不包含正文。"""
    loader = SkillRegistry().get_loader()

    rewrite = loader.load_for_rewrite("fund-compare", query="比较两只黄金 ETF")
    planner = loader.load_for_planner("fund-compare", query="比较两只黄金 ETF")
    synthesis = loader.load_for_synthesis("fund-compare", query="比较两只黄金 ETF")
    rewrite_artifact = rewrite.artifact()
    planner_artifact = planner.artifact()
    synthesis_artifact = synthesis.artifact()
    rewrite_spec = cast(dict[str, object], rewrite_artifact["spec_view"])
    planner_spec = cast(dict[str, object], planner_artifact["spec_view"])
    synthesis_spec = cast(dict[str, object], synthesis_artifact["spec_view"])

    assert rewrite.stage == "rewrite"
    assert planner.stage == "planner"
    assert synthesis.stage == "synthesis"
    assert "allowed_tools" not in rewrite_spec
    assert planner_spec["allowed_tools"]
    assert "output_template" in synthesis_spec
    assert "tool_plan_steps" not in synthesis_spec
    assert all("rewrite" in item.stages for item in rewrite.references)
    assert all("planner" in item.stages for item in planner.references)
    assert all("synthesis" in item.stages for item in synthesis.references)
    artifact_text = json.dumps(planner_artifact, ensure_ascii=False)
    assert "基金对比的可比性规则" in artifact_text
    assert "优先对比同类型" not in artifact_text
    assert planner.token_estimate <= planner.token_budget


@pytest.mark.unit
def test_loader_is_pinned_to_request_snapshot_across_registry_refresh(tmp_path: Path) -> None:
    """刷新成功后旧 Loader 仍使用旧 spec，新请求才看见新版本。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _copy_skill_assets(skills_dir)
    registry = SkillRegistry(skills_dir=skills_dir, vendor_skills_dir=tmp_path / "vendor")
    old_loader = registry.get_loader()
    old_context = old_loader.load_for_planner("fund-compare", query="黄金 ETF 对比")

    spec_path = skills_dir / "fund-compare" / "skill_spec.yaml"
    original = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(original.replace('version: "1.0.0"', 'version: "1.0.1"', 1), encoding="utf-8")
    registry.refresh()

    pinned_context = old_loader.load_for_planner("fund-compare", query="黄金 ETF 对比")
    new_context = registry.get_loader().load_for_planner(
        "fund-compare", query="黄金 ETF 对比"
    )
    assert old_context.skill_version == "1.0.0"
    assert pinned_context.registry_snapshot_hash == old_context.registry_snapshot_hash
    assert pinned_context.skill_version == "1.0.0"
    assert new_context.skill_version == "1.0.1"
    assert new_context.registry_snapshot_hash != old_context.registry_snapshot_hash


@pytest.mark.unit
def test_loader_fails_when_required_sections_exceed_budget() -> None:
    """必需章节超出预算时显式失败，不静默截断业务合同。"""
    loader = SkillRegistry(token_budget_per_stage=256).get_loader()
    with pytest.raises(SkillLoadError, match="exceed"):
        loader.load_for_rewrite("stock-first-pass", query="贵州茅台基本面")
