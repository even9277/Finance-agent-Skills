"""实现会话 Working State 的确定性字段级归并。"""

from __future__ import annotations

from dataclasses import replace

from .contracts import (
    StateOperation,
    StateValue,
    WorkingState,
    WorkingStateEvent,
    WorkingStateField,
    WorkingStateTransition,
    WorkingStateUpdate,
)


def reduce_working_state(
    current: WorkingState,
    update: WorkingStateUpdate,
    *,
    session_id: str,
    source_message_id: int,
    trace_id: str | None,
) -> WorkingStateTransition:
    """按字段操作归并本轮状态，并生成同版本审计事件。

    Args:
        current: PostgreSQL 读取的当前权威快照。
        update: 受控工作流产生、已通过类型校验的窄更新。
        session_id: 当前用户会话标识。
        source_message_id: 本轮用户消息主键。
        trace_id: 本轮 Trace 标识，只用于事件关联。

    Returns:
        新快照和字段事件；无实际变化时原样返回且不刷新版本。
    """
    values: dict[WorkingStateField, StateValue] = {
        WorkingStateField.ACTIVE_ENTITY: current.active_entity,
        WorkingStateField.CANDIDATE_ENTITIES: current.candidate_entities,
        WorkingStateField.CONSTRAINTS: current.constraints,
        WorkingStateField.REPLY_PREFERENCE_HINT: current.reply_preference_hint,
    }
    operations = (
        (
            WorkingStateField.ACTIVE_ENTITY,
            update.active_entity_operation,
            update.active_entity,
        ),
        (
            WorkingStateField.CANDIDATE_ENTITIES,
            update.candidate_entities_operation,
            update.candidate_entities,
        ),
        (
            WorkingStateField.CONSTRAINTS,
            update.constraints_operation,
            update.constraints,
        ),
        (
            WorkingStateField.REPLY_PREFERENCE_HINT,
            update.reply_preference_operation,
            update.reply_preference_hint,
        ),
    )
    changes: list[tuple[WorkingStateField, StateOperation, StateValue, StateValue]] = []
    for field_name, operation, incoming in operations:
        old_value = values[field_name]
        new_value = _apply_operation(field_name, old_value, incoming, operation)
        if new_value != old_value:
            values[field_name] = new_value
            changes.append((field_name, operation, old_value, new_value))

    if not changes:
        return WorkingStateTransition(state=current, events=())

    next_version = current.state_version + 1
    state = replace(
        current,
        active_entity=values[WorkingStateField.ACTIVE_ENTITY],
        candidate_entities=values[WorkingStateField.CANDIDATE_ENTITIES],
        constraints=values[WorkingStateField.CONSTRAINTS],
        reply_preference_hint=values[WorkingStateField.REPLY_PREFERENCE_HINT],
        state_version=next_version,
        source_message_id=source_message_id,
    )
    events = tuple(
        WorkingStateEvent(
            session_id=session_id,
            field=field_name,
            operation=operation,
            old_value=old_value,
            new_value=new_value,
            source=update.source,
            state_version=next_version,
            message_id=source_message_id,
            confidence=update.confidence,
            trace_id=trace_id,
        )
        for field_name, operation, old_value, new_value in changes
    )
    return WorkingStateTransition(state=state, events=events)


def _apply_operation(
    field_name: WorkingStateField,
    old_value: StateValue,
    incoming: StateValue,
    operation: StateOperation,
) -> StateValue:
    """应用有限状态操作，不接受核心状态上的隐式自由合并。"""
    if operation is StateOperation.NOOP:
        return old_value
    if operation in {StateOperation.CLEAR, StateOperation.EXPIRE}:
        if field_name is WorkingStateField.ACTIVE_ENTITY:
            return None
        if field_name in {
            WorkingStateField.CANDIDATE_ENTITIES,
            WorkingStateField.CONSTRAINTS,
        }:
            return ()
        return ""
    if operation is StateOperation.MERGE:
        if field_name is not WorkingStateField.CONSTRAINTS:
            raise ValueError(f"MERGE is not supported for {field_name.value}")
        if not isinstance(old_value, tuple) or not isinstance(incoming, tuple):
            raise ValueError("constraint MERGE requires tuple values")
        merged = tuple(
            dict.fromkeys(
                item
                for item in (*old_value, *incoming)
                if isinstance(item, str)
            )
        )
        return merged[:8]
    if operation is StateOperation.SET:
        return incoming
    raise ValueError(f"unsupported working-state operation: {operation.value}")
