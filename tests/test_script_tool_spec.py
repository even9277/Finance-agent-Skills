import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.tool_discovery.executable_registry import ExecutableToolRegistry, ScriptToolSpec  # noqa: E402


def test_script_tool_spec_disabled_by_default_is_not_planner_visible():
    registry = ExecutableToolRegistry()
    spec = ScriptToolSpec(
        name="run_local_report_script",
        description="disabled script",
        supported_entity_types=["none"],
        input_fields=[],
        evidence_type="script_artifact",
        source_api="local_script",
        api_family="script",
        freshness_tier="static",
        is_primary_evidence=False,
        rate_limit_group="script",
    )
    registry.register_script_tool(handler=lambda: None, spec=spec)
    assert "run_local_report_script" not in registry.names(planner_visible_only=True)
