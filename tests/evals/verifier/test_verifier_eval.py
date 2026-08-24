from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.conversation.contracts import (  # noqa: E402
    ConstraintSet,
    Entity,
    EntityType,
    EvidenceDimension,
    EvidenceFact,
    ReplyPreference,
    SkillCatalogSnapshot,
    StepStatus,
    TimeScope,
    ToolObservation,
    TushareRewriteResult,
)
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.verification import EvidenceVerifier  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


def _build_plan(message: str):
    entity = Entity(symbol="600519.SH", name="贵州茅台", entity_type=EntityType.STOCK)
    rewrite = TushareRewriteResult(
        effective_query=message,
        entity=entity,
        entities=(entity,),
        requested_dimensions=(
            EvidenceDimension.BASIC_PROFILE,
            EvidenceDimension.MARKET_SNAPSHOT,
        ),
        data_requirements=("basic_profile", "market_snapshot"),
        constraints=ConstraintSet(),
        reply_preference=ReplyPreference(),
        time_scope=TimeScope.RECENT_5_TRADING_DAYS,
    )
    catalog = ToolGovernanceCatalog.default()
    permissions = ControlledPermissionResolver(
        catalog=catalog,
        skill_catalog=SkillCatalogSnapshot.empty(),
    ).resolve(rewrite)
    return ControlledPlanner(catalog=catalog).plan(
        rewrite,
        permissions,
        trace_id="verifier-eval",
    )


@pytest.mark.eval_smoke
def test_verifier_smoke_executes_controlled_contract() -> None:
    """执行真实 M5 Verifier，而不是读取静态 prediction 或历史模块。"""
    rows = load_jsonl(Path("tests/evals/verifier/data/smoke.jsonl"))
    for row in rows:
        plan = _build_plan(row["message"])
        steps = {step.evidence_dimension.value: step for step in plan.steps}
        observations = tuple(
            ToolObservation(
                step_id=steps[item["dimension"]].step_id,
                tool_name=steps[item["dimension"]].tool_name,
                symbol=str(item.get("symbol", plan.entity.symbol if plan.entity else "")),
                evidence_dimension=steps[item["dimension"]].evidence_dimension,
                facts=tuple(
                    EvidenceFact(key=str(key), value=str(value))
                    for key, value in item.get("facts", {}).items()
                ),
                source="fixture:verifier:v1",
                observed_at=date.fromisoformat(item["observed_at"]),
                attempts=1,
                status=StepStatus.SUCCEEDED,
            )
            for item in row["observations"]
        )
        result = EvidenceVerifier().verify(
            plan=plan,
            observations=observations,
            as_of=date.fromisoformat(row["as_of"]),
        )

        assert result.claim_level.value == row["gold"]["allowed_claim_level"]
        assert sorted(item.value for item in result.missing_dimensions) == sorted(
            row["gold"]["missing_dimensions"]
        )
        assert len(result.rejected) == row["gold"]["rejected_count"]
