"""从 Application Use Case 验证 M2 新受控工作流的离线纵向链。"""

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
    ConversationRequest,
    ErrorCode,
    RunBudget,
    TerminalStatus,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402

CASES_PATH = ROOT / "tests" / "fixtures" / "conversation" / "vertical_slice_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    """读取带版本的 M2 四路径验收案例。"""
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
            assert result.verification.claim_level.value == "PARTIAL"
            assert len(model.calls) == 1
            assert "缺少" in result.reply
            assert model.calls[0].context.accepted_evidence == result.verification.accepted
            assert all(
                item.status.value == "ACCEPTED"
                for item in model.calls[0].context.accepted_evidence
            )

        if case["tool_behavior"] == "timeout_market":
            market_calls = [call for call in tool.calls if call.tool_name == "pro_bar"]
            assert len(market_calls) == result.context.budget.max_tool_attempts
            assert result.error_code is ErrorCode.TOOL_TIMEOUT
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
