"""以 PostgreSQL/SQLAlchemy 实现长期记忆候选治理与权威写入。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.memory.candidates import CandidateGovernanceResult
from backend.db.models import (
    MemoryAuditEventRow,
    MemoryCandidateEvidenceRow,
    MemoryCandidateRow,
    MemoryRecordRow,
)
from backend.infrastructure.memory.index_tasks import enqueue_index_upsert
from src.memory.contracts import (
    MEMORY_POLICY_VERSION,
    ActivationSource,
    CandidateDraft,
    CandidateReasonCode,
    CandidateSignals,
    CandidateStatus,
    MemoryAuditAction,
    MemoryCandidate,
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    MemorySource,
)
from src.memory.policy import evaluate_candidate_promotion

_CANDIDATE_RETENTION_DAYS = 30
_AUTO_MEMORY_RETENTION_DAYS = 90


class SqlAlchemyCandidateGovernanceRepository:
    """在调用方事务内完成候选聚合、冲突处理、晋升与安全审计。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def govern(
        self,
        *,
        user_id: str,
        drafts: tuple[CandidateDraft, ...],
        prompt_version: str,
        summary_version: int,
        state_version: int,
        trace_id: str | None,
    ) -> CandidateGovernanceResult:
        """合并用户证据并执行模型不可覆盖的确定性状态转换。

        Args:
            user_id: 已由 Worker 复核的会话所有者。
            drafts: 通过候选 schema/source gate 的抽取草稿。
            prompt_version: 生成候选所用的版本化 Prompt。
            summary_version: 触发抽取的 last-good 摘要版本。
            state_version: 抽取允许读取的 Working State 上界。
            trace_id: 关联前台轮次与后台任务的安全追踪标识。

        Returns:
            不含正文和用户标识的创建、晋升、确认与冲突计数。
        """
        created_count = 0
        promoted_count = 0
        confirmation_required_count = 0
        conflicted_count = 0
        for draft in drafts:
            created, status = await self._govern_one(
                user_id=user_id,
                draft=draft,
                prompt_version=prompt_version,
                summary_version=summary_version,
                state_version=state_version,
                trace_id=trace_id,
            )
            created_count += int(created)
            promoted_count += int(status is CandidateStatus.PROMOTED)
            confirmation_required_count += int(
                status is CandidateStatus.CONFIRMATION_REQUIRED
            )
            conflicted_count += int(status is CandidateStatus.CONFLICTED)
        await self._db.flush()
        return CandidateGovernanceResult(
            extracted_count=len(drafts),
            created_count=created_count,
            promoted_count=promoted_count,
            confirmation_required_count=confirmation_required_count,
            conflicted_count=conflicted_count,
        )

    async def _govern_one(
        self,
        *,
        user_id: str,
        draft: CandidateDraft,
        prompt_version: str,
        summary_version: int,
        state_version: int,
        trace_id: str | None,
    ) -> tuple[bool, CandidateStatus]:
        """治理一条规范化候选，并把重复证据收敛到同一候选。"""
        fingerprint = _fingerprint(draft)
        await self._lock_fingerprint(user_id, fingerprint)
        row = await self._db.scalar(
            select(MemoryCandidateRow)
            .where(
                MemoryCandidateRow.user_id == user_id,
                MemoryCandidateRow.kind == draft.kind.value,
                MemoryCandidateRow.category == draft.category,
                MemoryCandidateRow.fingerprint == fingerprint,
            )
            .order_by(MemoryCandidateRow.created_at)
            .limit(1)
            .with_for_update()
        )
        now = _utc_naive()
        created = row is None
        if row is None:
            candidate_id = uuid.uuid4().hex
            first_evidence = draft.evidence[0]
            candidate = MemoryCandidate(
                candidate_id=candidate_id,
                user_id=user_id,
                kind=draft.kind,
                category=draft.category,
                status=CandidateStatus.PENDING,
                source=MemorySource.MODEL_INFERRED,
                confidence=draft.confidence,
                fingerprint=fingerprint,
                idempotency_key=(
                    f"candidate:{fingerprint}:{first_evidence.message_id}"
                ),
                profile_field=draft.profile_field,
                value=draft.value,
                content=draft.content,
                evidence_ref=f"message:{first_evidence.message_id}",
                conflict_group_id=draft.conflict_key,
                expires_at=now + timedelta(days=_CANDIDATE_RETENTION_DAYS),
            )
            row = MemoryCandidateRow(
                id=candidate.candidate_id,
                user_id=candidate.user_id,
                kind=candidate.kind.value,
                category=candidate.category,
                profile_field=(
                    candidate.profile_field.value if candidate.profile_field else None
                ),
                value_json=_json_value(candidate.value),
                content=candidate.content,
                status=candidate.status.value,
                source=candidate.source.value,
                confidence=candidate.confidence,
                evidence_ref=candidate.evidence_ref,
                fingerprint=candidate.fingerprint,
                idempotency_key=candidate.idempotency_key,
                conflict_group_id=candidate.conflict_group_id,
                normalized_key=draft.normalized_key,
                policy_version=MEMORY_POLICY_VERSION,
                expires_at=candidate.expires_at,
                prompt_version=prompt_version,
                source_summary_version=summary_version,
                source_state_version=state_version,
            )
            self._db.add(row)
            await self._db.flush()
            self._audit(
                user_id=user_id,
                candidate_id=row.id,
                action=MemoryAuditAction.CREATED,
                before_status=None,
                after_status=CandidateStatus.PENDING,
                reason_code=CandidateReasonCode.AWAITING_MORE_EVIDENCE,
                trace_id=trace_id,
            )
        await self._append_evidence(row, draft)
        await self._db.flush()
        evidence_rows = list(
            (
                await self._db.execute(
                    select(MemoryCandidateEvidenceRow).where(
                        MemoryCandidateEvidenceRow.candidate_id == row.id,
                        MemoryCandidateEvidenceRow.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        conflicts = await self._conflicting_candidates(user_id, row, draft.conflict_key)
        signals = _signals(evidence_rows, len(conflicts))
        decision = evaluate_candidate_promotion(draft, signals, now=now)
        if conflicts:
            decision = evaluate_candidate_promotion(
                draft,
                CandidateSignals(
                    event_count=signals.event_count,
                    unique_query_count=signals.unique_query_count,
                    unique_session_count=signals.unique_session_count,
                    active_days=signals.active_days,
                    contradiction_count=max(1, signals.contradiction_count),
                    average_confidence=signals.average_confidence,
                    first_seen_at=signals.first_seen_at,
                    last_seen_at=signals.last_seen_at,
                ),
                now=now,
            )
            await self._quarantine_conflicts(user_id, conflicts, trace_id)
        previous_status = CandidateStatus(row.status)
        # 已晋升候选的重复证据只刷新统计，不把它倒退回 pending。
        target_status = (
            previous_status
            if previous_status is CandidateStatus.PROMOTED and not conflicts
            else decision.status
        )
        row.status = target_status.value
        row.decision_reason = decision.reason_code.value
        row.promotion_score = decision.score
        row.event_count = signals.event_count
        row.unique_query_count = signals.unique_query_count
        row.unique_session_count = signals.unique_session_count
        row.active_days = signals.active_days
        row.contradiction_count = max(signals.contradiction_count, len(conflicts))
        row.first_seen_at = signals.first_seen_at
        row.last_seen_at = signals.last_seen_at
        row.confidence = signals.average_confidence
        row.expires_at = signals.last_seen_at + timedelta(days=_CANDIDATE_RETENTION_DAYS)
        row.source_summary_version = max(row.source_summary_version, summary_version)
        row.source_state_version = max(row.source_state_version, state_version)
        if target_status is CandidateStatus.PROMOTED:
            await self._promote_text_candidate(row, trace_id)
        if previous_status is not target_status:
            self._audit(
                user_id=user_id,
                candidate_id=row.id,
                action=(
                    MemoryAuditAction.PROMOTED
                    if target_status is CandidateStatus.PROMOTED
                    else MemoryAuditAction.UPDATED
                ),
                before_status=previous_status,
                after_status=target_status,
                reason_code=decision.reason_code,
                trace_id=trace_id,
            )
        return created, target_status

    async def _append_evidence(
        self,
        candidate: MemoryCandidateRow,
        draft: CandidateDraft,
    ) -> None:
        """追加尚不存在的证据引用，重试不会重复增加频次。"""
        for evidence in draft.evidence:
            statement = select(MemoryCandidateEvidenceRow.id).where(
                MemoryCandidateEvidenceRow.candidate_id == candidate.id,
                MemoryCandidateEvidenceRow.user_id == candidate.user_id,
                MemoryCandidateEvidenceRow.message_id == evidence.message_id,
            )
            if evidence.state_event_id is None:
                statement = statement.where(
                    MemoryCandidateEvidenceRow.state_event_id.is_(None)
                )
            else:
                statement = statement.where(
                    MemoryCandidateEvidenceRow.state_event_id == evidence.state_event_id
                )
            if await self._db.scalar(statement) is not None:
                continue
            self._db.add(
                MemoryCandidateEvidenceRow(
                    candidate_id=candidate.id,
                    user_id=candidate.user_id,
                    session_id=evidence.session_id,
                    message_id=evidence.message_id,
                    state_event_id=evidence.state_event_id,
                    query_hash=evidence.query_hash,
                    observed_on=datetime.combine(evidence.observed_on, time.min),
                    confidence=evidence.confidence,
                    state_version=evidence.state_version,
                    summary_version=evidence.summary_version,
                )
            )

    async def _conflicting_candidates(
        self,
        user_id: str,
        current: MemoryCandidateRow,
        conflict_key: str | None,
    ) -> list[MemoryCandidateRow]:
        """查找同一治理槽位中含义不同且尚未终止的候选。"""
        if not conflict_key:
            return []
        return list(
            (
                await self._db.execute(
                    select(MemoryCandidateRow)
                    .where(
                        MemoryCandidateRow.user_id == user_id,
                        MemoryCandidateRow.id != current.id,
                        MemoryCandidateRow.conflict_group_id == conflict_key,
                        MemoryCandidateRow.fingerprint != current.fingerprint,
                        MemoryCandidateRow.status.not_in(
                            (
                                CandidateStatus.REJECTED.value,
                                CandidateStatus.EXPIRED.value,
                                CandidateStatus.SUPERSEDED.value,
                            )
                        ),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

    async def _quarantine_conflicts(
        self,
        user_id: str,
        conflicts: list[MemoryCandidateRow],
        trace_id: str | None,
    ) -> None:
        """隔离冲突候选，并停用它们先前自动晋升的文本记忆。"""
        for conflict in conflicts:
            previous = CandidateStatus(conflict.status)
            conflict.status = CandidateStatus.CONFLICTED.value
            conflict.decision_reason = CandidateReasonCode.CONTRADICTION_DETECTED.value
            records = list(
                (
                    await self._db.execute(
                        select(MemoryRecordRow).where(
                            MemoryRecordRow.user_id == user_id,
                            MemoryRecordRow.evidence_ref == f"candidate:{conflict.id}",
                            MemoryRecordRow.activation_source
                            == ActivationSource.POLICY_AUTO.value,
                            MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for record in records:
                record.status = MemoryRecordStatus.INACTIVE.value
                record.version += 1
            if previous is not CandidateStatus.CONFLICTED:
                self._audit(
                    user_id=user_id,
                    candidate_id=conflict.id,
                    action=MemoryAuditAction.UPDATED,
                    before_status=previous,
                    after_status=CandidateStatus.CONFLICTED,
                    reason_code=CandidateReasonCode.CONTRADICTION_DETECTED,
                    trace_id=trace_id,
                )

    async def _promote_text_candidate(
        self,
        candidate: MemoryCandidateRow,
        trace_id: str | None,
    ) -> None:
        """把通过治理的低影响文本候选写成唯一 PostgreSQL 权威记录。"""
        record_id = f"candidate-{candidate.id}"
        if await self._db.get(MemoryRecordRow, record_id) is not None:
            return
        record = MemoryRecord(
            record_id=record_id,
            user_id=candidate.user_id,
            kind=_memory_kind(candidate.kind),
            category=candidate.category,
            status=MemoryRecordStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            version=1,
            scope=MemoryScope.USER,
            content=candidate.content,
            evidence_ref=f"candidate:{candidate.id}",
            policy_version=candidate.policy_version,
            activation_source=ActivationSource.POLICY_AUTO,
            expires_at=_utc_naive() + timedelta(days=_AUTO_MEMORY_RETENTION_DAYS),
        )
        record_row = MemoryRecordRow(
            id=record.record_id,
            user_id=record.user_id,
            kind=record.kind.value,
            category=record.category,
            profile_field=None,
            value_json=None,
            content=record.content,
            status=record.status.value,
            scope=record.scope.value,
            version=record.version,
            source=record.source.value,
            evidence_ref=record.evidence_ref,
            policy_version=record.policy_version,
            activation_source=record.activation_source.value,
            expires_at=record.expires_at,
        )
        self._db.add(record_row)
        await self._db.flush()
        await enqueue_index_upsert(self._db, record_row, trace_id=trace_id)
        self._audit(
            user_id=candidate.user_id,
            candidate_id=candidate.id,
            record_id=record.record_id,
            action=MemoryAuditAction.PROMOTED,
            before_status=CandidateStatus.PENDING,
            after_status=MemoryRecordStatus.ACTIVE,
            reason_code=CandidateReasonCode.PROMOTION_GATES_PASSED,
            trace_id=trace_id,
        )

    async def _lock_fingerprint(self, user_id: str, fingerprint: str) -> None:
        """PostgreSQL 用事务 advisory lock 防止跨会话并发创建重复候选。"""
        bind = self._db.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        from sqlalchemy import text

        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"memory-candidate:{user_id}:{fingerprint}"},
        )

    def _audit(
        self,
        *,
        user_id: str,
        candidate_id: str,
        action: MemoryAuditAction,
        before_status: CandidateStatus | None,
        after_status: CandidateStatus | MemoryRecordStatus,
        reason_code: CandidateReasonCode,
        trace_id: str | None,
        record_id: str | None = None,
    ) -> None:
        """只记录安全状态元数据，禁止候选正文和值进入审计表。"""
        self._db.add(
            MemoryAuditEventRow(
                id=uuid.uuid4().hex,
                user_id=user_id,
                record_id=record_id,
                candidate_id=candidate_id,
                action=action.value,
                actor=MemorySource.SYSTEM.value,
                before_status=before_status.value if before_status else None,
                after_status=after_status.value,
                reason_code=reason_code.value,
                trace_id=trace_id,
            )
        )


def _fingerprint(draft: CandidateDraft) -> str:
    """由归一化业务键生成不泄露正文的候选指纹。"""
    material = f"{draft.kind.value}|{draft.category}|{draft.normalized_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _signals(
    evidence_rows: list[MemoryCandidateEvidenceRow],
    contradiction_count: int,
) -> CandidateSignals:
    """从权威证据行计算 Deep 治理信号，不采信 Provider 自报次数。"""
    observed = [row.observed_on for row in evidence_rows]
    return CandidateSignals(
        event_count=len(evidence_rows),
        unique_query_count=len({row.query_hash for row in evidence_rows}),
        unique_session_count=len({row.session_id for row in evidence_rows}),
        active_days=len({row.observed_on.date() for row in evidence_rows}),
        contradiction_count=contradiction_count,
        average_confidence=(
            sum(row.confidence for row in evidence_rows) / len(evidence_rows)
        ),
        first_seen_at=min(observed),
        last_seen_at=max(observed),
    )


def _json_value(value: object) -> object:
    """把不可变元组转换为数据库 JSON 支持的列表。"""
    return list(value) if isinstance(value, tuple) else value


def _memory_kind(value: str):
    """延迟导入枚举转换，保持记录构造处的类型检查清晰。"""
    from src.memory.contracts import MemoryValueKind

    return MemoryValueKind(value)


def _utc_naive() -> datetime:
    """返回与现有无时区数据库列一致的 UTC 时间。"""
    return datetime.now(UTC).replace(tzinfo=None)
