"""验证 RegistrySnapshot 原子切换、请求固定和 LKG 失败语义。"""

from __future__ import annotations

import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import MutableMapping, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
SKILLS_ROOT = AGENT_ROOT / "src" / "skills"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.skills.lifecycle import SkillStatus  # noqa: E402
from src.skills.skill_registry import SkillRegistry, SkillRegistryRefreshError  # noqa: E402
from src.skills.snapshot import (  # noqa: E402
    SkillSnapshotEntry,
    SkillSnapshotError,
    SkillSnapshotManager,
    build_registry_snapshot,
)

SKILL_NAMES = (
    "stock-first-pass",
    "fund-compare",
    "etf-screen",
    "sector-hotspot-brief",
    "market-move-explain",
)


def _entry(skill_id: str, version: str) -> SkillSnapshotEntry:
    """构造只用于快照管理测试的最小 active 条目。"""
    return SkillSnapshotEntry(
        skill_id=skill_id,
        status=SkillStatus.ACTIVE,
        skill_version=version,
        spec_hash=f"spec-{version}",
        reference_hash=f"ref-{version}",
    )


def _copy_skill_assets(target_root: Path) -> None:
    """复制五类文件资产到临时隔离目录，不带 cache 或历史 Runtime。"""
    for skill_name in SKILL_NAMES:
        shutil.copytree(SKILLS_ROOT / skill_name, target_root / skill_name)


@pytest.mark.unit
def test_snapshot_manager_requires_first_valid_snapshot_and_keeps_request_reference() -> None:
    """首次无快照必须拒绝；激活新候选不改变请求已固定的旧对象。"""
    manager = SkillSnapshotManager()
    with pytest.raises(SkillSnapshotError, match="no active"):
        manager.get_active_snapshot()

    old = build_registry_snapshot((_entry("old-skill", "1.0.0"),), registry_version="old")
    new = build_registry_snapshot((_entry("new-skill", "1.1.0"),), registry_version="new")
    manager.propose_snapshot(old)
    pinned = manager.activate_snapshot("old")
    manager.propose_snapshot(new)

    assert manager.get_active_snapshot() is pinned
    activated = manager.activate_snapshot("new")
    assert activated.get("new-skill") is not None
    assert pinned.get("old-skill") is not None
    assert pinned.get("new-skill") is None
    assert manager.get_last_known_good_snapshot() is activated
    mutable_view = cast(MutableMapping[str, SkillSnapshotEntry], activated.entries)
    with pytest.raises(TypeError):
        mutable_view["mutated"] = _entry("mutated", "1.0.0")


@pytest.mark.unit
def test_parallel_readers_only_observe_complete_old_or_new_snapshots() -> None:
    """并发读取期间只能看到完整引用，不能看到半成品 entries。"""
    old = build_registry_snapshot((_entry("old-skill", "1.0.0"),), registry_version="old")
    new = build_registry_snapshot((_entry("new-skill", "1.1.0"),), registry_version="new")
    manager = SkillSnapshotManager(old)

    def read_many() -> set[tuple[str, tuple[str, ...]]]:
        observations: set[tuple[str, tuple[str, ...]]] = set()
        for _ in range(200):
            snapshot = manager.get_active_snapshot()
            observations.add((snapshot.registry_version, tuple(snapshot.entries)))
        return observations

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(read_many) for _ in range(6)]
        manager.propose_snapshot(new)
        manager.activate_snapshot("new")
    observed = set().union(*(future.result() for future in futures))

    assert observed <= {("old", ("old-skill",)), ("new", ("new-skill",))}
    assert observed


@pytest.mark.unit
def test_registry_refresh_failure_keeps_active_and_last_known_good(tmp_path: Path) -> None:
    """任一 Skill gate 失败时不得发布剩余子集或污染 LKG。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _copy_skill_assets(skills_dir)
    registry = SkillRegistry(skills_dir=skills_dir, vendor_skills_dir=tmp_path / "vendor")
    before = registry.runtime_snapshot()

    spec_path = skills_dir / "stock-first-pass" / "skill_spec.yaml"
    spec_path.write_text("skill_name: stock-first-pass\n", encoding="utf-8")

    with pytest.raises(SkillRegistryRefreshError, match="schema gate"):
        registry.refresh()

    after = registry.runtime_snapshot()
    assert after is before
    assert after.snapshot_hash == before.snapshot_hash
    assert set(after.active_skill_ids()) == set(SKILL_NAMES)
    assert any(not report.passed for report in registry.last_rejected_reports())
