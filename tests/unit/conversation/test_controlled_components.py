"""验证 M2 确定性阶段的权限、计划和证据门控。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    Entity,
    EntityType,
    EvidenceDimension,
    EvidenceFact,
    EvidenceRequirement,
    ToolObservation,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
)
from src.conversation.planning import DeterministicPlanner  # noqa: E402
from src.conversation.validation import PlanValidator  # noqa: E402
from src.conversation.verification import EvidenceVerifier  # noqa: E402


@pytest.mark.unit
def test_plan_validator_rejects_tool_outside_permission_snapshot() -> None:
    """确认计划引用白名单外工具时会在执行前被阻断。"""
    entity = Entity(
        symbol="600519.SH",
        name="贵州茅台",
        entity_type=EntityType.STOCK,
    )
    plan = ToolPlan(
        plan_id="plan-unauthorized",
        entity=entity,
        steps=(
            ToolPlanStep(
                step_id="step-1",
                tool_name="trade_order",
                symbol=entity.symbol,
                evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
                required=True,
            ),
        ),
        requirements=(
            EvidenceRequirement(
                dimension=EvidenceDimension.MARKET_SNAPSHOT,
                required=True,
            ),
        ),
    )
    permissions = ToolPermissionSnapshot.create(
        allowed_tools=("stock_basic", "pro_bar"),
        source="m2-fixture",
        version="tools-v1",
    )

    validation = PlanValidator().validate(plan, permissions)

    assert validation.is_valid is False
    assert [issue.code.value for issue in validation.issues] == ["TOOL_NOT_ALLOWED"]


@pytest.mark.unit
def test_planner_produces_stable_steps_for_requested_dimensions() -> None:
    """确认同一实体和证据需求产生稳定、可复现的真实计划。"""
    entity = Entity(
        symbol="600519.SH",
        name="贵州茅台",
        entity_type=EntityType.STOCK,
    )
    planner = DeterministicPlanner()

    plan = planner.plan(
        entity,
        (EvidenceDimension.BASIC_PROFILE, EvidenceDimension.MARKET_SNAPSHOT),
    )

    assert plan.plan_id == "plan-stock-snapshot-v1"
    assert [
        (step.step_id, step.tool_name, step.evidence_dimension.value) for step in plan.steps
    ] == [
        ("fetch-basic-profile", "stock_basic", "basic_profile"),
        ("fetch-market-snapshot", "pro_bar", "market_snapshot"),
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
