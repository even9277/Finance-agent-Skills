"""以 SQLAlchemy 实现用户显式记忆写入、确认和软删除。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.memory.authority import AuthorityMutationResult
from backend.db.models import (
    MemoryAuditEventRow,
    MemoryCandidateRow,
    MemoryRecordRow,
    UserInvestProfile,
)
from backend.infrastructure.memory.index_tasks import enqueue_index_delete, enqueue_index_upsert
from src.memory.contracts import (
    MEMORY_POLICY_VERSION,
    ActivationSource,
    CandidateReasonCode,
    CandidateStatus,
    DerivedConsistencyStatus,
    MemoryAuditAction,
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    MemorySource,
    MemoryValueKind,
    ProfileField,
    ProfileValue,
)

_PROFILE_COLUMN_BY_FIELD = {
    ProfileField.RISK_LEVEL: "risk_level",
    ProfileField.INVESTMENT_HORIZON: "investment_horizon",
    ProfileField.EXPECTED_RETURN_MIN: "expected_return_min",
    ProfileField.EXPECTED_RETURN_MAX: "expected_return_max",
    ProfileField.SECTORS: "sectors",
    ProfileField.CONSTRAINTS: "constraints",
}


class SqlAlchemyAuthoritativeMemoryRepository:
    """复用调用方事务，把有效记录、兼容画像与审计一起提交。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def write_profile(
        self,
        *,
        user_id: str,
        field: ProfileField,
        value: ProfileValue,
        source: MemorySource,
        evidence_ref: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult:
        """写入用户确认画像，并保持旧 ``user_invest_profiles`` 读取兼容。"""
        if source not in {
            MemorySource.USER_UI,
            MemorySource.USER_COMMAND,
            MemorySource.USER_CONFIRMATION,
        }:
            raise ValueError("authoritative profile writes require explicit user source")
        column = _PROFILE_COLUMN_BY_FIELD.get(field)
        if column is None:
            raise ValueError("profile field is not backed by the compatibility profile")
        profile = await self._db.scalar(
            select(UserInvestProfile)
            .where(UserInvestProfile.user_id == user_id)
            .with_for_update()
        )
        if profile is None:
            profile = UserInvestProfile(user_id=user_id, updated_by="user")
            self._db.add(profile)
        setattr(profile, column, _json_value(value))
        profile.updated_by = "user"
        profile.updated_at = _utc_naive()

        row = await self._db.scalar(
            select(MemoryRecordRow)
            .where(
                MemoryRecordRow.user_id == user_id,
                MemoryRecordRow.kind == MemoryValueKind.STRUCTURED_PROFILE.value,
                MemoryRecordRow.profile_field == field.value,
                MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
            )
            .order_by(MemoryRecordRow.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if row is None:
            record = MemoryRecord(
                record_id=uuid.uuid4().hex,
                user_id=user_id,
                kind=MemoryValueKind.STRUCTURED_PROFILE,
                category="profile",
                status=MemoryRecordStatus.ACTIVE,
                source=source,
                version=1,
                scope=MemoryScope.USER,
                profile_field=field,
                value=value,
                evidence_ref=evidence_ref,
                activation_source=(
                    ActivationSource.USER_CONFIRMED
                    if source is MemorySource.USER_CONFIRMATION
                    else ActivationSource.EXPLICIT_USER
                ),
            )
            row = _record_row(record)
            self._db.add(row)
            action = MemoryAuditAction.CREATED
        else:
            row.value_json = _json_value(value)
            row.source = source.value
            row.evidence_ref = evidence_ref
            row.activation_source = (
                ActivationSource.USER_CONFIRMED.value
                if source is MemorySource.USER_CONFIRMATION
                else ActivationSource.EXPLICIT_USER.value
            )
            row.policy_version = MEMORY_POLICY_VERSION
            row.version += 1
            row.deleted_at = None
            action = MemoryAuditAction.UPDATED
        self._audit(
            user_id=user_id,
            record_id=row.id,
            action=action,
            after_status=MemoryRecordStatus.ACTIVE.value,
            reason_code="EXPLICIT_USER_WRITE",
            trace_id=trace_id,
        )
        await self._db.flush()
        return _result(row)

    async def add_text(
        self,
        *,
        user_id: str,
        category: str,
        content: str,
        source: MemorySource,
        evidence_ref: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult:
        """新增显式文本记忆；M5 中 PostgreSQL 即完整权威状态。"""
        if source not in {MemorySource.USER_UI, MemorySource.USER_COMMAND}:
            raise ValueError("authoritative text writes require explicit user source")
        record = MemoryRecord(
            record_id=uuid.uuid4().hex,
            user_id=user_id,
            kind=MemoryValueKind.TEXT,
            category=category,
            status=MemoryRecordStatus.ACTIVE,
            source=source,
            version=1,
            content=content,
            evidence_ref=evidence_ref,
            activation_source=ActivationSource.EXPLICIT_USER,
        )
        row = _record_row(record)
        self._db.add(row)
        self._audit(
            user_id=user_id,
            record_id=row.id,
            action=MemoryAuditAction.CREATED,
            after_status=MemoryRecordStatus.ACTIVE.value,
            reason_code="EXPLICIT_USER_WRITE",
            trace_id=trace_id,
        )
        await self._db.flush()
        await enqueue_index_upsert(self._db, row, trace_id=trace_id)
        return _result(row, consistency_status=DerivedConsistencyStatus.PENDING)

    async def update_text(
        self,
        *,
        user_id: str,
        record_id: str,
        content: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult | None:
        """先按 PostgreSQL 所有权过滤，再更新文本；不信任 Provider metadata。"""
        row = await self._owned_active_record(user_id, record_id)
        if row is None or row.kind != MemoryValueKind.TEXT.value:
            return None
        if not content.strip():
            raise ValueError("memory content must not be blank")
        row.content = content.strip()
        row.source = MemorySource.USER_UI.value
        row.activation_source = ActivationSource.EXPLICIT_USER.value
        row.policy_version = MEMORY_POLICY_VERSION
        row.version += 1
        self._audit(
            user_id=user_id,
            record_id=row.id,
            action=MemoryAuditAction.UPDATED,
            after_status=MemoryRecordStatus.ACTIVE.value,
            reason_code="EXPLICIT_USER_WRITE",
            trace_id=trace_id,
        )
        await self._db.flush()
        await enqueue_index_upsert(self._db, row, trace_id=trace_id)
        return _result(row, consistency_status=DerivedConsistencyStatus.PENDING)

    async def delete_record(
        self,
        *,
        user_id: str,
        record_id: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult | None:
        """按用户软删除权威记录；M6 前没有派生索引，因此立即一致。"""
        row = await self._owned_active_record(user_id, record_id)
        if row is None:
            return None
        row.status = MemoryRecordStatus.INACTIVE.value
        row.deleted_at = _utc_naive()
        row.version += 1
        self._audit(
            user_id=user_id,
            record_id=row.id,
            action=MemoryAuditAction.DELETED,
            after_status=MemoryRecordStatus.INACTIVE.value,
            reason_code="EXPLICIT_USER_DELETE",
            trace_id=trace_id,
        )
        await self._db.flush()
        await enqueue_index_delete(self._db, row, trace_id=trace_id)
        return _result(row, consistency_status=DerivedConsistencyStatus.PENDING)

    async def confirm_candidate(
        self,
        *,
        user_id: str,
        candidate_id: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult | None:
        """确认高影响候选，并通过同一显式画像写路径取得权威效力。"""
        candidate = await self._db.scalar(
            select(MemoryCandidateRow)
            .where(
                MemoryCandidateRow.id == candidate_id,
                MemoryCandidateRow.user_id == user_id,
                MemoryCandidateRow.status.in_(
                    (
                        CandidateStatus.CONFIRMATION_REQUIRED.value,
                        CandidateStatus.CONFLICTED.value,
                    )
                ),
            )
            .with_for_update()
        )
        if candidate is None or candidate.profile_field is None:
            return None
        result = await self.write_profile(
            user_id=user_id,
            field=ProfileField(candidate.profile_field),
            value=_profile_value(candidate.value_json),
            source=MemorySource.USER_CONFIRMATION,
            evidence_ref=f"candidate:{candidate.id}",
            trace_id=trace_id,
        )
        before = candidate.status
        candidate.status = CandidateStatus.PROMOTED.value
        candidate.decision_reason = CandidateReasonCode.USER_CONFIRMED.value
        candidate.reviewed_at = _utc_naive()
        candidate.reviewed_by = "user"
        self._audit(
            user_id=user_id,
            record_id=result.record_id,
            candidate_id=candidate.id,
            action=MemoryAuditAction.CONFIRMED,
            before_status=before,
            after_status=CandidateStatus.PROMOTED.value,
            reason_code=CandidateReasonCode.USER_CONFIRMED.value,
            trace_id=trace_id,
        )
        await self._db.flush()
        return AuthorityMutationResult(
            record_id=result.record_id,
            status=result.status,
            consistency_status=result.consistency_status,
            version=result.version,
            candidate_status=CandidateStatus.PROMOTED,
        )

    async def _owned_active_record(
        self,
        user_id: str,
        record_id: str,
    ) -> MemoryRecordRow | None:
        """按记录 ID 与认证用户双重过滤，并为写操作锁行。"""
        return await self._db.scalar(
            select(MemoryRecordRow)
            .where(
                MemoryRecordRow.id == record_id,
                MemoryRecordRow.user_id == user_id,
                MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
            )
            .with_for_update()
        )

    def _audit(
        self,
        *,
        user_id: str,
        action: MemoryAuditAction,
        after_status: str,
        reason_code: str,
        trace_id: str | None,
        record_id: str | None = None,
        candidate_id: str | None = None,
        before_status: str | None = None,
    ) -> None:
        """只写状态和原因码；画像值、文本正文与用户标识不进入日志。"""
        self._db.add(
            MemoryAuditEventRow(
                id=uuid.uuid4().hex,
                user_id=user_id,
                record_id=record_id,
                candidate_id=candidate_id,
                action=action.value,
                actor=MemorySource.USER_CONFIRMATION.value,
                before_status=before_status,
                after_status=after_status,
                reason_code=reason_code,
                trace_id=trace_id,
            )
        )


def _record_row(record: MemoryRecord) -> MemoryRecordRow:
    """把已通过领域权威校验的记录转换为 ORM 行。"""
    return MemoryRecordRow(
        id=record.record_id,
        user_id=record.user_id,
        kind=record.kind.value,
        category=record.category,
        profile_field=record.profile_field.value if record.profile_field else None,
        value_json=_json_value(record.value),
        content=record.content,
        status=record.status.value,
        scope=record.scope.value,
        version=record.version,
        source=record.source.value,
        evidence_ref=record.evidence_ref,
        policy_version=record.policy_version,
        activation_source=record.activation_source.value,
        expires_at=record.expires_at,
        deleted_at=record.deleted_at,
    )


def _result(
    row: MemoryRecordRow,
    *,
    consistency_status: DerivedConsistencyStatus = DerivedConsistencyStatus.CONSISTENT,
) -> AuthorityMutationResult:
    """把 ORM 行映射为不依赖 Provider 的稳定应用结果。"""
    return AuthorityMutationResult(
        record_id=row.id,
        status=MemoryRecordStatus(row.status),
        consistency_status=consistency_status,
        version=row.version,
    )


def _json_value(value: ProfileValue | None) -> str | float | list[str] | None:
    """将不可变画像集合转换为 JSON 数组。"""
    return list(value) if isinstance(value, tuple) else value


def _profile_value(value: object) -> ProfileValue:
    """从受控候选 JSON 恢复领域画像值。"""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    if isinstance(value, (str, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    raise ValueError("candidate profile value is invalid")


def _utc_naive() -> datetime:
    """返回与现有无时区数据库列一致的 UTC 时间。"""
    return datetime.now(UTC).replace(tzinfo=None)
