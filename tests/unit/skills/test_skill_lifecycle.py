"""验证 Skill 生命周期只允许显式白名单转换。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.skills.lifecycle import (  # noqa: E402
    SkillLifecycleError,
    SkillStatus,
    can_transition,
    normalize_status,
    transition,
)


@pytest.mark.unit
def test_skill_lifecycle_supports_shadow_activation_and_bounded_rollback() -> None:
    """通过 gate 的 shadow 可激活，active 可回滚但不可跳回 draft。"""
    assert can_transition("shadow", "active") is True
    assert transition("shadow", "active") is SkillStatus.ACTIVE
    assert transition("active", "rolled_back") is SkillStatus.ROLLED_BACK
    assert can_transition("active", "draft") is False


@pytest.mark.unit
def test_skill_lifecycle_rejects_deprecated_revival_and_unknown_status() -> None:
    """deprecated 不允许直接复活，未知状态不能静默降级。"""
    assert can_transition("deprecated", "active") is False
    with pytest.raises(SkillLifecycleError):
        transition("deprecated", "active")
    with pytest.raises(SkillLifecycleError):
        normalize_status("published")
