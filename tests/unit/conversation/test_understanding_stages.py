"""验证 M3 工具调用前理解链的安全边界和 bad cases。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[3] / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    ContextPacket,
    Entity,
    EntityResolutionResult,
    EntityType,
    RouteDecision,
    RouteFamily,
    RouteSource,
)
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from src.conversation.rewriting import RouteAwareRewriter  # noqa: E402
from src.conversation.routing import TwoStageRouter  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402


@pytest.mark.unit
def test_router_never_replaces_authoritative_entity() -> None:
    """确认 Router 只选择能力链，不重新猜测或覆盖实体。"""
    packet = ContextPacket(current_message="贵州茅台 600519.SH 现在还能买吗")
    entities = AuthoritativeEntityResolver().resolve(packet)
    before = entities.entity

    decision = TwoStageRouter(SkillRegistry().conversation_snapshot()).route(packet, entities)

    assert entities.entity == before
    assert entities.entity is not None and entities.entity.symbol == "600519.SH"
    assert decision.family is RouteFamily.FINANCIAL_SOP
    assert decision.skill_name == "stock-first-pass"


@pytest.mark.unit
def test_low_confidence_sop_match_requires_confirmation() -> None:
    """确认弱 SOP 命中不会直接进入工具阶段。"""
    packet = ContextPacket(current_message="分析一下贵州茅台 600519.SH")
    entities = AuthoritativeEntityResolver().resolve(packet)

    decision = TwoStageRouter(SkillRegistry().conversation_snapshot()).route(packet, entities)

    assert decision.family is RouteFamily.FINANCIAL_SOP
    assert decision.skill_name == "stock-first-pass"
    assert decision.requires_confirmation is True
    assert decision.confidence < 0.85


@pytest.mark.unit
def test_invalid_sop_subject_is_clarified_before_planning() -> None:
    """确认 fund-compare 只有单一基金时 Rewrite 会阻断后续计划。"""
    entity = Entity(symbol="518880.SH", name="华安黄金ETF", entity_type=EntityType.FUND)
    entities = EntityResolutionResult(
        entity=entity,
        resolved_entities=(entity,),
        candidates=(entity,),
        inherited=False,
        confidence=0.99,
    )
    route = RouteDecision(
        family=RouteFamily.FINANCIAL_SOP,
        analysis_mode="fund_compare",
        confidence=0.95,
        reason="explicit test route",
        skill_name="fund-compare",
        route_source=RouteSource.STAGE1_HIGH,
    )

    result = RouteAwareRewriter(SkillRegistry().conversation_snapshot()).rewrite(
        ContextPacket(current_message="比较一下华安黄金 ETF"),
        entities,
        route,
    )

    assert result.needs_clarification is True
    assert result.entity_conflict == "fund_compare_requires_two_entities"
    assert "两只" in result.clarification_question
    assert "基金" in result.clarification_question
