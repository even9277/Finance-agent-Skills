"""验证会话 Working State 的确定性合并与审计语义。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.memory.contracts import (  # noqa: E402
    MemorySource,
    StateOperation,
    WorkingEntity,
    WorkingState,
    WorkingStateField,
    WorkingStateUpdate,
)
from src.memory.working_state import reduce_working_state  # noqa: E402


def _entity(symbol: str, name: str) -> WorkingEntity:
    return WorkingEntity(symbol=symbol, name=name, entity_type="stock")


def test_explicit_entity_switch_and_field_updates_share_one_new_version() -> None:
    """当前轮显式实体、约束和偏好必须原子形成同一状态版本。"""
    current = WorkingState(
        active_entity=_entity("300750.SZ", "宁德时代"),
        constraints=("只看A股口径",),
        state_version=3,
        source_message_id=9,
    )
    update = WorkingStateUpdate(
        active_entity=_entity("600519.SH", "贵州茅台"),
        candidate_entities=(_entity("600519.SH", "贵州茅台"),),
        active_entity_operation=StateOperation.SET,
        candidate_entities_operation=StateOperation.SET,
        constraints=("不提供直接买卖建议",),
        constraints_operation=StateOperation.MERGE,
        reply_preference_hint="先给结论，再展开",
        reply_preference_operation=StateOperation.SET,
        source=MemorySource.USER_MESSAGE,
        confidence=0.92,
    )

    transition = reduce_working_state(
        current,
        update,
        session_id="session-state",
        source_message_id=10,
        trace_id="tr_state",
    )

    assert transition.state.state_version == 4
    assert transition.state.active_entity == _entity("600519.SH", "贵州茅台")
    assert transition.state.constraints == (
        "只看A股口径",
        "不提供直接买卖建议",
    )
    assert transition.state.reply_preference_hint == "先给结论，再展开"
    assert {event.field for event in transition.events} == {
        WorkingStateField.ACTIVE_ENTITY,
        WorkingStateField.CANDIDATE_ENTITIES,
        WorkingStateField.CONSTRAINTS,
        WorkingStateField.REPLY_PREFERENCE_HINT,
    }
    assert {event.state_version for event in transition.events} == {4}
    assert {event.message_id for event in transition.events} == {10}


def test_no_update_preserves_state_without_fabricating_an_event() -> None:
    """没有本轮信号时不得刷新版本或把旧状态伪装成新证据。"""
    current = WorkingState(
        active_entity=_entity("600519.SH", "贵州茅台"),
        constraints=("不展开技术面分析",),
        reply_preference_hint="回答简洁",
        state_version=5,
        source_message_id=11,
    )

    transition = reduce_working_state(
        current,
        WorkingStateUpdate(),
        session_id="session-state",
        source_message_id=12,
        trace_id="tr_noop",
    )

    assert transition.state == current
    assert transition.events == ()


def test_clear_operations_remove_only_the_addressed_fields() -> None:
    """清空临时约束和偏好时不得顺带丢失当前实体。"""
    current = WorkingState(
        active_entity=_entity("600519.SH", "贵州茅台"),
        constraints=("只看A股口径",),
        reply_preference_hint="回答简洁",
        state_version=2,
        source_message_id=4,
    )

    transition = reduce_working_state(
        current,
        WorkingStateUpdate(
            constraints_operation=StateOperation.CLEAR,
            reply_preference_operation=StateOperation.CLEAR,
        ),
        session_id="session-state",
        source_message_id=5,
        trace_id="tr_clear",
    )

    assert transition.state.active_entity == current.active_entity
    assert transition.state.constraints == ()
    assert transition.state.reply_preference_hint == ""
    assert transition.state.state_version == 3


def test_segment_expiry_clears_temporary_fields_with_expire_events() -> None:
    """话题段结束时清理临时状态，并保留可审计的 EXPIRE 原因。"""
    current = WorkingState(
        active_entity=_entity("600519.SH", "贵州茅台"),
        candidate_entities=(_entity("600519.SH", "贵州茅台"),),
        constraints=("只看A股口径",),
        reply_preference_hint="回答简洁",
        state_version=6,
        source_message_id=12,
    )
    update = WorkingStateUpdate(
        active_entity_operation=StateOperation.EXPIRE,
        candidate_entities_operation=StateOperation.EXPIRE,
        constraints_operation=StateOperation.EXPIRE,
        reply_preference_operation=StateOperation.EXPIRE,
    )

    transition = reduce_working_state(
        current,
        update,
        session_id="session-state",
        source_message_id=13,
        trace_id="tr_expire",
    )

    assert transition.state.active_entity is None
    assert transition.state.candidate_entities == ()
    assert transition.state.constraints == ()
    assert transition.state.reply_preference_hint == ""
    assert transition.state.state_version == 7
    assert len(transition.events) == 4
    assert {event.operation for event in transition.events} == {
        StateOperation.EXPIRE
    }
