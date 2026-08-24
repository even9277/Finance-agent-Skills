"""验证受控对话状态机和输入合同的不变量。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    ConversationRequest,
    ConversationState,
    RunPhase,
    TerminalStatus,
)
from src.conversation.errors import ContractViolationError, StateTransitionError  # noqa: E402


@pytest.mark.unit
def test_request_rejects_blank_identity_and_message() -> None:
    """确认无用户、会话或消息的请求不能进入工作流。"""
    with pytest.raises(ContractViolationError, match="user_id"):
        ConversationRequest(user_id="", session_id="session-1", message="查询行情")

    with pytest.raises(ContractViolationError, match="session_id"):
        ConversationRequest(user_id="user-1", session_id="", message="查询行情")

    with pytest.raises(ContractViolationError, match="message"):
        ConversationRequest(user_id="user-1", session_id="session-1", message="  ")


@pytest.mark.unit
def test_state_rejects_illegal_phase_jump_and_second_terminal() -> None:
    """确认阶段不能越级，也不能在已有终态后再次终止。"""
    state = ConversationState()

    with pytest.raises(StateTransitionError, match="RECEIVED.*ROUTED"):
        state.transition(RunPhase.ROUTED)

    for phase in (
        RunPhase.PREFLIGHTED,
        RunPhase.ENTITY_RESOLVED,
        RunPhase.ROUTED,
        RunPhase.REWRITTEN,
        RunPhase.PLANNED,
        RunPhase.VALIDATED,
        RunPhase.EXECUTING,
        RunPhase.VERIFIED,
        RunPhase.SYNTHESIZING,
    ):
        state.transition(phase)

    state.terminate(TerminalStatus.SUCCEEDED)
    assert state.phase is RunPhase.SUCCEEDED
    assert state.terminal_status is TerminalStatus.SUCCEEDED

    with pytest.raises(StateTransitionError, match="terminal"):
        state.terminate(TerminalStatus.FAILED)


@pytest.mark.unit
def test_clarification_is_a_valid_early_terminal() -> None:
    """确认实体阶段可以正常结束为澄清，而不是伪装成系统失败。"""
    state = ConversationState()
    state.transition(RunPhase.PREFLIGHTED)
    state.transition(RunPhase.ENTITY_RESOLVED)
    state.terminate(TerminalStatus.NEEDS_CLARIFICATION)

    assert state.phase is RunPhase.NEEDS_CLARIFICATION
    assert state.terminal_status is TerminalStatus.NEEDS_CLARIFICATION


@pytest.mark.unit
def test_rewritten_request_can_stop_before_unmigrated_execution() -> None:
    """确认理解链完成后可经总结阶段诚实结束，而不是伪造执行成功。"""
    state = ConversationState()
    for phase in (
        RunPhase.PREFLIGHTED,
        RunPhase.ENTITY_RESOLVED,
        RunPhase.ROUTED,
        RunPhase.REWRITTEN,
        RunPhase.SYNTHESIZING,
    ):
        state.transition(phase)

    state.terminate(TerminalStatus.UNSUPPORTED)

    assert state.phase is RunPhase.UNSUPPORTED
    assert state.terminal_status is TerminalStatus.UNSUPPORTED
