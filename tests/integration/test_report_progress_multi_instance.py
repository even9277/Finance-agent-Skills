"""锁定两个报告运行时之间的版本通知与丢消息恢复合同。"""

from __future__ import annotations

import asyncio
import importlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

redis = pytest.importorskip("redis.asyncio")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _redis_url() -> str:
    """读取显式隔离的 Redis URL。"""
    if os.getenv("RUN_D06_ISOLATED_INFRA_TESTS", "").lower() != "true":
        pytest.skip("需要 RUN_D06_ISOLATED_INFRA_TESTS=true 的隔离 Compose")
    value = os.getenv("TEST_REDIS_URL", "").strip()
    if not value:
        pytest.fail("D06 multi-instance 测试缺少 TEST_REDIS_URL")
    return value


def _database_url() -> str:
    """只接受同一 D06 隔离拓扑中的 PostgreSQL URL。"""
    value = os.getenv("TEST_DATABASE_URL", "").strip()
    if not value.startswith("postgresql+asyncpg://e2e:"):
        pytest.fail("D06 multi-instance 测试缺少隔离 PostgreSQL")
    return value


@pytest.mark.integration
def test_two_runtime_instances_observe_new_version_and_recover_missed_notification() -> None:
    """D06-T06：B 能观察 A，离线期间丢失 Pub/Sub 后仍从 latest snapshot 恢复。"""

    async def scenario() -> None:
        redis_url = _redis_url()
        runtime_module = importlib.import_module("backend.infrastructure.report_tasks.runtime")
        contracts = importlib.import_module("backend.application.report_tasks.contracts")
        namespace = f"finance-d06-runtime-{uuid.uuid4().hex}"
        runtime_a = runtime_module.create_report_task_runtime(
            redis_url=redis_url,
            namespace=namespace,
            ttl_sec=20,
        )
        runtime_b = runtime_module.create_report_task_runtime(
            redis_url=redis_url,
            namespace=namespace,
            ttl_sec=20,
        )
        snapshot_v7 = contracts.ReportTaskSnapshot(
            task_id="task-d06-multi",
            report_id="report-d06-multi",
            snapshot_version=7,
            status="running",
            progress=65,
            stages=(),
            updated_at=datetime(2026, 9, 5, tzinfo=UTC),
            error_code=None,
            message=None,
        )
        try:
            async with runtime_b.subscribe(snapshot_v7.task_id) as subscription:
                await runtime_a.store_and_publish(
                    user_id="user-d06-multi",
                    key_digest="a" * 64,
                    request_fingerprint="b" * 64,
                    snapshot=snapshot_v7,
                )
                notification = await asyncio.wait_for(subscription.receive(), timeout=2)
            assert notification.snapshot_version == 7

            # B 断开期间的 v8 通知允许丢失；重连通过持久快照恢复，而非要求 replay。
            snapshot_v8 = contracts.ReportTaskSnapshot(
                task_id=snapshot_v7.task_id,
                report_id=snapshot_v7.report_id,
                snapshot_version=8,
                status="completed",
                progress=100,
                stages=(),
                updated_at=datetime(2026, 9, 5, 0, 1, tzinfo=UTC),
                error_code=None,
                message=None,
            )
            await runtime_a.store_and_publish(
                user_id="user-d06-multi",
                key_digest="a" * 64,
                request_fingerprint="b" * 64,
                snapshot=snapshot_v8,
            )
            recovered = await runtime_b.load_latest(
                user_id="user-d06-multi",
                key_digest="a" * 64,
                request_fingerprint="b" * 64,
            )
            assert recovered == snapshot_v8
        finally:
            await runtime_a.close()
            await runtime_b.close()

    asyncio.run(scenario())


@pytest.mark.integration
def test_two_instances_rebuild_flushed_redis_from_postgres_authority() -> None:
    """D06-T04/T06：Redis 清空后由 PostgreSQL 重建，跨实例仍只观察更高版本。"""

    async def scenario() -> None:
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
        from backend.db.models import User
        from backend.infrastructure.report_tasks.repository import (
            SqlAlchemyReportTaskClaimRepository,
            SqlAlchemyReportTaskSnapshotRepository,
        )
        from backend.infrastructure.report_tasks.runtime import create_report_task_runtime

        redis_url = _redis_url()
        engine = create_async_engine(_database_url(), poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        namespace = f"finance-d06-db-rebuild-{uuid.uuid4().hex}"
        runtime_a = create_report_task_runtime(
            redis_url=redis_url,
            namespace=namespace,
            ttl_sec=20,
        )
        runtime_b = create_report_task_runtime(
            redis_url=redis_url,
            namespace=namespace,
            ttl_sec=20,
        )
        admin = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
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
                    command="跨实例 Redis 重建 600519",
                    client_key=f"request-{uuid.uuid4().hex}",
                )

            update = ReportTaskSnapshotUpdate(
                task_id=created.task_id,
                report_id=created.report_id,
                status=ReportTaskStatus.RUNNING,
                progress=35,
                stages=(
                    ReportStageSnapshot(
                        stage=ReportStage.FUNDAMENTAL_ANALYSIS,
                        status=ReportStageStatus.SUCCEEDED,
                    ),
                ),
            )
            async with runtime_b.subscribe(created.task_id) as subscription:
                async with sessions() as session:
                    record = await SqlAlchemyReportTaskSnapshotRepository(
                        session
                    ).persist_snapshot(update)
                assert record is not None
                await runtime_a.store_and_publish(
                    user_id=record.user_id,
                    key_digest=record.key_digest,
                    request_fingerprint=record.request_fingerprint,
                    snapshot=record.snapshot,
                )
                observed = await asyncio.wait_for(subscription.receive(), timeout=2)
            assert observed.snapshot_version == record.snapshot.snapshot_version == 2

            # 只删除本测试唯一命名空间，模拟 flush/restart 丢失派生状态。
            keys = await admin.keys(f"{namespace}:*")
            if keys:
                await admin.delete(*keys)
            assert await runtime_b.load_latest(
                user_id=record.user_id,
                key_digest=record.key_digest,
                request_fingerprint=record.request_fingerprint,
            ) is None

            async with sessions() as session:
                authoritative = await SqlAlchemyReportTaskSnapshotRepository(
                    session
                ).load_latest(created.task_id)
            assert authoritative is not None
            await runtime_b.store_record(authoritative)
            rebuilt = await runtime_a.load_latest(
                user_id=authoritative.user_id,
                key_digest=authoritative.key_digest,
                request_fingerprint=authoritative.request_fingerprint,
            )
            assert rebuilt == authoritative.snapshot
            health = await runtime_b.health()
            metrics = health["metrics"]
            assert isinstance(metrics, dict)
            assert metrics["rebuilds"] == 1
        finally:
            keys = await admin.keys(f"{namespace}:*")
            if keys:
                await admin.delete(*keys)
            await admin.aclose()
            await runtime_a.close()
            await runtime_b.close()
            await engine.dispose()

    asyncio.run(scenario())
