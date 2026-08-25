"""验证 M5 长期候选的来源边界、确定性评分和状态转换。"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.candidates import (  # noqa: E402
    CandidateExtractionRequest,
    CandidateSourceMessage,
    validate_candidate_drafts,
)
from src.memory.contracts import (  # noqa: E402
    CandidateDraft,
    CandidateEvidence,
    CandidateReasonCode,
    CandidateSignals,
    CandidateStatus,
    MemoryContractError,
    MemoryValueKind,
    ProfileField,
)
from src.memory.policy import evaluate_candidate_promotion  # noqa: E402


def _evidence(
    message_id: int,
    *,
    session_id: str = "fixture-session",
    query_hash: str | None = None,
    observed_on: date = date(2026, 8, 25),
) -> CandidateEvidence:
    """创建无真实正文的用户侧证据夹具。"""
    return CandidateEvidence(
        session_id=session_id,
        message_id=message_id,
        source_role="user",
        query_hash=query_hash or f"query-{message_id}",
        observed_on=observed_on,
        confidence=0.95,
        state_version=1,
        summary_version=1,
    )


def _text_draft(*evidence: CandidateEvidence) -> CandidateDraft:
    """创建低影响回答偏好候选。"""
    return CandidateDraft(
        kind=MemoryValueKind.TEXT,
        category="response_preference",
        normalized_key="response_preference:conclusion_first",
        confidence=0.95,
        evidence=tuple(evidence),
        content="回答先给结论，再解释风险",
        conflict_key="response_preference:default",
    )


@pytest.mark.unit
def test_candidate_evidence_rejects_assistant_source() -> None:
    """助手或工具输出不能伪装成用户证据。"""
    with pytest.raises(MemoryContractError, match="user message"):
        CandidateEvidence(
            session_id="fixture-session",
            message_id=1,
            source_role="assistant",
            query_hash="query-1",
            observed_on=date(2026, 8, 25),
            confidence=1.0,
        )


@pytest.mark.unit
def test_candidate_output_must_reference_frozen_user_message_and_be_unique() -> None:
    """Provider 不能引用窗口外消息，也不能重复返回同一规范键。"""
    request = CandidateExtractionRequest(
        session_id="fixture-session",
        summary_version=1,
        state_version=1,
        messages=(
            CandidateSourceMessage(
                message_id=10,
                content="以后先给结论",
                created_on=date(2026, 8, 25),
                query_hash="q-10",
            ),
        ),
    )
    with pytest.raises(MemoryContractError, match="outside"):
        validate_candidate_drafts(request, (_text_draft(_evidence(99)),))
    draft = _text_draft(_evidence(10))
    with pytest.raises(MemoryContractError, match="duplicate"):
        validate_candidate_drafts(request, (draft, draft))


@pytest.mark.unit
def test_high_impact_candidate_is_confirmation_only_even_when_score_is_high() -> None:
    """风险偏好候选永远不因分数高而自动写入权威画像。"""
    evidence = tuple(
        _evidence(
            index,
            session_id=f"session-{index}",
            observed_on=date(2026, 8, 20 + index),
        )
        for index in range(1, 4)
    )
    draft = CandidateDraft(
        kind=MemoryValueKind.STRUCTURED_PROFILE,
        category="profile_suggestion",
        normalized_key="profile:risk_level:aggressive",
        confidence=1.0,
        evidence=evidence,
        profile_field=ProfileField.RISK_LEVEL,
        value="aggressive",
        conflict_key="profile:risk_level",
    )
    decision = evaluate_candidate_promotion(
        draft,
        CandidateSignals(
            event_count=3,
            unique_query_count=3,
            unique_session_count=3,
            active_days=3,
            contradiction_count=0,
            average_confidence=1.0,
            first_seen_at=datetime(2026, 8, 20),
            last_seen_at=datetime(2026, 8, 25),
        ),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert decision.status is CandidateStatus.CONFIRMATION_REQUIRED
    assert decision.eligible is False
    assert decision.reason_code is CandidateReasonCode.HIGH_IMPACT_CONFIRMATION_REQUIRED


@pytest.mark.unit
def test_text_promotion_requires_repeat_unique_context_and_active_days() -> None:
    """单轮偏好保持 pending，跨会话/跨日期重复后才允许晋升。"""
    draft = _text_draft(_evidence(1))
    pending = evaluate_candidate_promotion(
        draft,
        CandidateSignals(
            event_count=1,
            unique_query_count=1,
            unique_session_count=1,
            active_days=1,
            contradiction_count=0,
            average_confidence=0.95,
            first_seen_at=datetime(2026, 8, 20),
            last_seen_at=datetime(2026, 8, 25),
        ),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert pending.status is CandidateStatus.PENDING
    promoted = evaluate_candidate_promotion(
        draft,
        CandidateSignals(
            event_count=3,
            unique_query_count=3,
            unique_session_count=2,
            active_days=2,
            contradiction_count=0,
            average_confidence=0.95,
            first_seen_at=datetime(2026, 8, 20),
            last_seen_at=datetime(2026, 8, 25),
        ),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert promoted.status is CandidateStatus.PROMOTED
    assert promoted.eligible is True
    assert promoted.reason_code is CandidateReasonCode.PROMOTION_GATES_PASSED


@pytest.mark.unit
def test_conflict_and_recency_are_hard_gates() -> None:
    """冲突或超过 30 天没有强化的候选不可自动晋升。"""
    draft = _text_draft(_evidence(1))
    signals = CandidateSignals(
        event_count=5,
        unique_query_count=5,
        unique_session_count=3,
        active_days=4,
        contradiction_count=1,
        average_confidence=1.0,
        first_seen_at=datetime(2026, 7, 1),
        last_seen_at=datetime(2026, 8, 20),
    )
    conflict = evaluate_candidate_promotion(
        draft,
        signals,
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert conflict.status is CandidateStatus.CONFLICTED
    stale = evaluate_candidate_promotion(
        draft,
        CandidateSignals(
            event_count=5,
            unique_query_count=5,
            unique_session_count=3,
            active_days=4,
            contradiction_count=0,
            average_confidence=1.0,
            first_seen_at=datetime(2026, 6, 1),
            last_seen_at=datetime(2026, 6, 20),
        ),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert stale.status is CandidateStatus.EXPIRED
    assert stale.reason_code is CandidateReasonCode.RETENTION_EXPIRED
