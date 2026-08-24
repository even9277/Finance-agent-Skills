"""验证 memory-v1 领域合同、版本和权威边界。"""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.memory.contracts import (  # noqa: E402
    MEMORY_POLICY_VERSION,
    MEMORY_SCHEMA_VERSION,
    ActivationSource,
    MemoryContractError,
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    MemorySource,
    MemoryValueKind,
    NewOutboxTask,
    OutboxTaskKind,
    ProfileField,
    TurnCommittedPayload,
    WorkingEntity,
    WorkingState,
    build_turn_outbox_key,
)
from src.memory.policy import (  # noqa: E402
    requires_user_confirmation,
    validate_record_authority,
)


@pytest.mark.unit
def test_working_state_is_immutable_versioned_and_bounded() -> None:
    """确认核心会话状态不可原地修改，且关键长度和版本均被校验。"""
    state = WorkingState(
        active_entity=WorkingEntity(
            symbol="600519.SH",
            name="贵州茅台",
            entity_type="stock",
        ),
        constraints=("不讨论杠杆",),
        reply_preference_hint="先给结论",
        scope=MemoryScope.SESSION_SEGMENT,
        state_version=2,
        source_message_id=7,
    )

    assert state.schema_version == MEMORY_SCHEMA_VERSION
    assert state.active_entity is not None
    assert state.active_entity.symbol == "600519.SH"
    with pytest.raises(FrozenInstanceError):
        state.state_version = 3  # type: ignore[misc]
    with pytest.raises(MemoryContractError):
        WorkingState(state_version=-1)
    with pytest.raises(MemoryContractError):
        WorkingState(reply_preference_hint="x" * 221)


@pytest.mark.unit
def test_model_inferred_high_impact_profile_requires_confirmation() -> None:
    """确认模型推断的高影响字段不能通过自动策略成为权威记录。"""
    with pytest.raises(MemoryContractError):
        MemoryRecord(
            record_id="fixture-record-risk",
            user_id="fixture-user-memory",
            kind=MemoryValueKind.STRUCTURED_PROFILE,
            category="profile",
            profile_field=ProfileField.RISK_LEVEL,
            value="aggressive",
            status=MemoryRecordStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            activation_source=ActivationSource.POLICY_AUTO,
            evidence_ref="message:fixture-1",
            version=1,
        )

    assert requires_user_confirmation(
        ProfileField.RISK_LEVEL,
        MemorySource.MODEL_INFERRED,
    ) is True


@pytest.mark.unit
def test_explicit_text_memory_has_versioned_authority_contract() -> None:
    """确认显式文本偏好具有权威来源、版本和策略版本。"""
    record = MemoryRecord(
        record_id="fixture-record-response-style",
        user_id="fixture-user-memory",
        kind=MemoryValueKind.TEXT,
        category="response_style",
        content="以后回答先给结论",
        status=MemoryRecordStatus.ACTIVE,
        source=MemorySource.USER_COMMAND,
        activation_source=ActivationSource.EXPLICIT_USER,
        evidence_ref="message:fixture-2",
        version=1,
    )

    validate_record_authority(record)
    assert record.policy_version == MEMORY_POLICY_VERSION
    assert record.scope is MemoryScope.USER


@pytest.mark.unit
def test_turn_outbox_key_is_stable_and_contains_no_message_content() -> None:
    """确认幂等键只使用稳定行标识，不复制用户消息或画像正文。"""
    key = build_turn_outbox_key("fixture-session", 42)

    assert key == "memory:turn-committed:fixture-session:42"
    assert "贵州茅台" not in key
    with pytest.raises(MemoryContractError):
        build_turn_outbox_key("fixture-session", 0)


@pytest.mark.unit
def test_authoritative_record_rejects_conflicting_kind_source_and_evidence() -> None:
    """确认权威合同不能表达空画像、混合载荷或伪造显式来源。"""
    common = {
        "record_id": "fixture-record-invalid",
        "user_id": "fixture-user-memory",
        "category": "profile",
        "status": MemoryRecordStatus.ACTIVE,
        "version": 1,
    }
    with pytest.raises(MemoryContractError, match="profile_field and value"):
        MemoryRecord(
            **common,
            kind=MemoryValueKind.STRUCTURED_PROFILE,
            profile_field=ProfileField.RISK_LEVEL,
            value=None,
            source=MemorySource.USER_COMMAND,
        )
    with pytest.raises(MemoryContractError, match="evidence_ref"):
        MemoryRecord(
            **common,
            kind=MemoryValueKind.TEXT,
            content="以后回答先给结论",
            source=MemorySource.USER_COMMAND,
        )
    with pytest.raises(MemoryContractError, match="explicit-user activation"):
        MemoryRecord(
            **common,
            kind=MemoryValueKind.STRUCTURED_PROFILE,
            profile_field=ProfileField.RISK_LEVEL,
            value="balanced",
            source=MemorySource.MODEL_INFERRED,
            activation_source=ActivationSource.EXPLICIT_USER,
            evidence_ref="message:fixture-3",
        )


@pytest.mark.unit
def test_turn_outbox_contract_rejects_cross_field_mismatch() -> None:
    """确认 Outbox 会话、聚合、负载和幂等键不能分别指向不同轮次。"""
    payload = TurnCommittedPayload(
        session_id="fixture-session-a",
        user_message_id=10,
        assistant_message_id=11,
        state_version=0,
    )
    with pytest.raises(MemoryContractError, match="session_id must match"):
        NewOutboxTask(
            user_id="fixture-user",
            session_id="fixture-session-b",
            aggregate_type="chat_turn",
            aggregate_id="fixture-session-a",
            task_kind=OutboxTaskKind.TURN_COMMITTED,
            idempotency_key=build_turn_outbox_key("fixture-session-a", 10),
            payload=payload,
        )
    with pytest.raises(MemoryContractError, match="idempotency_key"):
        NewOutboxTask(
            user_id="fixture-user",
            session_id="fixture-session-a",
            aggregate_type="chat_turn",
            aggregate_id="fixture-session-a",
            task_kind=OutboxTaskKind.TURN_COMMITTED,
            idempotency_key="arbitrary-key",
            payload=payload,
        )
