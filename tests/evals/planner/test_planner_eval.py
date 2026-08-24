"""执行 M4 Typed Planner 的固定离线评测。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for import_root in (PROJECT_ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.conversation.contracts import (  # noqa: E402
    ConstraintSet,
    Entity,
    EntityType,
    ReplyPreference,
    SopRewriteResult,
    TimeScope,
    TushareRewriteResult,
)
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.validation import PlanValidator  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


def _rewrite(row: dict[str, Any]) -> SopRewriteResult | TushareRewriteResult:
    entities = tuple(
        Entity(
            symbol=item["symbol"],
            name=item["name"],
            entity_type=EntityType(item["entity_type"]),
        )
        for item in row["entities"]
    )
    common = {
        "effective_query": row["case_id"],
        "entity": entities[0] if entities else None,
        "entities": entities,
        "requested_dimensions": (),
        "data_requirements": tuple(row["data_requirements"]),
        "constraints": ConstraintSet(),
        "reply_preference": ReplyPreference(),
        "time_scope": TimeScope.LATEST_TRADING_DAY,
    }
    if row["kind"] == "financial-sop":
        return SopRewriteResult(skill_name=row["skill_name"], **common)
    return TushareRewriteResult(**common)


@pytest.mark.eval_smoke
def test_planner_eval_generates_permission_validated_dags() -> None:
    """验证四类固定任务只规划必要工具并通过权限/DAG 校验。"""
    rows = load_jsonl(Path("tests/evals/planner/data/smoke.jsonl"))
    catalog = ToolGovernanceCatalog.default()
    resolver = ControlledPermissionResolver(
        catalog=catalog,
        skill_catalog=SkillRegistry().conversation_snapshot(),
    )
    planner = ControlledPlanner(catalog=catalog)

    for row in rows:
        rewrite = _rewrite(row)
        permissions = resolver.resolve(rewrite)
        plan = planner.plan(rewrite, permissions, trace_id=row["case_id"])
        validation = PlanValidator().validate(plan, permissions)
        tools = {step.tool_name for step in plan.steps}

        assert validation.validated_plan is not None
        assert tools >= set(row["gold"]["required_tools"])
        assert tools.isdisjoint(row["gold"]["forbidden_tools"])
        assert len(plan.steps) == row["gold"]["step_count"]


@pytest.mark.eval_smoke
def test_planner_runner_writes_baseline_metrics(tmp_path: Path) -> None:
    """确认版本化 Planner 数据仍可进入统一指标产物。"""
    from tests.evals.runner import write_report

    rows = load_jsonl(Path("tests/evals/planner/data/smoke.jsonl"))
    report = write_report("planner", rows, tmp_path)
    assert "planned_evidence_coverage" in report.read_text(encoding="utf-8")
