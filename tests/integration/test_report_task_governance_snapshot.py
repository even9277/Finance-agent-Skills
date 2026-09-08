"""在真实 PostgreSQL 上验证报告快照与 Report 的原子提交。"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.application.report_progress.contracts import (
    ReportStage,
    ReportStageStatus,
    ReportTaskStatus,
)
from backend.application.report_tasks.contracts import (
    ReportStageSnapshot,
    ReportTaskSnapshotUpdate,
)
from backend.application.report_tasks.service import ReportTaskCreationService
from backend.db.database import Base
from backend.db.models import Report, User
from backend.infrastructure.report_tasks.repository import (
    SqlAlchemyReportTaskClaimRepository,
    SqlAlchemyReportTaskSnapshotRepository,
)


def _isolated_postgres_url() -> str:
    """只接受 D06 显式隔离、专用账号的 PostgreSQL。"""
    if os.getenv("RUN_D06_ISOLATED_INFRA_TESTS", "").lower() != "true":
        pytest.skip("需要 RUN_D06_ISOLATED_INFRA_TESTS=true 的隔离 PostgreSQL")
    value = os.getenv("TEST_DATABASE_URL", "").strip()
    if not value.startswith("postgresql+asyncpg://e2e:"):
        pytest.fail("D06 快照测试拒绝未识别的 PostgreSQL 目标")
    return value


@pytest.mark.integration
def test_postgres_report_and_snapshot_terminal_commit_are_atomic() -> None:
    """D06-T04：真实 PostgreSQL 同时提交报告正文、终态、阶段和版本。"""

    async def scenario() -> None:
        engine = create_async_engine(_isolated_postgres_url(), poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        user_id = str(uuid.uuid4())
        try:
            async with engine.begin() as connection:
                await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                session.add(User(id=user_id))
                await session.commit()
                created = await ReportTaskCreationService(
                    SqlAlchemyReportTaskClaimRepository(session),
                    digest_secret="fixture-secret-at-least-thirty-two-bytes",
                    ttl_seconds=600,
                ).create_or_reuse(
                    user_id=user_id,
                    command="隔离数据库快照测试 600519",
                    client_key=f"request-{uuid.uuid4().hex}",
                )

            running = ReportTaskSnapshotUpdate(
                task_id=created.task_id,
                report_id=created.report_id,
                status=ReportTaskStatus.RUNNING,
                progress=20,
                stages=(
                    ReportStageSnapshot(
                        stage=ReportStage.PREPARING,
                        status=ReportStageStatus.SUCCEEDED,
                    ),
                ),
            )
            async with sessions() as session:
                repository = SqlAlchemyReportTaskSnapshotRepository(session)
                snapshot = await repository.persist_snapshot(running)
                assert snapshot is not None
                assert snapshot.snapshot.snapshot_version == 2

            completed = running.model_copy(
                update={
                    "status": ReportTaskStatus.COMPLETED,
                    "progress": 100,
                    "report_content": "# PostgreSQL 原子终态",
                }
            )
            async with sessions() as session:
                repository = SqlAlchemyReportTaskSnapshotRepository(session)
                snapshot = await repository.persist_snapshot(completed)
                assert snapshot is not None
                assert snapshot.snapshot.snapshot_version == 3
                assert snapshot.snapshot.status is ReportTaskStatus.COMPLETED
                report = await session.get(Report, created.report_id)
                assert report is not None
                assert (report.status, report.progress, report.content) == (
                    "completed",
                    100,
                    "# PostgreSQL 原子终态",
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())
