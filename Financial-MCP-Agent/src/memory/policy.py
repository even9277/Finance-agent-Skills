"""定义不依赖模型或 Provider 的记忆权威基础规则。"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from .contracts import (
    ActivationSource,
    CandidateDraft,
    CandidateReasonCode,
    CandidateSignals,
    CandidateStatus,
    MemoryContractError,
    MemoryRecord,
    MemorySource,
    ProfileField,
    PromotionDecision,
)

HIGH_IMPACT_PROFILE_FIELDS = frozenset(
    {
        ProfileField.RISK_LEVEL,
        ProfileField.INVESTMENT_HORIZON,
        ProfileField.EXPECTED_RETURN_MIN,
        ProfileField.EXPECTED_RETURN_MAX,
        ProfileField.SECTORS,
        ProfileField.WATCHLIST,
        ProfileField.CONSTRAINTS,
    }
)

AUTO_PROMOTABLE_TEXT_CATEGORIES = frozenset(
    {
        "response_preference",
        "topic_interest",
    }
)
MIN_EVENT_COUNT = 3
MIN_UNIQUE_QUERY_COUNT = 3
MIN_UNIQUE_SESSION_COUNT = 2
MIN_ACTIVE_DAYS = 2
MAX_CANDIDATE_AGE_DAYS = 30
PROMOTION_SCORE_THRESHOLD = 0.80


def requires_user_confirmation(field: ProfileField, source: MemorySource) -> bool:
    """判断画像候选是否必须取得用户确认。

    Args:
        field: 候选准备影响的结构化画像字段。
        source: 候选证据来源。

    Returns:
        模型推断高影响字段时返回 ``True``；显式用户来源返回 ``False``。
    """
    return source is MemorySource.MODEL_INFERRED and field in HIGH_IMPACT_PROFILE_FIELDS


def validate_record_authority(record: MemoryRecord) -> None:
    """拒绝把模型推断的高影响画像直接标记为自动生效。

    Args:
        record: 准备写入 PostgreSQL 权威表的领域记录。

    Raises:
        MemoryContractError: 记录绕过了冻结的用户确认边界。
    """
    if (
        record.profile_field is not None
        and requires_user_confirmation(record.profile_field, record.source)
        and record.activation_source is ActivationSource.POLICY_AUTO
    ):
        raise MemoryContractError(
            "model-inferred high-impact profile cannot be auto-activated"
        )


def evaluate_candidate_promotion(
    draft: CandidateDraft,
    signals: CandidateSignals,
    *,
    now: datetime | None = None,
) -> PromotionDecision:
    """按冻结的硬门槛和六维信号决定候选能否自动晋升。

    Args:
        draft: 已通过 schema/source gate 的候选草稿。
        signals: 由权威证据行聚合出的次数、会话、日期和冲突统计。
        now: 可注入的 UTC 当前时间，便于离线评测稳定复现。

    Returns:
        带原因码和六维分数的确定性决策；模型不能覆盖该结果。
    """
    current = (now or datetime.now(UTC)).replace(tzinfo=None)
    age_days = max(0.0, (current - signals.last_seen_at).total_seconds() / 86_400)
    frequency = min(1.0, math.log1p(signals.event_count) / math.log1p(MIN_EVENT_COUNT))
    relevance = signals.average_confidence
    query_diversity = min(1.0, signals.unique_query_count / MIN_UNIQUE_QUERY_COUNT)
    recency = max(0.0, 0.5 ** (age_days / 14.0))
    consolidation = min(
        1.0,
        (
            signals.unique_session_count / MIN_UNIQUE_SESSION_COUNT
            + signals.active_days / MIN_ACTIVE_DAYS
        )
        / 2,
    )
    content = (draft.content or str(draft.value or "")).strip()
    conceptual_richness = min(1.0, len(content) / 12.0)
    score = round(
        0.24 * frequency
        + 0.30 * relevance
        + 0.15 * query_diversity
        + 0.15 * recency
        + 0.10 * consolidation
        + 0.06 * conceptual_richness,
        6,
    )

    if draft.kind.value == "structured_profile":
        return _decision(
            CandidateStatus.CONFIRMATION_REQUIRED,
            CandidateReasonCode.HIGH_IMPACT_CONFIRMATION_REQUIRED,
            score,
            frequency,
            relevance,
            query_diversity,
            recency,
            consolidation,
            conceptual_richness,
        )
    if draft.category not in AUTO_PROMOTABLE_TEXT_CATEGORIES:
        return _decision(
            CandidateStatus.CONFIRMATION_REQUIRED,
            CandidateReasonCode.SOURCE_NOT_AUTHORIZED,
            score,
            frequency,
            relevance,
            query_diversity,
            recency,
            consolidation,
            conceptual_richness,
        )
    if age_days > MAX_CANDIDATE_AGE_DAYS:
        return _decision(
            CandidateStatus.EXPIRED,
            CandidateReasonCode.RETENTION_EXPIRED,
            score,
            frequency,
            relevance,
            query_diversity,
            recency,
            consolidation,
            conceptual_richness,
        )
    if signals.contradiction_count > 0:
        return _decision(
            CandidateStatus.CONFLICTED,
            CandidateReasonCode.CONTRADICTION_DETECTED,
            score,
            frequency,
            relevance,
            query_diversity,
            recency,
            consolidation,
            conceptual_richness,
        )
    gates_passed = (
        signals.event_count >= MIN_EVENT_COUNT
        and signals.unique_query_count >= MIN_UNIQUE_QUERY_COUNT
        and signals.unique_session_count >= MIN_UNIQUE_SESSION_COUNT
        and signals.active_days >= MIN_ACTIVE_DAYS
        and score >= PROMOTION_SCORE_THRESHOLD
    )
    return _decision(
        CandidateStatus.PROMOTED if gates_passed else CandidateStatus.PENDING,
        (
            CandidateReasonCode.PROMOTION_GATES_PASSED
            if gates_passed
            else CandidateReasonCode.AWAITING_MORE_EVIDENCE
        ),
        score,
        frequency,
        relevance,
        query_diversity,
        recency,
        consolidation,
        conceptual_richness,
        eligible=gates_passed,
    )


def _decision(
    status: CandidateStatus,
    reason_code: CandidateReasonCode,
    score: float,
    frequency: float,
    relevance: float,
    query_diversity: float,
    recency: float,
    consolidation: float,
    conceptual_richness: float,
    *,
    eligible: bool = False,
) -> PromotionDecision:
    """集中构造规范化决策，避免不同分支遗漏评分字段。"""
    return PromotionDecision(
        status=status,
        reason_code=reason_code,
        eligible=eligible,
        score=score,
        frequency=frequency,
        relevance=relevance,
        query_diversity=query_diversity,
        recency=recency,
        consolidation=consolidation,
        conceptual_richness=conceptual_richness,
    )
