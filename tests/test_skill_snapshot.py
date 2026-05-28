import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills_v2.lifecycle import SkillStatus  # noqa: E402
from src.skills_v2.snapshot import SkillSnapshotEntry, SkillSnapshotManager, build_registry_snapshot  # noqa: E402


def _entry(skill_id="stock-first-pass", status=SkillStatus.ACTIVE):
    return SkillSnapshotEntry(
        skill_id=skill_id,
        status=status,
        skill_version="1.0.0",
        spec_hash="s",
        reference_hash="r",
    )


def test_snapshot_manager_activates_pending_snapshot():
    manager = SkillSnapshotManager(build_registry_snapshot([_entry("old")], registry_version="old"))
    pending = manager.propose_snapshot(build_registry_snapshot([_entry("new")], registry_version="new"))
    assert pending.registry_version == "new"
    active = manager.activate_snapshot("new")
    assert active.get("new") is not None
    assert manager.get_last_known_good_snapshot().registry_version == "new"


def test_snapshot_active_mapping_is_immutable():
    snapshot = build_registry_snapshot([_entry()])
    try:
        snapshot.entries["x"] = _entry("x")  # type: ignore[index]
        mutated = True
    except TypeError:
        mutated = False
    assert mutated is False
