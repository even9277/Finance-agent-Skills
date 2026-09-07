"""验证报告任务治理仓储的过期换代与运行中保护。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.application.report_tasks.service import ReportTaskCreationService
from backend.db.database import Base
from backend.db.models import Report, ReportTaskGovernanceRow, User
from backend.infrastructure.report_tasks.repository import SqlAlchemyReportTaskClaimRepository


@pytest.mark.integration
def test_expired_terminal_rotates_one_stable_row_but_expired_running_replays(
    tmp_path: Path,
) -> None:
    """D06-T02：终态过期原子换代，运行态即使过期也不得创建第二任务。"""

    async def scenario() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'rotation.db').as_posix()}"
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                session.add(User(id="user-d06-rotation"))
                await session.commit()

            key = "request-d06-rotation-0001"
            async with sessions() as session:
                service = ReportTaskCreationService(
                    SqlAlchemyReportTaskClaimRepository(session),
                    digest_secret="fixture-secret-at-least-thirty-two-bytes",
                    ttl_seconds=600,
                )
                first = await service.create_or_reuse(
                    user_id="user-d06-rotation",
                    command="分析贵州茅台 600519",
                    client_key=key,
                )

            async with sessions() as session:
                governance = (
                    await session.execute(select(ReportTaskGovernanceRow))
                ).scalar_one()
                report = await session.get(Report, first.report_id)
                assert report is not None
                report.status = "running"
                governance.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()

            async with sessions() as session:
                service = ReportTaskCreationService(
                    SqlAlchemyReportTaskClaimRepository(session),
                    digest_secret="fixture-secret-at-least-thirty-two-bytes",
                    ttl_seconds=600,
                )
                running_replay = await service.create_or_reuse(
                    user_id="user-d06-rotation",
                    command="分析贵州茅台 600519",
                    client_key=key,
                )
                assert running_replay.task_id == first.task_id
                assert running_replay.idempotency_status.value == "REPLAYED"

            async with sessions() as session:
                governance = (
                    await session.execute(select(ReportTaskGovernanceRow))
                ).scalar_one()
                report = await session.get(Report, first.report_id)
                assert report is not None
                report.status = "completed"
                governance.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()

            async with sessions() as session:
                service = ReportTaskCreationService(
                    SqlAlchemyReportTaskClaimRepository(session),
                    digest_secret="fixture-secret-at-least-thirty-two-bytes",
                    ttl_seconds=600,
                )
                rotated = await service.create_or_reuse(
                    user_id="user-d06-rotation",
                    command="分析贵州茅台 600519",
                    client_key=key,
                )
                assert rotated.idempotency_status.value == "CREATED"
                assert rotated.generation == 2
                assert rotated.task_id != first.task_id

            async with sessions() as session:
                governance_count = await session.scalar(
                    select(func.count()).select_from(ReportTaskGovernanceRow)
                )
                report_count = await session.scalar(select(func.count()).select_from(Report))
                assert governance_count == 1
                assert report_count == 2
        finally:
            await engine.dispose()

    asyncio.run(scenario())
