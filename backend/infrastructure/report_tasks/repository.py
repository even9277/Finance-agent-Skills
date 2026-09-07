"""实现报告任务治理表的 SQLAlchemy 原子创建与复用。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.report_tasks.contracts import (
    ExistingReportTaskDecision,
    ReportIdempotencyConflictError,
    ReportIdempotencyStatus,
    ReportTaskClaim,
    ReportTaskCreateResult,
    ReportStageSnapshot,
    ReportTaskSnapshot,
    ReportTaskSnapshotRecord,
    ReportTaskSnapshotUpdate,
    decide_existing_report_task,
)
from backend.application.report_progress.contracts import (
    ReportStage,
    ReportStageStatus,
    ReportTaskStatus,
)
from backend.application.report_progress.snapshot import (
    REPORT_GENERATION_FAILED_CODE,
    REPORT_GENERATION_FAILED_MESSAGE,
)
from backend.db.models import Report, ReportTaskGovernanceRow


class ReportTaskPersistenceError(RuntimeError):
    """表示治理行与报告权威事实不一致或无法完成原子写入。"""


class SqlAlchemyReportTaskClaimRepository:
    """使用数据库唯一约束收敛跨进程报告创建竞争。

    首次创建将 ``Report`` 与治理行放入同一事务。并发失败方回滚整笔事务，
    再读取唯一约束获胜行；终态过期换代通过行锁串行化，绝不删除治理行制造空窗。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_reuse(self, claim: ReportTaskClaim) -> ReportTaskCreateResult:
        """原子创建、复用或换代用户作用域内的报告任务。

        Args:
            claim: 仅含摘要、指纹、用户和期限的低敏声明。

        Returns:
            当前唯一任务和本请求是否拥有后台派发权。

        Raises:
            ReportIdempotencyConflictError: 同一键已绑定不同命令指纹。
            ReportTaskPersistenceError: 治理行引用的报告缺失，或唯一竞争无法收口。
        """
        existing = await self._load_governance_row(claim, for_update=True)
        if existing is not None:
            return await self._resolve_existing(existing, claim)
        return await self._create_or_follow_winner(claim)

    async def _create_or_follow_winner(self, claim: ReportTaskClaim) -> ReportTaskCreateResult:
        task_id = str(uuid.uuid4())
        report_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        report = Report(
            id=report_id,
            task_id=task_id,
            user_id=claim.user_id,
            status="pending",
            progress=0,
        )
        governance = ReportTaskGovernanceRow(
            id=str(uuid.uuid4()),
            user_id=claim.user_id,
            key_digest=claim.key_digest,
            request_fingerprint=claim.request_fingerprint,
            task_id=task_id,
            report_id=report_id,
            generation=1,
            expires_at=claim.expires_at,
            snapshot_version=1,
            stage_states=[],
            created_at=now,
            updated_at=now,
        )
        self._session.add_all((report, governance))
        try:
            await self._session.commit()
        except IntegrityError:
            # 唯一约束失败会让整个事务（包含候选 Report）回滚；随后只跟随获胜行。
            await self._session.rollback()
            winner = await self._load_governance_row(claim, for_update=True)
            if winner is None:
                raise ReportTaskPersistenceError("报告任务唯一竞争未找到获胜治理行") from None
            return await self._resolve_existing(winner, claim)
        return self._result(governance, report, ReportIdempotencyStatus.CREATED)

    async def _resolve_existing(
        self,
        governance: ReportTaskGovernanceRow,
        claim: ReportTaskClaim,
    ) -> ReportTaskCreateResult:
        report = await self._session.get(Report, governance.report_id)
        if report is None or report.user_id != claim.user_id:
            await self._session.rollback()
            raise ReportTaskPersistenceError("报告任务治理行缺少匹配的用户报告")

        decision = decide_existing_report_task(
            existing_fingerprint=governance.request_fingerprint,
            request_fingerprint=claim.request_fingerprint,
            task_status=report.status,
            expires_at=governance.expires_at,
            now=datetime.now(UTC),
        )
        if decision is ExistingReportTaskDecision.CONFLICT:
            await self._session.rollback()
            raise ReportIdempotencyConflictError
        if decision is ExistingReportTaskDecision.REPLAY:
            await self._session.commit()
            return self._result(governance, report, ReportIdempotencyStatus.REPLAYED)
        return await self._rotate_expired(governance, claim)

    async def _rotate_expired(
        self,
        governance: ReportTaskGovernanceRow,
        claim: ReportTaskClaim,
    ) -> ReportTaskCreateResult:
        task_id = str(uuid.uuid4())
        report_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        report = Report(
            id=report_id,
            task_id=task_id,
            user_id=claim.user_id,
            status="pending",
            progress=0,
        )
        governance.task_id = task_id
        governance.report_id = report_id
        governance.generation += 1
        governance.expires_at = claim.expires_at
        governance.snapshot_version = 1
        governance.stage_states = []
        governance.updated_at = now
        self._session.add(report)
        await self._session.commit()
        return self._result(governance, report, ReportIdempotencyStatus.CREATED)

    async def _load_governance_row(
        self,
        claim: ReportTaskClaim,
        *,
        for_update: bool,
    ) -> ReportTaskGovernanceRow | None:
        query = select(ReportTaskGovernanceRow).where(
            ReportTaskGovernanceRow.user_id == claim.user_id,
            ReportTaskGovernanceRow.key_digest == claim.key_digest,
        )
        if for_update:
            query = query.with_for_update()
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def _result(
        governance: ReportTaskGovernanceRow,
        report: Report,
        outcome: ReportIdempotencyStatus,
    ) -> ReportTaskCreateResult:
        return ReportTaskCreateResult(
            task_id=governance.task_id,
            report_id=governance.report_id,
            status=ReportTaskStatus(report.status),
            idempotency_status=outcome,
            expires_at=governance.expires_at,
            generation=governance.generation,
        )


