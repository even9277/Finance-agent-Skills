"""验证 Milestone 4 的 metadata 路由、确认和 input-contract 改写。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryTraceSink,
)
from src.conversation.contracts import (  # noqa: E402
    ContextPacket,
    ConversationRequest,
    Entity,
    EntityResolutionResult,
    EntityType,
    RouteDecision,
    RouteFamily,
    RouteSource,
    SkillRerankRequest,
    SkillRerankResult,
    SkillRerankScore,
    TerminalStatus,
)
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from src.conversation.rewriting import RouteAwareRewriter  # noqa: E402
from src.conversation.routing import TwoStageRouter  # noqa: E402
from src.conversation.skill_discovery import SkillDiscovery  # noqa: E402
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402


class _RecordingReranker:
    """记录最小候选并返回固定 typed 分数。"""

    def __init__(self, scores: tuple[SkillRerankScore, ...]) -> None:
        self._scores = scores
        self.requests: list[SkillRerankRequest] = []

    def rerank(self, request: SkillRerankRequest) -> SkillRerankResult:
        """返回测试指定的候选分数。"""
        self.requests.append(request)
        return SkillRerankResult(scores=self._scores)


class _FailingReranker:
    """模拟在线 rerank 瞬时失败。"""

    def rerank(self, request: SkillRerankRequest) -> SkillRerankResult:
        """抛出错误以验证 deterministic fallback。"""
        del request
        raise RuntimeError("provider unavailable")


@pytest.mark.unit
def test_registry_routing_view_contains_asset_metadata_without_execution_fields() -> None:
    """路由视图必须来自已校验 spec，且不暴露工具或引用正文。"""
    view = SkillRegistry().conversation_snapshot().routing_view()

    assert len(view) == 5
    assert all(item.when_to_use and item.when_not_to_use for item in view)
    assert all(item.positive_examples and item.negative_examples for item in view)
    assert all(item.supported_entity_types for item in view)
    assert not hasattr(view[0], "allowed_tools")
    assert not hasattr(view[0], "reference_paths")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "skill_name"),
    (
        ("贵州茅台 600519.SH 现在还能买吗", "stock-first-pass"),
        ("宁德时代今天为什么突然跌了", "market-move-explain"),
        ("华安黄金ETF和博时黄金ETF哪个更适合长期持有", "fund-compare"),
        ("帮我筛三只低波动红利ETF", "etf-screen"),
        ("半导体板块最近强不强，龙头是谁", "sector-hotspot-brief"),
    ),
)
def test_metadata_retriever_routes_five_skills_with_explainable_candidates(
    query: str,
    skill_name: str,
) -> None:
    """五类代表性请求必须稳定高置信命中，并保留候选解释。"""
    registry = SkillRegistry()
    packet = ContextPacket(current_message=query)
    entities = AuthoritativeEntityResolver().resolve(packet)

    match = SkillDiscovery(registry.conversation_snapshot()).discover(
        query,
        entities=entities.resolved_entities,
    )

    assert match.skill_name == skill_name
    assert match.confidence >= 0.82
    assert match.candidates[0].skill_name == skill_name
    assert match.candidates[0].reasons


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "skill_name"),
    (
        ("帮我快速看一下这只股票基本面", "stock-first-pass"),
        ("比较一下华安黄金ETF", "fund-compare"),
        ("最近什么板块强", "sector-hotspot-brief"),
    ),
)
def test_missing_subject_queries_reach_skill_input_contract(
    query: str,
    skill_name: str,
) -> None:
    """缺槽位请求也应先发现目标 Skill，再由 input contract 给出专属澄清。"""
    registry = SkillRegistry()
    packet = ContextPacket(current_message=query)
    entities = AuthoritativeEntityResolver().resolve(packet)

    decision = TwoStageRouter(registry.conversation_snapshot()).route(packet, entities)

    assert decision.family is RouteFamily.FINANCIAL_SOP
    assert decision.skill_name == skill_name
    assert decision.requires_confirmation is False


@pytest.mark.unit
def test_mid_confidence_route_returns_versioned_confirmation_without_selecting_skill() -> None:
    """相邻 Skill 无法拉开分差时必须返回版本化确认，而不是猜一个执行。"""
    registry = SkillRegistry()
    packet = ContextPacket(current_message="帮我分析一下黄金相关产品")
    entities = EntityResolutionResult(
        entity=None,
        candidates=(),
        inherited=False,
        confidence=0.0,
    )

    decision = TwoStageRouter(registry.conversation_snapshot()).route(packet, entities)

    assert decision.family is RouteFamily.FINANCIAL_SOP
    assert decision.skill_name is None
    assert decision.requires_confirmation is True
    assert decision.skill_confirmation is not None
    assert len(decision.skill_confirmation.candidates) >= 2
    assert decision.skill_confirmation.registry_snapshot_hash
    assert all(item.version for item in decision.skill_confirmation.candidates)


@pytest.mark.unit
def test_optional_reranker_receives_top_k_typed_candidates_and_can_reorder() -> None:
    """在线层只能重排 top-K typed 候选，不能读取完整 Skill 或历史。"""
    registry = SkillRegistry()
    reranker = _RecordingReranker(
        (
            SkillRerankScore(skill_name="etf-screen", score=0.93, reason="screen intent"),
            SkillRerankScore(skill_name="fund-compare", score=0.61, reason="neighbor"),
        )
    )
    discovery = SkillDiscovery(registry.conversation_snapshot(), reranker=reranker, top_k=2)

    match = discovery.discover("帮我分析一下黄金相关产品", entities=())

    assert match.skill_name == "etf-screen"
    assert reranker.requests and len(reranker.requests[0].candidates) == 2
    assert not hasattr(reranker.requests[0], "history")
    assert not hasattr(reranker.requests[0].candidates[0], "skill_body")


@pytest.mark.unit
def test_reranker_failure_falls_back_to_deterministic_mid_confidence_result() -> None:
    """rerank 失败必须回到确定性结果，不得把异常变成高置信选择。"""
    registry = SkillRegistry()
    discovery = SkillDiscovery(
        registry.conversation_snapshot(),
        reranker=_FailingReranker(),
        top_k=2,
    )

    match = discovery.discover("帮我分析一下黄金相关产品", entities=())

    assert match.skill_name is None
    assert match.requires_confirmation is True
    assert "fallback" in match.reason


@pytest.mark.unit
def test_loader_driven_rewrite_rejects_explicit_skill_with_missing_cardinality() -> None:
    """显式 Skill 只能跳过自动选择，不能绕过 spec input contract。"""
    registry = SkillRegistry()
    snapshot = registry.conversation_snapshot()
    entity = Entity("518880.SH", "华安黄金ETF", EntityType.FUND)
    entities = EntityResolutionResult(
        entity=entity,
        resolved_entities=(entity,),
        candidates=(entity,),
        inherited=False,
        confidence=0.99,
    )
    route = TwoStageRouter(snapshot).route(
        ContextPacket(current_message="使用 fund-compare 比较华安黄金ETF"),
        entities,
        explicit_skill="fund-compare",
    )

    result = RouteAwareRewriter(snapshot, skill_loader=registry.get_loader()).rewrite(
        ContextPacket(current_message="使用 fund-compare 比较华安黄金ETF"),
        entities,
        route,
    )

    assert route.route_source is RouteSource.USER_EXPLICIT
    assert result.needs_clarification is True
    assert result.entity_conflict == "fund_compare_requires_two_entities"


@pytest.mark.unit
def test_loader_driven_rewrite_rejects_multiple_independent_skill_tasks() -> None:
    """Rewrite 必须在 Planner 前要求拆分两个独立 SOP。"""
    registry = SkillRegistry()
    snapshot = registry.conversation_snapshot()
    first = Entity("518880.SH", "华安黄金ETF", EntityType.FUND)
    second = Entity("159937.SZ", "博时黄金ETF", EntityType.FUND)
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
        reason="test",
        skill_name="fund-compare",
        route_source=RouteSource.STAGE1_HIGH,
    )

    result = RouteAwareRewriter(snapshot, skill_loader=registry.get_loader()).rewrite(
        ContextPacket(current_message="先比较华安黄金ETF和博时黄金ETF，再筛三只低波动红利ETF"),
        entities,
        route,
    )

    assert result.needs_clarification is True
    assert result.route_mismatch == "multiple_skill_tasks"
    assert "拆分" in result.clarification_question


@pytest.mark.unit
def test_workflow_mid_confidence_confirmation_is_terminal_and_executes_no_tool() -> None:
    """结构化确认必须在 permission/planner/executor 之前终止。"""

    async def run_case() -> None:
        registry = SkillRegistry()
        model = FakeModelProvider()
        tool = FakeToolProvider()
        trace = InMemoryTraceSink()
        workflow = ControlledConversationWorkflow(
            model=model,
            tool=tool,
            trace=trace,
            skill_catalog=registry.conversation_snapshot(),
            skill_loader=registry.get_loader(),
        )

        result = await workflow.run(
            ConversationRequest(
                user_id="user-m4",
                session_id="session-m4-confirm",
                message="帮我分析一下黄金相关产品",
            )
        )

        assert result.status is TerminalStatus.NEEDS_CLARIFICATION
        assert result.skill_confirmation is not None
        assert result.tool_call_count == 0
        assert not tool.calls
        assert not model.calls
        assert "permission" not in {event.stage.value for event in result.events}
        route_event = next(event for event in result.events if event.stage.value == "route")
        attributes = {item.key: item.value for item in route_event.attributes}
        assert isinstance(attributes["candidate_count"], int)
        assert attributes["candidate_count"] >= 2
        assert attributes["route_source"] == "stage1_low"

    asyncio.run(run_case())


@pytest.mark.unit
def test_workflow_fallback_does_not_require_financial_entity() -> None:
    """普通问候应进入 fallback，不得被金融实体缺失门控误判为澄清。"""

    async def run_case() -> None:
        registry = SkillRegistry()
        tool = FakeToolProvider()
        result = await ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=tool,
            trace=InMemoryTraceSink(),
            skill_catalog=registry.conversation_snapshot(),
            skill_loader=registry.get_loader(),
        ).run(
            ConversationRequest(
                user_id="user-m9",
                session_id="session-m9-fallback",
                message="你好，介绍一下你自己",
            )
        )

        assert result.status is TerminalStatus.UNSUPPORTED
        assert result.route is not None and result.route.family is RouteFamily.FALLBACK
        assert tool.calls == []

    asyncio.run(run_case())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "skill_name", "reply_fragment"),
    (
        ("帮我快速看一下这只股票基本面", "stock-first-pass", "一只股票"),
        ("比较一下华安黄金ETF", "fund-compare", "两只"),
        ("最近什么板块强", "sector-hotspot-brief", "一个明确主体"),
    ),
)
def test_workflow_missing_skill_slots_clarify_before_tools(
    query: str,
    skill_name: str,
    reply_fragment: str,
) -> None:
    """自动发现的 Skill 缺槽位时必须在工具执行前给出专属澄清。"""

    async def run_case() -> None:
        registry = SkillRegistry()
        tool = FakeToolProvider()
        result = await ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=tool,
            trace=InMemoryTraceSink(),
            skill_catalog=registry.conversation_snapshot(),
            skill_loader=registry.get_loader(),
        ).run(
            ConversationRequest(
                user_id="user-m9",
                session_id=f"session-m9-{skill_name}",
                message=query,
            )
        )

        assert result.status is TerminalStatus.NEEDS_CLARIFICATION
        assert result.route is not None and result.route.skill_name == skill_name
        assert reply_fragment in result.reply
        assert tool.calls == []

    asyncio.run(run_case())
