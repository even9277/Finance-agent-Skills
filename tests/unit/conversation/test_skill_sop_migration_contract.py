"""冻结 Skills 迁移在公开请求、路由澄清和弱证据上的目标行为。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.schemas.chat import ChatMessageRequest  # noqa: E402
from backend.application.chat import factory as chat_factory  # noqa: E402
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryTraceSink,
)
from src.conversation import contracts  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ContextPacket,
    Entity,
    EntityResolutionResult,
    EntityType,
    RouteDecision,
    RouteFamily,
    RouteSource,
)
from src.conversation.rewriting import RouteAwareRewriter  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402


@pytest.mark.contract
def test_public_chat_request_accepts_optional_explicit_skill_without_breaking_old_clients() -> None:
    """公开 Schema 必须暴露可选 explicit_skill，并继续接受旧请求形状。"""
    assert "explicit_skill" in ChatMessageRequest.model_fields
    old_request = ChatMessageRequest.model_validate({"user_id": "user-1", "message": "你好"})
    explicit = ChatMessageRequest.model_validate(
        {
            "user_id": "user-1",
            "message": "比较两只基金",
            "explicit_skill": "fund-compare",
        }
    )
    assert getattr(old_request, "explicit_skill", None) is None
    assert getattr(explicit, "explicit_skill", None) == "fund-compare"


@pytest.mark.contract
def test_conversation_result_can_return_machine_consumable_skill_confirmation() -> None:
    """中置信路由必须返回候选、理由和版本，而不只是一句文字。"""
    confirmation_type = getattr(contracts, "SkillConfirmation", None)
    assert confirmation_type is not None, "missing typed SkillConfirmation contract"
    assert "skill_confirmation" in contracts.ConversationResult.__dataclass_fields__
    fields = confirmation_type.__dataclass_fields__
    assert {"candidates", "reason", "registry_snapshot_hash"} <= set(fields)


@pytest.mark.contract
def test_web_news_is_registered_as_read_only_weak_evidence() -> None:
    """Web News 必须进入统一治理目录并拥有独立弱证据维度。"""
    web_news = getattr(contracts.EvidenceDimension, "WEB_NEWS", None)
    assert web_news is not None
    policy = ToolGovernanceCatalog.default().require("search_web_news")
    assert policy.evidence_dimension is web_news
    assert policy.side_effect is contracts.ToolSideEffect.READ
    assert policy.api_family == "web-search-read"


@pytest.mark.unit
def test_rewrite_rejects_multiple_independent_skill_tasks_before_planning() -> None:
    """一个请求包含两个独立 SOP 时必须先拆分，不能由单个 Skill 强吞。"""
    first = Entity(symbol="518880.SH", name="华安黄金ETF", entity_type=EntityType.FUND)
    second = Entity(symbol="159937.SZ", name="博时黄金ETF", entity_type=EntityType.FUND)
    entities = EntityResolutionResult(
        entity=first,
        resolved_entities=(first, second),
        candidates=(first, second),
        inherited=False,
        confidence=0.99,
    )
    route = RouteDecision(
        family=RouteFamily.FINANCIAL_SOP,
        analysis_mode="fund_compare",
        confidence=0.95,
        reason="contract route",
        skill_name="fund-compare",
        route_source=RouteSource.STAGE1_HIGH,
    )

    result = RouteAwareRewriter(SkillRegistry().conversation_snapshot()).rewrite(
        ContextPacket(
            current_message="先比较华安黄金ETF和博时黄金ETF，再筛三只低波动红利ETF"
        ),
        entities,
        route,
    )

    assert result.needs_clarification is True
    assert result.route_mismatch == "multiple_skill_tasks"
    assert "拆分" in result.clarification_question


@pytest.mark.unit
def test_production_factory_uses_process_registry_for_cross_request_lkg() -> None:
    """生产装配必须复用进程级 Registry，避免每个请求丢失最近合法快照。"""
    registry = SkillRegistry()

    with (
        patch.object(
            chat_factory,
            "get_skill_registry",
            side_effect=(registry, registry),
        ) as registry_factory,
        patch.object(
            chat_factory,
            "OpenAICompatibleModelProvider",
            side_effect=(FakeModelProvider(), FakeModelProvider()),
        ),
        patch.object(
            chat_factory,
            "build_read_only_tool_provider",
            side_effect=(FakeToolProvider(), FakeToolProvider()),
        ),
        patch.object(
            chat_factory,
            "SkillTraceSink",
            side_effect=(InMemoryTraceSink(), InMemoryTraceSink()),
        ),
    ):
        first = chat_factory.build_chat_use_case(object())  # type: ignore[arg-type]
        second = chat_factory.build_chat_use_case(object())  # type: ignore[arg-type]

    assert first is not second
    assert registry_factory.call_count == 2
