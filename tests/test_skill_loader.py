import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills.skill_registry import SkillRegistry  # noqa: E402


def test_skill_loader_returns_stage_artifact_for_workspace_skill():
    registry = SkillRegistry()
    context = registry.get_loader().load_for_planner("stock-first-pass", query="贵州茅台怎么看")
    assert context.skill_id == "stock-first-pass"
    assert context.stage == "planner"
    assert context.spec["skill_name"] == "stock-first-pass"
    assert "reference_paths" in context.artifact()
