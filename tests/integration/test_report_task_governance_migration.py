"""锁定 D06 独立治理表的 Alembic 与 ORM 所有权合同。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.database import Base
from backend.db.migration_runner import downgrade_database, upgrade_database
from backend.db import models


def _isolated_postgres_url() -> str:
    """只返回 D06 显式隔离的 PostgreSQL 验收 URL。"""
    if os.getenv("RUN_D06_ISOLATED_INFRA_TESTS", "").lower() != "true":
        pytest.skip("需要 RUN_D06_ISOLATED_INFRA_TESTS=true 的隔离 PostgreSQL")
    value = os.getenv("TEST_DATABASE_URL", "").strip()
    if not value.startswith("postgresql+asyncpg://e2e:"):
        pytest.fail("D06 迁移测试拒绝未识别的 PostgreSQL 目标")
    return value


async def _bootstrap_legacy_database(database_url: str) -> None:
    """只创建非 Alembic 管理表，模拟应用首次启动的安全前置状态。"""
    engine = create_async_engine(database_url)
    try:
        legacy_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name not in models.ALEMBIC_MANAGED_TABLE_NAMES
        ]
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=legacy_tables)
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_report_governance_table_is_alembic_managed_and_reversible(tmp_path: Path) -> None:
    """D06-T02：独立治理表可升级、降级、再升级且不混入 legacy create_all。"""
    row_type = getattr(models, "ReportTaskGovernanceRow", None)
    assert row_type is not None, "D06 ORM 尚未实现：ReportTaskGovernanceRow"
    assert row_type.__tablename__ == "report_task_governance"
    assert row_type.__tablename__ in models.ALEMBIC_MANAGED_TABLE_NAMES

    database_path = tmp_path / "report-governance-migration.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    asyncio.run(_bootstrap_legacy_database(async_url))

    upgrade_database(async_url)
    from sqlalchemy import create_engine

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assert "report_task_governance" in inspector.get_table_names()
        columns = {item["name"] for item in inspector.get_columns("report_task_governance")}
        assert columns == {
            "id",
            "user_id",
            "key_digest",
            "request_fingerprint",
            "task_id",
            "report_id",
            "generation",
            "expires_at",
            "snapshot_version",
            "stage_states",
            "created_at",
            "updated_at",
        }
        unique_constraints = {
            (item["name"], tuple(item["column_names"]))
            for item in inspector.get_unique_constraints("report_task_governance")
        }
        assert (
            "uq_report_task_governance_user_key",
            ("user_id", "key_digest"),
        ) in unique_constraints
        orm_uniques = {
            constraint.name
            for constraint in row_type.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert "uq_report_task_governance_user_key" in orm_uniques
    finally:
        engine.dispose()

    downgrade_database(async_url, allow_isolated=True)
    engine = create_engine(sync_url)
    try:
        assert "report_task_governance" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    upgrade_database(async_url)
    engine = create_engine(sync_url)
    try:
        assert "report_task_governance" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.integration
def test_report_governance_revision_up_down_reupgrade_on_isolated_postgres() -> None:
    """D06-T02：真实 PostgreSQL 可从 legacy 基线升级、定向降级并再升级。"""
    database_url = _isolated_postgres_url()
    asyncio.run(_bootstrap_legacy_database(database_url))

    async def table_names() -> set[str]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync_connection: set(inspect(sync_connection).get_table_names())
                )
        finally:
            await engine.dispose()

    upgrade_database(database_url)
    assert "report_task_governance" in asyncio.run(table_names())

    downgrade_database(database_url, "20260825_04", allow_isolated=True)
    assert "report_task_governance" not in asyncio.run(table_names())

    upgrade_database(database_url)
    assert "report_task_governance" in asyncio.run(table_names())
