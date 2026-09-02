"""验证 Milestone 5 的 spec-guided 计划、证据、降级与总结链。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.infrastructure.chat.testing import InMemoryTraceSink  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    AnswerContextPack,
    ClaimLevel,
    ControllerAction,
    ControllerRuntimeState,
    ConversationRequest,
    ContextPacket,
    EvidenceDimension,
    EvidenceFact,
    EvidenceRejectionCode,
    ExecutedPlanStep,
    ModelSynthesisChunk,
    ModelSynthesisRequest,
    RunBudget,
    StepStatus,
    TerminalStatus,
    ToolCall,
    ToolObservation,
)
from src.conversation.control import RuleController  # noqa: E402
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.rewriting import RouteAwareRewriter  # noqa: E402
from src.conversation.routing import TwoStageRouter  # noqa: E402
from src.conversation.synthesis import (  # noqa: E402
    ControlledSynthesizer,
    build_skill_synthesis_guidance,
)
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.validation import PlanValidator  # noqa: E402
from src.conversation.verification import EvidenceVerifier  # noqa: E402
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.skills.loader import PlannerSkillView, SynthesisSkillView  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402


def _build_skill_plan(query: str):
    """从真实 Registry 和理解链构造一个 spec-guided 未执行计划。"""
    registry = SkillRegistry()
    runtime = registry.runtime_snapshot()
    catalog_snapshot = registry.conversation_snapshot(runtime)
    loader = registry.get_loader(runtime)
    packet = ContextPacket(current_message=query)
    entities = AuthoritativeEntityResolver().resolve(packet)
    route = TwoStageRouter(catalog_snapshot).route(packet, entities)
    rewrite = RouteAwareRewriter(catalog_snapshot, skill_loader=loader).rewrite(
        packet,
        entities,
        route,
    )
    assert rewrite.skill_name is not None and not rewrite.needs_clarification
    planner_context = loader.load_for_planner(rewrite.skill_name, query=query)
    governance = ToolGovernanceCatalog.default()
    permissions = ControlledPermissionResolver(
        catalog=governance,
        skill_catalog=catalog_snapshot,
    ).resolve(rewrite, skill_context=planner_context)
    plan = ControlledPlanner(catalog=governance).plan(
        rewrite,
        permissions,
        trace_id=f"trace-{rewrite.skill_name}",
        skill_context=planner_context,
    )
    return registry, loader, rewrite, planner_context, permissions, plan


@pytest.mark.unit
def test_permission_is_intersection_of_spec_and_governance() -> None:
    """Skill 权限仍取 spec 与治理目录交集，M6 已纳入的 Web News 可执行。"""
    _, _, rewrite, planner_context, permissions, _ = _build_skill_plan(
        "宁德时代今天为什么突然跌了"
    )
    planner_view = planner_context.spec_view
    assert isinstance(planner_view, PlannerSkillView)

    assert rewrite.skill_name == "market-move-explain"
    assert "search_web_news" in planner_view.allowed_tools
    assert "search_web_news" in permissions.allowed_tools
    assert set(permissions.allowed_tools) == set(planner_view.allowed_tools)
    assert permissions.skill_spec_hash == planner_context.spec_hash
    assert permissions.registry_snapshot_hash == planner_context.registry_snapshot_hash


@pytest.mark.unit
def test_stock_plan_uses_spec_steps_required_flags_and_concurrency() -> None:
    """个股首轮计划必须由 spec 六个模板步骤生成并继续经过 Validator。"""
    _, _, rewrite, context, permissions, plan = _build_skill_plan(
        "贵州茅台 600519.SH 值不值得继续跟踪"
    )
    view = context.spec_view
    assert isinstance(view, PlannerSkillView)

    assert rewrite.skill_name == "stock-first-pass"
    assert [step.tool_name for step in plan.steps] == [item.tool for item in view.tool_plan_steps]
    assert [step.required for step in plan.steps] == [item.required for item in view.tool_plan_steps]
    assert [step.template_step for step in plan.steps] == [item.step for item in view.tool_plan_steps]
    assert plan.skill_spec_hash == context.spec_hash
    assert plan.concurrency_limit == view.concurrency.batch_size
    assert plan.evidence_contract is not None
    assert plan.evidence_contract.must_have_all == (
        EvidenceDimension.BASIC_PROFILE,
        EvidenceDimension.MARKET_SNAPSHOT,
        EvidenceDimension.FINANCIAL_INDICATOR,
    )
    assert PlanValidator().validate(
        plan,
        permissions,
        budget=RunBudget(max_plan_steps=16),
    ).validated_plan is not None


@pytest.mark.unit
def test_fund_compare_repeats_spec_steps_and_builds_per_symbol_evidence_groups() -> None:
    """基金比较必须对两个主体重复模板，并要求每个主体至少一类动态证据。"""
    _, _, _, context, permissions, plan = _build_skill_plan(
        "华安黄金ETF和博时黄金ETF哪个更适合长期持有"
    )

    assert len(plan.steps) == 10
    assert sum(step.tool_name == "get_fund_basic_info" for step in plan.steps) == 2
    assert plan.evidence_contract is not None
    assert plan.evidence_contract.min_distinct_symbols == 2
    assert plan.evidence_contract.per_symbol_must_have_any == (
        EvidenceDimension.FUND_NAV,
        EvidenceDimension.FUND_MARKET,
        EvidenceDimension.FUND_SHARE,
    )
    assert PlanValidator().validate(
        plan,
        permissions,
        budget=RunBudget(max_plan_steps=16),
    ).validated_plan is not None


def _facts_for_dimension(dimension: EvidenceDimension) -> tuple[EvidenceFact, ...]:
    """返回能通过字段质量门禁的离线事实。"""
    values = {
        EvidenceDimension.BASIC_PROFILE: (EvidenceFact(key="name", value="fixture"),),
        EvidenceDimension.MARKET_SNAPSHOT: (
            EvidenceFact(key="close", value="10.0"),
            EvidenceFact(key="trade_date", value=date.today().isoformat()),
        ),
        EvidenceDimension.FINANCIAL_INDICATOR: (EvidenceFact(key="roe", value="12.3"),),
        EvidenceDimension.INCOME_STATEMENT: (EvidenceFact(key="revenue", value="100"),),
        EvidenceDimension.BALANCE_SHEET: (EvidenceFact(key="total_assets", value="200"),),
        EvidenceDimension.CASHFLOW_STATEMENT: (
            EvidenceFact(key="n_cashflow_act", value="30"),
        ),
        EvidenceDimension.FUND_BASIC: (EvidenceFact(key="fund_name", value="fixture"),),
        EvidenceDimension.ETF_BASIC: (EvidenceFact(key="fund_name", value="fixture"),),
        EvidenceDimension.FUND_NAV: (EvidenceFact(key="unit_nav", value="1.1"),),
        EvidenceDimension.FUND_MARKET: (EvidenceFact(key="close", value="1.2"),),
        EvidenceDimension.FUND_SHARE: (EvidenceFact(key="fd_share", value="1000"),),
        EvidenceDimension.INDEX_DAILY: (EvidenceFact(key="close", value="3500"),),
        EvidenceDimension.SECTOR_SNAPSHOT: (EvidenceFact(key="pct_change", value="2.1"),),
        EvidenceDimension.SECTOR_CONSTITUENTS: (
            EvidenceFact(key="constituent", value="fixture"),
        ),
        EvidenceDimension.WEB_NEWS: (
            EvidenceFact(key="W1.title", value="fixture news"),
            EvidenceFact(key="W1.domain", value="news.example.com"),
            EvidenceFact(key="W1.summary", value="fixture weak signal"),
        ),
    }
    return values[dimension]


def _observation(step) -> ToolObservation:
    return ToolObservation(
        step_id=step.step_id,
        tool_name=step.tool_name,
        symbol=step.symbol,
        evidence_dimension=step.evidence_dimension,
        facts=_facts_for_dimension(step.evidence_dimension),
        source=f"fixture:{step.tool_name}:m5",
        observed_at=date.today(),
        attempts=1,
    )


@pytest.mark.unit
def test_verifier_enforces_per_symbol_any_group_and_field_quality() -> None:
    """两个基金都必须有动态证据；错误业务字段不能靠非空字符串蒙混过关。"""
    _, _, _, _, _, plan = _build_skill_plan(
        "华安黄金ETF和博时黄金ETF哪个更适合长期持有"
    )
    basic_steps = tuple(step for step in plan.steps if step.tool_name == "get_fund_basic_info")
    nav_steps = tuple(step for step in plan.steps if step.tool_name == "get_fund_nav")

    complete = EvidenceVerifier().verify(
        plan=plan,
        observations=tuple(_observation(step) for step in (*basic_steps, *nav_steps)),
        as_of=date.today(),
    )
    missing_one = EvidenceVerifier().verify(
        plan=plan,
        observations=tuple(
            _observation(step) for step in (*basic_steps, nav_steps[0])
        ),
        as_of=date.today(),
    )
    bad_field = _observation(nav_steps[1])
    bad_field = ToolObservation(
        step_id=bad_field.step_id,
        tool_name=bad_field.tool_name,
        symbol=bad_field.symbol,
        evidence_dimension=bad_field.evidence_dimension,
        facts=(EvidenceFact(key="unrelated", value="non-empty"),),
        source=bad_field.source,
        observed_at=bad_field.observed_at,
        attempts=1,
    )
    rejected_field = EvidenceVerifier().verify(
        plan=plan,
        observations=tuple(
            [*(_observation(step) for step in basic_steps), _observation(nav_steps[0]), bad_field]
        ),
        as_of=date.today(),
    )

    assert complete.claim_level is ClaimLevel.ANALYTICAL
    assert not complete.missing_evidence_groups
    assert missing_one.claim_level is ClaimLevel.DESCRIPTIVE
    assert missing_one.missing_evidence_groups
    assert any(
        item.rejection_code is EvidenceRejectionCode.FIELD_QUALITY
        for item in rejected_field.rejected
    )


@pytest.mark.unit
def test_controller_reports_spec_degrade_stage() -> None:
    """补证与部分回答必须携带当前 Skill degrade policy 的稳定阶段。"""
    _, loader, rewrite, _, _, plan = _build_skill_plan(
        "华安黄金ETF和博时黄金ETF哪个更适合长期持有"
    )
    assert rewrite.skill_name is not None
    synthesis_context = loader.load_for_synthesis(rewrite.skill_name, query=plan.objective)
    synthesis_view = synthesis_context.spec_view
    assert isinstance(synthesis_view, SynthesisSkillView)
    first_basic = next(step for step in plan.steps if step.tool_name == "get_fund_basic_info")
    verification = EvidenceVerifier().verify(
        plan=plan,
        observations=(_observation(first_basic),),
        as_of=date.today(),
    )
    controller = RuleController()
    budget = RunBudget(max_replans=1)

    first = controller.decide(
        verification,
        budget=budget,
        runtime=ControllerRuntimeState(),
        degrade_policy=synthesis_view.degrade_policy,
    )
    exhausted = controller.decide(
        verification,
        budget=budget,
        runtime=ControllerRuntimeState(replan_count=1),
        degrade_policy=synthesis_view.degrade_policy,
    )

    assert first.action is ControllerAction.REPLAN
    assert first.degrade_stage == "partial_compare"
    assert exhausted.action is ControllerAction.RESPOND_PARTIAL
    assert exhausted.degrade_stage == "partial_compare"


@pytest.mark.unit
def test_synthesis_guidance_contains_output_contract_and_references_without_tools() -> None:
    """Synthesis 只能获得输出/降级/reference 指引和 accepted evidence。"""

    @dataclass(slots=True)
    class _Model:
        calls: list[ModelSynthesisRequest] = field(default_factory=list)

        async def stream_synthesize(self, request: ModelSynthesisRequest):
            self.calls.append(request)
            yield ModelSynthesisChunk(content="受控结论", index=1)

    _, loader, rewrite, _, _, plan = _build_skill_plan(
        "华安黄金ETF和博时黄金ETF哪个更适合长期持有，先说风险"
    )
    assert rewrite.skill_name is not None
    loaded = loader.load_for_synthesis(rewrite.skill_name, query=plan.objective)
    view = loaded.spec_view
    assert isinstance(view, SynthesisSkillView)
    observations = tuple(_observation(step) for step in plan.steps)
    verification = EvidenceVerifier().verify(
        plan=plan,
        observations=observations,
        as_of=date.today(),
    )
    guidance = build_skill_synthesis_guidance(
        loaded,
        reply_preference="风险提示优先",
        degrade_stage="primary",
    )
    pack = AnswerContextPack.create(
        question="比较两只基金",
        effective_query=plan.objective,
        entities=plan.entities,
        executed_plan=tuple(
            ExecutedPlanStep(
                plan_id=plan.plan_id,
                step_id=step.step_id,
                tool_name=step.tool_name,
                status=StepStatus.SUCCEEDED,
                evidence_dimension=step.evidence_dimension,
                replanned=False,
            )
            for step in plan.steps
        ),
        verification=verification,
        terminal_status=TerminalStatus.SUCCEEDED,
        constraints=(),
        reply_preference="风险提示优先",
        selected_skill=rewrite.skill_name,
        skill_guidance=guidance,
    )
    model = _Model()

    reply = asyncio.run(ControlledSynthesizer(model).synthesize(pack))

    assert reply == "受控结论"
    assert model.calls[0].context.skill_guidance == guidance
    assert guidance.section_order == view.output_template.response_pref_overrides[
        "risk_first"
    ].section_order
    assert guidance.references
    assert not hasattr(guidance, "allowed_tools")
    assert not hasattr(guidance, "tool_plan_steps")


@dataclass(slots=True)
class _M5Tool:
    """为五类 Skill 返回维度匹配且字段合格的离线证据。"""

    calls: list[ToolCall] = field(default_factory=list)
    drop_dynamic_symbol: str = ""

    async def execute(self, call: ToolCall) -> ToolObservation:
        """只通过唯一 ToolPort 接收 Validator 已验收调用。"""
        self.calls.append(call)
        facts = _facts_for_dimension(call.evidence_dimension)
        if (
            self.drop_dynamic_symbol
            and call.symbol == self.drop_dynamic_symbol
            and call.evidence_dimension
            in {
                EvidenceDimension.FUND_NAV,
                EvidenceDimension.FUND_MARKET,
                EvidenceDimension.FUND_SHARE,
            }
        ):
            facts = ()
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=facts,
            source=f"fixture:{call.tool_name}:m5-e2e",
            observed_at=date.today(),
            attempts=1,
        )


@dataclass(slots=True)
class _M5Model:
    """记录最终安全上下文的离线模型。"""

    calls: list[ModelSynthesisRequest] = field(default_factory=list)

    async def stream_synthesize(self, request: ModelSynthesisRequest):
        """返回不访问网络的固定回答。"""
        self.calls.append(request)
        yield ModelSynthesisChunk(content="基于已验收证据的离线结论。", index=1)


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("query", "skill_name"),
    (
        ("贵州茅台 600519.SH 值不值得继续跟踪", "stock-first-pass"),
        ("华安黄金ETF和博时黄金ETF哪个更适合长期持有", "fund-compare"),
        ("帮我筛三只低波动红利ETF", "etf-screen"),
        ("半导体板块最近强不强，龙头是谁", "sector-hotspot-brief"),
        ("宁德时代今天为什么突然跌了", "market-move-explain"),
    ),
)
def test_five_skills_execute_end_to_end_through_single_executor(
    query: str,
    skill_name: str,
) -> None:
    """五类 Skill 必须经 route→Loader→permission→plan→Validator→唯一 Executor→verify→synthesis。"""

    async def run_case() -> None:
        registry = SkillRegistry()
        runtime = registry.runtime_snapshot()
        tool = _M5Tool()
        model = _M5Model()
        workflow = ControlledConversationWorkflow(
            model=model,
            tool=tool,
            trace=InMemoryTraceSink(),
            budget=RunBudget(max_plan_steps=16),
            skill_catalog=registry.conversation_snapshot(runtime),
            skill_loader=registry.get_loader(runtime),
        )
        result = await workflow.run(
            ConversationRequest(
                user_id="user-m5",
                session_id=f"session-{skill_name}",
                message=query,
            )
        )

        assert result.status is TerminalStatus.SUCCEEDED
        assert result.route is not None and result.route.skill_name == skill_name
        assert result.plan is not None and result.plan.skill_name == skill_name
        assert result.verification is not None
        assert result.verification.claim_level is ClaimLevel.ANALYTICAL
        assert len(tool.calls) == result.tool_call_count == len(result.plan.steps)
        assert {call.step_id for call in tool.calls} == {
            step.step_id for step in result.plan.steps
        }
        if skill_name == "market-move-explain":
            assert "search_web_news" in {call.tool_name for call in tool.calls}
        assert model.calls[0].context.skill_guidance is not None
        stages = [event.stage.value for event in result.events]
        assert stages.count("execute") == 1
        assert stages[-1] == "termination"

    asyncio.run(run_case())


@pytest.mark.e2e
def test_fund_compare_degrades_to_partial_when_one_subject_lacks_dynamic_evidence() -> None:
    """一只基金缺少全部动态证据时必须按 spec 降级，不能形成完整比较。"""

    async def run_case() -> None:
        registry = SkillRegistry()
        runtime = registry.runtime_snapshot()
        tool = _M5Tool(drop_dynamic_symbol="159937.SZ")
        model = _M5Model()
        workflow = ControlledConversationWorkflow(
            model=model,
            tool=tool,
            trace=InMemoryTraceSink(),
            budget=RunBudget(max_plan_steps=16),
            skill_catalog=registry.conversation_snapshot(runtime),
            skill_loader=registry.get_loader(runtime),
        )
        result = await workflow.run(
            ConversationRequest(
                user_id="user-m5-partial",
                session_id="session-fund-compare-partial",
                message="华安黄金ETF和博时黄金ETF哪个更适合长期持有",
            )
        )

        assert result.status is TerminalStatus.PARTIAL
        assert result.verification is not None
        assert "per_symbol:159937.SZ" in result.verification.missing_evidence_groups
        assert result.controller is not None
        assert result.controller.degrade_stage == "partial_compare"
        assert model.calls[0].context.claim_level is ClaimLevel.DESCRIPTIVE
        assert all(item.facts for item in model.calls[0].context.accepted_evidence)
        assert "部分结果" in result.reply

    asyncio.run(run_case())
