"""验证 Skill SemVer 与稳定内容哈希合同。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.skills.version import (  # noqa: E402
    SkillVersion,
    combine_hashes,
    stable_hash_mapping,
    stable_hash_text,
)


@pytest.mark.unit
def test_stable_hash_normalizes_line_endings_and_mapping_order() -> None:
    """平台换行和 YAML 字段顺序不得制造伪版本。"""
    assert stable_hash_text("a\r\nb\n") == stable_hash_text("a\nb")
    assert stable_hash_mapping({"a": 1, "b": [2]}) == stable_hash_mapping(
        {"b": [2], "a": 1}
    )
    assert combine_hashes("a", "b") != combine_hashes("b", "a")


@pytest.mark.unit
def test_skill_version_preserves_semver_and_fingerprints_legacy_labels() -> None:
    """规范版本原样保留，历史标签只能作为带哈希的兼容展示值。"""
    assert SkillVersion("1.2.3").normalized == "1.2.3"
    assert SkillVersion("1.2.3").is_semver is True
    assert SkillVersion("").normalized == "0.1.0"
    assert SkillVersion("").is_semver is False
    assert SkillVersion("draft").normalized.startswith("0.1.0+")
    assert SkillVersion("draft").is_semver is False