class SqlAlchemyReportTaskSnapshotRepository:
    """以 Report 与治理行的同一事务维护最新任务快照。

    Redis 和 SSE 只能消费本适配器提交后的返回值。历史任务若没有治理行，
    仍更新原 Report 以保留 D05 兼容行为，但不会伪造可跨实例的版本快照。
    """

    _TERMINAL_TASK_STATUSES = {
        ReportTaskStatus.COMPLETED.value,
        ReportTaskStatus.FAILED.value,
    }
    _TERMINAL_STAGE_STATUSES = {
        ReportStageStatus.SUCCEEDED,
        ReportStageStatus.FAILED,
        ReportStageStatus.SKIPPED,
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist_snapshot(
        self,
        update: ReportTaskSnapshotUpdate,
    ) -> ReportTaskSnapshotRecord | None:
        """提交单调 Report 状态与治理快照。

        Args:
            update: 已在应用层验证的状态、阶段和可选终态写入。

        Returns:
            提交后的完整快照记录；历史无治理行任务返回 ``None``。

        Raises:
            ReportTaskPersistenceError: Report 缺失、所有权不一致或阶段 JSON 损坏。
        """
        governance = await self._load_by_task(update.task_id, for_update=True)
        report_result = await self._session.execute(
            select(Report).where(Report.task_id == update.task_id).with_for_update()
        )
        report = report_result.scalar_one_or_none()
        if report is None or report.id != update.report_id:
            await self._session.rollback()
            raise ReportTaskPersistenceError("报告任务快照缺少匹配的 Report")
        if governance is not None and (
            governance.report_id != report.id or governance.user_id != report.user_id
        ):
            await self._session.rollback()
            raise ReportTaskPersistenceError("治理快照与 Report 所有权不一致")

        if report.status in self._TERMINAL_TASK_STATUSES:
            await self._session.commit()
            return self._record(governance, report) if governance is not None else None

        previous_status = report.status
        previous_progress = int(report.progress or 0)
        report.progress = max(previous_progress, update.progress)
        # 已运行任务不接受迟到的 pending；终态在上方直接锁定。
        report.status = (
            ReportTaskStatus.RUNNING.value
            if previous_status == ReportTaskStatus.RUNNING.value
            and update.status is ReportTaskStatus.PENDING
            else update.status.value
        )
        if update.status is ReportTaskStatus.COMPLETED:
            report.content = update.report_content
            report.error_msg = None
        elif update.status is ReportTaskStatus.FAILED:
            report.error_msg = update.report_error_msg

        if governance is None:
            await self._session.commit()
            return None

        previous_stages = self._decode_stages(governance.stage_states)
        merged_stages = self._merge_stages(previous_stages, update.stages)
        changed = (
            report.status != previous_status
            or report.progress != previous_progress
            or merged_stages != previous_stages
        )
        if changed:
            governance.snapshot_version += 1
            governance.stage_states = [
                {"stage": item.stage.value, "status": item.status.value}
                for item in merged_stages
            ]
            governance.updated_at = datetime.now(UTC)
        await self._session.commit()
        return self._record(governance, report)

    async def load_latest(self, task_id: str) -> ReportTaskSnapshotRecord | None:
        """读取任务当前的权威治理快照，不获取行锁。"""
        governance = await self._load_by_task(task_id, for_update=False)
        if governance is None:
            return None
        report = await self._session.get(Report, governance.report_id)
        if report is None or report.task_id != task_id or report.user_id != governance.user_id:
            raise ReportTaskPersistenceError("治理快照引用的 Report 不存在或所有权不一致")
        return self._record(governance, report)

    async def _load_by_task(
        self,
        task_id: str,
        *,
        for_update: bool,
    ) -> ReportTaskGovernanceRow | None:
        query = select(ReportTaskGovernanceRow).where(
            ReportTaskGovernanceRow.task_id == task_id
        )
        if for_update:
            query = query.with_for_update()
        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        # 测试替身和历史会话可能只识别 Report 查询，不能把它误当治理行。
        return row if isinstance(row, ReportTaskGovernanceRow) else None

    @classmethod
    def _merge_stages(
        cls,
        existing: tuple[ReportStageSnapshot, ...],
        incoming: tuple[ReportStageSnapshot, ...],
    ) -> tuple[ReportStageSnapshot, ...]:
        current = {item.stage: item.status for item in existing}
        for item in incoming:
            previous = current.get(item.stage)
            if previous in cls._TERMINAL_STAGE_STATUSES and previous is not item.status:
                continue
            current[item.stage] = item.status
        return tuple(
            ReportStageSnapshot(stage=stage, status=current[stage])
            for stage in ReportStage
            if stage in current
        )

    @staticmethod
    def _decode_stages(raw: object) -> tuple[ReportStageSnapshot, ...]:
        if not isinstance(raw, list):
            raise ReportTaskPersistenceError("报告治理阶段快照不是列表")
        try:
            return tuple(ReportStageSnapshot.model_validate(item) for item in raw)
        except (TypeError, ValueError) as exc:
            raise ReportTaskPersistenceError("报告治理阶段快照损坏") from exc

    @classmethod
    def _record(
        cls,
        governance: ReportTaskGovernanceRow,
        report: Report,
    ) -> ReportTaskSnapshotRecord:
        failed = report.status == ReportTaskStatus.FAILED.value
        return ReportTaskSnapshotRecord(
            user_id=governance.user_id,
            key_digest=governance.key_digest,
            request_fingerprint=governance.request_fingerprint,
            snapshot=ReportTaskSnapshot(
                task_id=governance.task_id,
                report_id=governance.report_id,
                snapshot_version=governance.snapshot_version,
                status=ReportTaskStatus(report.status),
                progress=max(0, min(100, int(report.progress or 0))),
                stages=cls._decode_stages(governance.stage_states),
                updated_at=governance.updated_at,
                error_code=REPORT_GENERATION_FAILED_CODE if failed else None,
                message=REPORT_GENERATION_FAILED_MESSAGE if failed else None,
            ),
        )
