import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills.skill_registry import SkillRegistry  # noqa: E402


def test_skill_registry_exposes_active_snapshot_and_loader():
    registry = SkillRegistry()
    snapshot = registry.get_active_snapshot()
    assert snapshot.get("stock-first-pass") is not None
    pending = registry.propose_snapshot()
    assert pending.registry_version
    assert registry.activate_snapshot(pending.registry_version).registry_version == pending.registry_version
    assert registry.get_loader().load_for_rewrite("stock-first-pass").skill_id == "stock-first-pass"
