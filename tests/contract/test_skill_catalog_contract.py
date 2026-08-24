"""验证 Skill 快照和渐进视图不会扩大执行权限。"""

from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[2] / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.errors import ContractViolationError  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402


@pytest.mark.contract
def test_workspace_skill_snapshot_is_immutable_and_stable() -> None:
    """确认真实 Registry 可生成版本化、排序稳定的不可变快照。"""
    registry = SkillRegistry()

    first = registry.conversation_snapshot()
    registry.refresh()
    second = registry.conversation_snapshot()

    assert first.snapshot_hash == second.snapshot_hash
    assert first.version == "workspace-skills-v1"
    assert {item.name for item in first.skills} >= {
        "fund-compare",
        "etf-screen",
        "market-move-explain",
        "sector-hotspot-brief",
        "stock-first-pass",
    }


@pytest.mark.contract
def test_reference_view_cannot_expand_execution_permissions() -> None:
    """确认渐进加载 reference 只暴露已登记路径，不携带或新增工具权限。"""
    snapshot = SkillRegistry().conversation_snapshot()
    descriptor = snapshot.require("fund-compare")
    execution = snapshot.execution_view("fund-compare")
    selected = descriptor.reference_paths[:1]

    reference_view = snapshot.reference_view("fund-compare", selected)

    assert set(reference_view.reference_paths) <= set(descriptor.reference_paths)
    assert "allowed_tools" not in asdict(reference_view)
    assert execution.allowed_tools == descriptor.allowed_tools
    with pytest.raises(ContractViolationError, match="reference path"):
        snapshot.reference_view("fund-compare", ("../../secrets.md",))
