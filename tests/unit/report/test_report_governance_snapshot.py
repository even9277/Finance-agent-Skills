"""验证报告治理快照的单调、终态锁定与同事务写入语义。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.application.report_progress.contracts import (
    ReportStage,
    ReportStageStatus,
    ReportTaskStatus,
)
from backend.application.report_tasks.contracts import (
    ReportStageSnapshot,
    ReportTaskSnapshotUpdate,
)
from backend.db.database import Base
from backend.db.models import Report, ReportTaskGovernanceRow, User
from backend.infrastructure.report_tasks.repository import (
    SqlAlchemyReportTaskSnapshotRepository,
)


@pytest.mark.unit
def test_snapshot_version_is_monotonic_and_terminal_is_locked(tmp_path: Path) -> None:
    """D06-T04：阶段、Report 和版本同事务推进，重复/回退不产生新版本。"""

    async def scenario() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'snapshot.db').as_posix()}"
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        task_id = "task-d06-snapshot"
        report_id = "report-d06-snapshot"
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                session.add(User(id="user-d06-snapshot"))
                session.add(
                    Report(
                        id=report_id,
                        task_id=task_id,
                        user_id="user-d06-snapshot",
                        status="pending",
                        progress=0,
                    )
                )
                session.add(
                    ReportTaskGovernanceRow(
                        id="governance-d06-snapshot",
                        user_id="user-d06-snapshot",
                        key_digest="a" * 64,
                        request_fingerprint="b" * 64,
                        task_id=task_id,
                        report_id=report_id,
                        generation=1,
                        expires_at=datetime.now(UTC) + timedelta(minutes=10),
                        snapshot_version=1,
                        stage_states=[],
                    )
                )
                await session.commit()

            preparing = ReportTaskSnapshotUpdate(
                task_id=task_id,
                report_id=report_id,
                status=ReportTaskStatus.RUNNING,
                progress=10,
                stages=(
                    ReportStageSnapshot(
                        stage=ReportStage.PREPARING,
                        status=ReportStageStatus.RUNNING,
                    ),
                ),
            )
            async with sessions() as session:
                repository = SqlAlchemyReportTaskSnapshotRepository(session)
                version_two = await repository.persist_snapshot(preparing)
                assert version_two is not None
                assert version_two.snapshot.snapshot_version == 2

            # 完全相同的消息不增加版本，较低进度也不能回退 Report。
            duplicate = preparing.model_copy(update={"progress": 5})
            async with sessions() as session:
                repository = SqlAlchemyReportTaskSnapshotRepository(session)
                unchanged = await repository.persist_snapshot(duplicate)
                assert unchanged is not None
                assert unchanged.snapshot.snapshot_version == 2
                assert unchanged.snapshot.progress == 10

            completed = preparing.model_copy(
                update={
                    "status": ReportTaskStatus.COMPLETED,
                    "progress": 100,
                    "stages": (
                        ReportStageSnapshot(
                            stage=ReportStage.PREPARING,
                            status=ReportStageStatus.SUCCEEDED,
                        ),
                    ),
                    "report_content": "# 已提交报告",
                }
            )
            async with sessions() as session:
                repository = SqlAlchemyReportTaskSnapshotRepository(session)
                terminal = await repository.persist_snapshot(completed)
                assert terminal is not None
                assert terminal.snapshot.snapshot_version == 3
                report = await session.get(Report, report_id)
                assert report is not None
                assert (report.status, report.progress, report.content) == (
                    "completed",
                    100,
                    "# 已提交报告",
                )

            # 终态后任何旧运行消息均只返回现状，不改写 Report、阶段或版本。
            async with sessions() as session:
                repository = SqlAlchemyReportTaskSnapshotRepository(session)
                locked = await repository.persist_snapshot(preparing)
                assert locked is not None
                assert locked.snapshot.snapshot_version == 3
                assert locked.snapshot.status is ReportTaskStatus.COMPLETED
                assert locked.snapshot.progress == 100
                assert locked.snapshot.stages[0].status.value == "SUCCEEDED"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.unit
def test_snapshot_update_rejects_content_on_nonterminal_state() -> None:
    """D06-T04：报告正文只能随 completed 终态事务写入。"""
    with pytest.raises(ValueError, match="report_content"):
        ReportTaskSnapshotUpdate(
            task_id="task-d06-invalid",
            report_id="report-d06-invalid",
            status=ReportTaskStatus.RUNNING,
            progress=20,
            report_content="不应写入",
        )
