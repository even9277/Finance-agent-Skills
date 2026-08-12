from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("Financial-MCP-Agent").resolve()))

from importlib.util import find_spec

pytestmark = pytest.mark.skipif(
    find_spec("src.agents.planner") is None,
    reason="依赖受控主链 planner 模块，待 M2 迁移后自动启用",
)


@pytest.mark.eval_smoke
def test_planner_smoke_dataset_generates_valid_tool_plans() -> None:
    from src.agents.planner.plan_validator import PlanValidator
    from src.agents.planner.tushare_planner import TusharePlanner
    from tests.evals.runner import load_jsonl

    rows = load_jsonl(Path("tests/evals/planner/data/smoke.jsonl"))
    assert rows

    planner = TusharePlanner()
    validator = PlanValidator()
    for row in rows:
        plan = planner.plan(
            rewrite_result=row["rewrite_result"],
            discovery_result=row["discovery_result"],
            active_entity=row.get("active_entity"),
            trace_id=row["case_id"],
        )
        validated = validator.validate(plan, discovery_result=row["discovery_result"])
        planned_tools = {step.tool_name for step in validated.plan.steps}
        planned_evidence = {step.evidence_type for step in validated.plan.steps}

        assert validated.plan.route == row["gold"]["route"]
        assert planned_evidence >= set(row["gold"]["required_evidence"])
        assert planned_tools.isdisjoint(set(row["gold"].get("forbidden_tools") or []))


@pytest.mark.eval_smoke
def test_planner_runner_writes_baseline_metrics(tmp_path: Path) -> None:
    from tests.evals.runner import load_jsonl, write_report

    rows = load_jsonl(Path("tests/evals/planner/data/smoke.jsonl"))
    report = write_report("planner", rows, tmp_path)
    payload = report.read_text(encoding="utf-8")

    assert report.name == "planner_metrics.json"
    assert "planned_evidence_coverage" in payload
