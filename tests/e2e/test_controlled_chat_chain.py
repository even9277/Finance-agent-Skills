"""从 Application Use Case 验证受控工作流的离线纵向链。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryConversationRepository,
    InMemoryTraceSink,
)
from src.conversation.contracts import (  # noqa: E402
    ClaimLevel,
    ConversationRequest,
    ErrorCode,
    EvidenceStatus,
    RunBudget,
    TerminalStatus,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402

CASES_PATH = ROOT / "tests" / "fixtures" / "conversation" / "vertical_slice_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    """读取带版本的纵向验收案例。"""
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert payload["fixture_version"] == "controlled-chat-vertical-slice-v1"
    return list(payload["cases"])


@pytest.mark.e2e
@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: str(case["case_id"]))
def test_controlled_chat_vertical_slice_reaches_expected_terminal(case: dict[str, Any]) -> None:
    """确认四条固定案例经过同一真实 Orchestrator 并到达唯一终态。"""

    async def run_case() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider(behavior=str(case["tool_behavior"]))
        repository = InMemoryConversationRepository()
        trace = InMemoryTraceSink()
        workflow = ControlledConversationWorkflow(model=model, tool=tool, trace=trace)
        use_case = ControlledChatUseCase(workflow=workflow, repository=repository)
        request = ConversationRequest(
            user_id="user-m2",
            session_id=f"session-{case['case_id']}",
            request_id=f"request-{case['case_id']}",
            message=str(case["message"]),
        )

        result = await use_case.execute(request)

        assert result.status is TerminalStatus(str(case["expected_status"]))
        assert len(tool.calls) == int(case["expected_tool_calls"])
        assert result.missing_dimensions == tuple(case["expected_missing_dimensions"])
        assert len(repository.saved) == 1
        assert repository.saved[0].result == result
        assert [event.sequence for event in trace.events] == list(
            range(1, len(trace.events) + 1)
        )
        assert all(event.trace_id == result.context.trace_id for event in trace.events)
        assert all(event.run_id == result.context.run_id for event in trace.events)
        assert trace.events[-1].stage.value == "termination"

        if result.status is TerminalStatus.SUCCEEDED:
            stages = [event.stage.value for event in trace.events]
            if case["tool_behavior"] == "success":
                assert stages == [
                    "context",
                    "entity_resolution",
                    "route",
                    "rewrite",
                    "permission",
                    "plan",
                    "validate",
                    "execute",
                    "verify",
                    "controller",
                    "synthesis",
                    "termination",
                ]
            else:
                assert stages.count("replan") == 1
                assert stages.count("execute") == 2
                assert stages.count("verify") == 2
            assert result.entity is not None and result.entity.symbol == "600519.SH"
            assert result.verification is not None
            assert len(result.verification.accepted) == 2
            assert len(model.calls) == 1
            assert "600519.SH" in result.reply
        elif result.status is TerminalStatus.NEEDS_CLARIFICATION:
            assert [event.stage.value for event in trace.events] == [
                "context",
                "entity_resolution",
                "controller",
                "termination",
            ]
            assert result.entity is None
            assert len(model.calls) == 0
            assert "中国平安" in result.reply and "平安银行" in result.reply
        else:
            assert result.status is TerminalStatus.PARTIAL
            assert result.verification is not None
            assert result.verification.claim_level.value == "DESCRIPTIVE"
            assert len(model.calls) == 1
            assert "缺少" in result.reply
            assert model.calls[0].context.accepted_evidence == result.verification.accepted
            assert all(
                item.status.value == "ACCEPTED"
                for item in model.calls[0].context.accepted_evidence
            )

        if case["tool_behavior"] == "timeout_market":
            market_calls = [call for call in tool.calls if call.tool_name == "get_market_bars"]
            assert len(market_calls) == result.context.budget.max_tool_attempts
            assert result.error_code is None
        elif case["tool_behavior"] == "missing_market":
            assert result.error_code is ErrorCode.EVIDENCE_MISSING

    asyncio.run(run_case())


@pytest.mark.e2e
def test_workflow_stops_when_total_stage_budget_is_exhausted() -> None:
    """确认过小总阶段预算会产生稳定失败，而不是继续执行或循环。"""

    async def run_case() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider()
        trace = InMemoryTraceSink()
        workflow = ControlledConversationWorkflow(
            model=model,
            tool=tool,
            trace=trace,
            budget=RunBudget(max_steps=2, max_tool_attempts=2, max_replans=0),
        )
        result = await ControlledChatUseCase(
            workflow=workflow,
            repository=InMemoryConversationRepository(),
        ).execute(
            ConversationRequest(
                user_id="user-m2",
                session_id="session-budget",
                request_id="request-budget",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            )
        )

        assert result.status is TerminalStatus.FAILED
        assert result.error_code is ErrorCode.STEP_BUDGET_EXHAUSTED
        assert result.tool_call_count == 0
        assert model.calls == []
        assert tool.calls == []
        assert [event.stage.value for event in trace.events] == [
            "context",
            "entity_resolution",
            "termination",
        ]

    asyncio.run(run_case())


@pytest.mark.e2e
def test_trace_sink_failure_does_not_block_business_result() -> None:
    """确认可选观测出口失败时，离线业务主链仍产生结果。"""

    async def run_case() -> None:
        workflow = ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=FakeToolProvider(),
            trace=InMemoryTraceSink(fail_on_emit=True),
        )
        use_case = ControlledChatUseCase(
            workflow=workflow,
            repository=InMemoryConversationRepository(),
        )

        result = await use_case.execute(
            ConversationRequest(
                user_id="user-m2",
                session_id="session-trace-failure",
                request_id="request-trace-failure",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            )
        )

        assert result.status is TerminalStatus.SUCCEEDED

    asyncio.run(run_case())


@pytest.mark.e2e
def test_low_confidence_skill_route_clarifies_before_tools() -> None:
    """确认 Stage1 低置信命中在任何工具或模型调用前停止。"""

    async def run_case() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider()
        trace = InMemoryTraceSink()
        workflow = ControlledConversationWorkflow(
            model=model,
            tool=tool,
            trace=trace,
            skill_catalog=SkillRegistry().conversation_snapshot(),
        )
        result = await ControlledChatUseCase(
            workflow=workflow,
            repository=InMemoryConversationRepository(),
        ).execute(
            ConversationRequest(
                user_id="user-m3",
                session_id="session-route-confirm",
                request_id="request-route-confirm",
                message="分析一下贵州茅台 600519.SH",
            )
        )

        assert result.status is TerminalStatus.NEEDS_CLARIFICATION
        assert result.error_code is ErrorCode.ROUTE_CONFIRMATION_REQUIRED
        assert result.tool_call_count == 0
        assert model.calls == []
        assert tool.calls == []
        assert [event.stage.value for event in trace.events] == [
            "context",
            "entity_resolution",
            "route",
            "controller",
            "termination",
        ]

    asyncio.run(run_case())


@pytest.mark.e2e
def test_m4_sop_runs_validated_tools_before_baseline_evidence_stages() -> None:
    """确认高置信 SOP 只执行权限快照内的 Validated Plan。"""

    async def run_case() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider()
        trace = InMemoryTraceSink()
        workflow = ControlledConversationWorkflow(
            model=model,
            tool=tool,
            trace=trace,
            skill_catalog=SkillRegistry().conversation_snapshot(),
        )
        result = await ControlledChatUseCase(
            workflow=workflow,
            repository=InMemoryConversationRepository(),
        ).execute(
            ConversationRequest(
                user_id="user-m3",
                session_id="session-sop-boundary",
                request_id="request-sop-boundary",
                message="贵州茅台 600519.SH 现在还能买吗",
            )
        )

        assert result.status is TerminalStatus.SUCCEEDED
        assert result.route is not None and result.route.skill_name == "stock-first-pass"
        assert result.tool_call_count == 3
        assert len(model.calls) == 1
        assert {call.tool_name for call in tool.calls} == {
            "get_stock_basic_info",
            "get_market_bars",
            "get_fina_indicator",
        }
        assert [event.stage.value for event in trace.events] == [
            "context",
            "entity_resolution",
            "route",
            "rewrite",
            "permission",
            "plan",
            "validate",
            "execute",
            "verify",
            "controller",
            "synthesis",
            "termination",
        ]

    asyncio.run(run_case())


@pytest.mark.e2e
def test_m5_missing_market_uses_one_alternative_then_succeeds() -> None:
    """确认主行情为空时只补证一次，并使用权限内的不同工具收口。"""

    async def run_case() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider(behavior="recover_market_with_alternative")
        trace = InMemoryTraceSink()
        result = await ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(model=model, tool=tool, trace=trace),
            repository=InMemoryConversationRepository(),
        ).execute(
            ConversationRequest(
                user_id="user-m5",
                session_id="session-m5-replan",
                request_id="request-m5-replan",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            )
        )

        assert result.status is TerminalStatus.SUCCEEDED
        assert [call.tool_name for call in tool.calls] == [
            "get_stock_basic_info",
            "get_market_bars",
            "get_daily_bars",
        ]
        assert [event.stage.value for event in trace.events].count("replan") == 1
        assert [event.stage.value for event in trace.events].count("verify") == 2
        assert result.controller is not None and result.controller.replans_remaining == 0
        assert len(model.calls) == 1

    asyncio.run(run_case())


@pytest.mark.e2e
def test_m5_replan_without_new_evidence_terminates_partial() -> None:
    """确认备用工具仍无事实时不会再次规划或强答。"""

    async def run_case() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider(behavior="missing_market")
        trace = InMemoryTraceSink()
        result = await ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(model=model, tool=tool, trace=trace),
            repository=InMemoryConversationRepository(),
        ).execute(
            ConversationRequest(
                user_id="user-m5",
                session_id="session-m5-bounded",
                request_id="request-m5-bounded",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            )
        )

        assert result.status is TerminalStatus.PARTIAL
        assert [event.stage.value for event in trace.events].count("replan") == 1
        assert [call.tool_name for call in tool.calls] == [
            "get_stock_basic_info",
            "get_market_bars",
            "get_daily_bars",
        ]
        assert result.verification is not None
        assert result.verification.claim_level is ClaimLevel.DESCRIPTIVE
        assert all(
            item.status is EvidenceStatus.ACCEPTED
            for item in model.calls[0].context.accepted_evidence
        )

    asyncio.run(run_case())


@pytest.mark.e2e
def test_invalid_explicit_sop_subject_clarifies_before_planning() -> None:
    """确认显式选择 Skill 也必须通过 Rewrite 主体合同。"""

    async def run_case() -> None:
        tool = FakeToolProvider()
        workflow = ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=tool,
            trace=InMemoryTraceSink(),
            skill_catalog=SkillRegistry().conversation_snapshot(),
        )
        result = await ControlledChatUseCase(
            workflow=workflow,
            repository=InMemoryConversationRepository(),
        ).execute(
            ConversationRequest(
                user_id="user-m3",
                session_id="session-sop-subject",
                request_id="request-sop-subject",
                message="比较一下华安黄金 ETF",
                explicit_skill="fund-compare",
            )
        )

        assert result.status is TerminalStatus.NEEDS_CLARIFICATION
        assert result.error_code is ErrorCode.REWRITE_CLARIFICATION_REQUIRED
        assert tool.calls == []
        assert result.route is not None and result.route.skill_name == "fund-compare"

    asyncio.run(run_case())
