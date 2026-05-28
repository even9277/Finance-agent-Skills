import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills_v2.schema_gate import validate_skill  # noqa: E402


def _spec():
    return {
        "skill_name": "stock-first-pass",
        "skill_family": "financial-sop",
        "version": "1.0.0",
        "input_contract": {},
        "allowed_tools": ["get_stock_basic_info"],
        "tool_plan_steps": [{"tool": "get_stock_basic_info", "required": True}],
        "required_evidence": {"must_have_all": ["stock_basic"]},
        "output_template": {},
        "degrade_policy": {},
    }


def test_schema_gate_accepts_valid_skill_spec():
    report = validate_skill(_spec(), allowed_tool_names=["get_stock_basic_info"], evidence_types=["stock_basic"])
    assert report.passed
    assert report.status == "active"


def test_schema_gate_disables_unknown_tool_and_evidence():
    spec = _spec()
    spec["allowed_tools"] = ["missing_tool"]
    spec["tool_plan_steps"] = [{"tool": "missing_tool"}]
    spec["required_evidence"] = {"must_have_all": ["unknown_evidence"]}
    report = validate_skill(spec, allowed_tool_names=["get_stock_basic_info"], evidence_types=["stock_basic"])
    assert not report.passed
    assert "unknown_allowed_tool" in report.disabled_reason
    assert "unknown_evidence_type" in report.disabled_reason
