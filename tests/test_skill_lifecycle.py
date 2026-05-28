import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills_v2.lifecycle import SkillLifecycleError, SkillStatus, can_transition, transition  # noqa: E402


def test_lifecycle_allows_shadow_to_active():
    assert can_transition(SkillStatus.SHADOW, SkillStatus.ACTIVE)
    assert transition("shadow", "active") == SkillStatus.ACTIVE


def test_lifecycle_rejects_deprecated_to_active():
    assert not can_transition("deprecated", "active")
    with pytest.raises(SkillLifecycleError):
        transition("deprecated", "active")
