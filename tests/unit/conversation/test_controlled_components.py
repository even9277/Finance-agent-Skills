"""验证 M2 确定性阶段的权限、计划和证据门控。"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    ConstraintSet,
    Entity,
    EntityType,
    EvidenceDimension,
    EvidenceFact,
    ReplyPreference,
    SkillCatalogSnapshot,
    TimeScope,
    ToolObservation,
    TushareRewriteResult,
)
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.validation import PlanValidator  # noqa: E402
from src.conversation.verification import EvidenceVerifier  # noqa: E402


def _planning_inputs():
    entity = Entity(
        symbol="600519.SH",
        name="贵州茅台",
        entity_type=EntityType.STOCK,
    )
    rewrite = TushareRewriteResult(
        effective_query="查询贵州茅台基础信息和近期行情",
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
    plan = ControlledPlanner(catalog=catalog).plan(
        rewrite,
        permissions,
        trace_id="trace-stable-plan",
    )
    return plan, permissions


@pytest.mark.unit
def test_plan_validator_rejects_tool_outside_permission_snapshot() -> None:
    """确认计划引用白名单外工具时会在执行前被阻断。"""
    plan, permissions = _planning_inputs()
    plan = replace(
        plan,
        steps=(replace(plan.steps[0], tool_name="trade_order"),),
    )

    validation = PlanValidator().validate(plan, permissions)

    assert validation.is_valid is False
    assert "TOOL_NOT_ALLOWED" in {issue.code.value for issue in validation.issues}


@pytest.mark.unit
def test_planner_produces_stable_steps_for_requested_dimensions() -> None:
    """确认同一实体和证据需求产生稳定、可复现的真实计划。"""
    plan, permissions = _planning_inputs()
    repeated, _ = _planning_inputs()

    assert plan.plan_id == repeated.plan_id
    assert PlanValidator().validate(plan, permissions).is_valid is True
    assert [
        (step.tool_name, step.evidence_dimension.value) for step in plan.steps
    ] == [
        ("get_stock_basic_info", "basic_profile"),
        ("get_market_bars", "market_snapshot"),
    ]


@pytest.mark.unit
def test_verifier_rejects_empty_payload_and_reports_missing_dimension() -> None:
    """确认 HTTP 成功但无事实的数据不能成为可用证据。"""
    entity = Entity(
        symbol="600519.SH",
        name="贵州茅台",
        entity_type=EntityType.STOCK,
    )
    observations = (
        ToolObservation(
            step_id="fetch-basic-profile",
            tool_name="stock_basic",
            symbol=entity.symbol,
            evidence_dimension=EvidenceDimension.BASIC_PROFILE,
            facts=(EvidenceFact(key="name", value="贵州茅台"),),
            source="fixture",
            observed_at=date(2026, 8, 24),
            attempts=1,
        ),
        ToolObservation(
            step_id="fetch-market-snapshot",
            tool_name="pro_bar",
            symbol=entity.symbol,
            evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
            facts=(),
            source="fixture",
            observed_at=date(2026, 8, 24),
            attempts=1,
        ),
    )

    result = EvidenceVerifier().verify(
        entity=entity,
        observations=observations,
        required_dimensions=(
            EvidenceDimension.BASIC_PROFILE,
            EvidenceDimension.MARKET_SNAPSHOT,
        ),
    )

    assert [item.evidence_dimension.value for item in result.accepted] == ["basic_profile"]
    assert [item.evidence_dimension.value for item in result.rejected] == ["market_snapshot"]
    assert result.missing_dimensions == (EvidenceDimension.MARKET_SNAPSHOT,)
    assert result.claim_level.value == "PARTIAL"
