"""验证 M5 证据门控、有界补证和总结输入隔离。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    AnswerContextPack,
    ClaimLevel,
    ConstraintSet,
    ControllerAction,
    ControllerRuntimeState,
    Entity,
    EntityType,
    EvidenceDimension,
    EvidenceFact,
    EvidenceRejectionCode,
    ExecutedPlanStep,
    ModelSynthesisRequest,
    ReplyPreference,
    RunBudget,
    StepStatus,
    TerminalStatus,
    TimeScope,
    ToolObservation,
    ToolPlanStep,
    TushareRewriteResult,
)
from src.conversation.control import RuleController  # noqa: E402
from src.conversation.permissions import ControlledPermissionResolver  # noqa: E402
from src.conversation.planning import ControlledPlanner  # noqa: E402
from src.conversation.replanning import BoundedEvidenceReplanner  # noqa: E402
from src.conversation.synthesis import ControlledSynthesizer  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402
from src.conversation.verification import EvidenceVerifier  # noqa: E402

AS_OF = date(2026, 8, 24)
ENTITY = Entity(symbol="600519.SH", name="贵州茅台", entity_type=EntityType.STOCK)


def _plan_and_permissions():
    rewrite = TushareRewriteResult(
        effective_query="查询贵州茅台基础信息和近期行情",
        entity=ENTITY,
        entities=(ENTITY,),
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
        skill_catalog=replace_empty_skill_catalog(),
    ).resolve(rewrite)
    plan = ControlledPlanner(catalog=catalog).plan(
        rewrite,
        permissions,
        trace_id="trace-m5",
    )
    return plan, permissions


def replace_empty_skill_catalog():
    """延迟导入空 Skill 快照，保持测试辅助函数类型清晰。"""
    from src.conversation.contracts import SkillCatalogSnapshot

    return SkillCatalogSnapshot.empty()


def _observation(
    *,
    step_id: str,
    tool_name: str,
    dimension: EvidenceDimension,
    symbol: str = ENTITY.symbol,
    facts: tuple[EvidenceFact, ...] = (EvidenceFact(key="value", value="ok"),),
    observed_at: date = AS_OF,
    status: StepStatus = StepStatus.SUCCEEDED,
) -> ToolObservation:
    return ToolObservation(
        step_id=step_id,
        tool_name=tool_name,
        symbol=symbol,
        evidence_dimension=dimension,
        facts=facts,
        source=f"fixture:{tool_name}:v1",
        observed_at=observed_at,
        attempts=1,
        status=status,
    )


@pytest.mark.unit
def test_verifier_rejects_empty_wrong_entity_and_stale_evidence() -> None:
    """空载荷、错主语和过期行情都不能进入 accepted evidence。"""
    plan, _ = _plan_and_permissions()
    basic_step, market_step = plan.steps
    plan = replace(
        plan,
        steps=plan.steps
        + (
            ToolPlanStep(
                step_id="stale-market",
                tool_name="get_daily_bars",
                symbol=ENTITY.symbol,
                evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
                required=True,
                idempotency_key="stale-market-fingerprint",
            ),
        ),
    )
    observations = (
        _observation(
            step_id=basic_step.step_id,
            tool_name=basic_step.tool_name,
            dimension=basic_step.evidence_dimension,
            facts=(),
        ),
        _observation(
            step_id=market_step.step_id,
            tool_name=market_step.tool_name,
            dimension=market_step.evidence_dimension,
            symbol="000001.SZ",
        ),
        _observation(
            step_id="stale-market",
            tool_name="get_daily_bars",
            dimension=EvidenceDimension.MARKET_SNAPSHOT,
            observed_at=AS_OF - timedelta(days=30),
        ),
    )

    result = EvidenceVerifier().verify(plan=plan, observations=observations, as_of=AS_OF)

    assert result.accepted == ()
    assert {item.rejection_code for item in result.rejected} == {
        EvidenceRejectionCode.EMPTY_FACTS,
        EvidenceRejectionCode.ENTITY_MISMATCH,
        EvidenceRejectionCode.STALE,
    }
    assert result.claim_level is ClaimLevel.REFUSE
    assert result.missing_requirements == plan.requirements


@pytest.mark.unit
def test_verifier_rejects_conflicting_facts_instead_of_choosing_one() -> None:
    """同主语、同维度、同日期的事实冲突必须整体隔离。"""
    plan, _ = _plan_and_permissions()
    market_step = plan.steps[1]
    plan = replace(
        plan,
        steps=plan.steps
        + (
            ToolPlanStep(
                step_id="alternative-market",
                tool_name="get_daily_bars",
                symbol=ENTITY.symbol,
                evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
                required=True,
                idempotency_key="alternative-market-fingerprint",
            ),
        ),
    )
    observations = (
        _observation(
            step_id=market_step.step_id,
            tool_name=market_step.tool_name,
            dimension=market_step.evidence_dimension,
            facts=(EvidenceFact(key="close", value="1688.00", unit="CNY"),),
        ),
        _observation(
            step_id="alternative-market",
            tool_name="get_daily_bars",
            dimension=EvidenceDimension.MARKET_SNAPSHOT,
            facts=(EvidenceFact(key="close", value="1699.00", unit="CNY"),),
        ),
    )

    result = EvidenceVerifier().verify(plan=plan, observations=observations, as_of=AS_OF)

    assert result.accepted == ()
    assert all(
        item.rejection_code is EvidenceRejectionCode.CONFLICT for item in result.rejected
    )
    assert EvidenceRejectionCode.CONFLICT in result.hard_gate_failures


@pytest.mark.unit
def test_controller_replans_once_then_terminates_partial() -> None:
    """同一缺口最多触发冻结次数的补证，耗尽后必须降级终止。"""
    plan, _ = _plan_and_permissions()
    basic_step = plan.steps[0]
    verification = EvidenceVerifier().verify(
        plan=plan,
        observations=(
            _observation(
                step_id=basic_step.step_id,
                tool_name=basic_step.tool_name,
                dimension=basic_step.evidence_dimension,
            ),
        ),
        as_of=AS_OF,
    )
    controller = RuleController()
    budget = RunBudget(max_replans=1)

    first = controller.decide(
        verification,
        budget=budget,
        runtime=ControllerRuntimeState(),
    )
    exhausted = controller.decide(
        verification,
        budget=budget,
        runtime=ControllerRuntimeState(
            replan_count=1,
            previous_missing_requirements=verification.missing_requirements,
        ),
    )

    assert first.action is ControllerAction.REPLAN
    assert first.terminal_status is None
    assert first.replans_remaining == 1
    assert exhausted.action is ControllerAction.RESPOND_PARTIAL
    assert exhausted.terminal_status is TerminalStatus.PARTIAL
    assert exhausted.replans_remaining == 0


@pytest.mark.unit
def test_replanner_adds_only_an_untried_permitted_alternative() -> None:
    """补证只能选择原权限快照内、未执行过且覆盖缺口的备用工具。"""
    plan, permissions = _plan_and_permissions()
    basic_step = plan.steps[0]
    verification = EvidenceVerifier().verify(
        plan=plan,
        observations=(
            _observation(
                step_id=basic_step.step_id,
                tool_name=basic_step.tool_name,
                dimension=basic_step.evidence_dimension,
            ),
        ),
        as_of=AS_OF,
    )

    result = BoundedEvidenceReplanner().replan(
        root_plan=plan,
        permissions=permissions,
        verification=verification,
        attempt=1,
        attempted_fingerprints=frozenset(step.idempotency_key for step in plan.steps),
    )

    assert result.plan is not None
    assert [step.tool_name for step in result.plan.steps] == ["get_daily_bars"]
    assert result.plan.steps[0].tool_name in permissions.allowed_tools
    assert result.plan.steps[0].idempotency_key not in {
        step.idempotency_key for step in plan.steps
    }


@pytest.mark.unit
def test_synthesis_receives_accepted_facts_and_reason_only_rejection_summaries() -> None:
    """模型上下文不得携带 rejected evidence 的事实值。"""

    class CapturingModel:
        def __init__(self) -> None:
            self.calls: list[ModelSynthesisRequest] = []

        async def synthesize(self, request: ModelSynthesisRequest) -> str:
            self.calls.append(request)
            return "基于已验收证据的保守结论。"

    plan, _ = _plan_and_permissions()
    basic_step, market_step = plan.steps
    verification = EvidenceVerifier().verify(
        plan=plan,
        observations=(
            _observation(
                step_id=basic_step.step_id,
                tool_name=basic_step.tool_name,
                dimension=basic_step.evidence_dimension,
                facts=(EvidenceFact(key="name", value="贵州茅台"),),
            ),
            _observation(
                step_id=market_step.step_id,
                tool_name=market_step.tool_name,
                dimension=market_step.evidence_dimension,
                facts=(EvidenceFact(key="secret_bad_value", value="SHOULD_NOT_LEAK"),),
                observed_at=AS_OF - timedelta(days=30),
            ),
        ),
        as_of=AS_OF,
    )
    pack = AnswerContextPack.create(
        question="贵州茅台近期表现如何",
        effective_query=plan.objective,
        entities=plan.entities,
        executed_plan=(
            ExecutedPlanStep(
                plan_id=plan.plan_id,
                step_id=basic_step.step_id,
                tool_name=basic_step.tool_name,
                status=StepStatus.SUCCEEDED,
                evidence_dimension=basic_step.evidence_dimension,
                replanned=False,
            ),
        ),
        verification=verification,
        terminal_status=TerminalStatus.PARTIAL,
        constraints=(),
        reply_preference="concise",
        selected_skill=None,
    )
    model = CapturingModel()

    reply = asyncio.run(ControlledSynthesizer(model).synthesize(pack))

    assert "部分结果" in reply
    assert model.calls[0].context.accepted_evidence == verification.accepted
    assert model.calls[0].context.rejected_evidence == ()
    assert all(not item.facts for item in model.calls[0].context.rejection_summaries)
    assert "SHOULD_NOT_LEAK" not in repr(model.calls[0])
    assert model.calls[0].context.claim_level is ClaimLevel.DESCRIPTIVE
