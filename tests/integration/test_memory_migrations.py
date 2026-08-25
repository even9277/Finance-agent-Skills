"""验证 memory-v1 Alembic revision 的升降级与历史数据兼容性。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.db.database import Base  # noqa: E402
from backend.db.migration_runner import downgrade_database, upgrade_database  # noqa: E402
from backend.db.models import (  # noqa: E402
    ALEMBIC_MANAGED_TABLE_NAMES,
    Message,
    Session,
    User,
)


def _alembic_head_revision() -> str:
    """读取仓库当前 Alembic head，避免迁移测试硬编码历史版本。"""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    revisions = [
        token.strip()
        for line in result.stdout.splitlines()
        for token in line.split()
        if token.strip().startswith("20")
    ]
    if not revisions:
        raise AssertionError(f"unable to identify Alembic revision from output: {result.stdout}")
    return revisions[-1]


@pytest.mark.integration
def test_migration_downgrade_requires_explicit_isolated_confirmation() -> None:
    """确认默认调用不能误降级任何数据库。"""
    with pytest.raises(ValueError, match="isolated-database confirmation"):
        downgrade_database("sqlite+aiosqlite:///must-not-be-created.db")


@pytest.mark.integration
def test_direct_alembic_downgrade_fails_closed_without_isolated_flag(
    tmp_path: Path,
) -> None:
    """确认直接 CLI 也不能绕过 revision 内部的隔离降级授权。"""
    database_path = tmp_path / "direct-downgrade-must-not-start.db"
    command_env = os.environ.copy()
    command_env["MIGRATION_DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    command_env.pop("ALLOW_ISOLATED_MEMORY_DOWNGRADE", None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=PROJECT_ROOT,
        env=command_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "explicit isolated-database confirmation" in (result.stdout + result.stderr)


@pytest.mark.contract
def test_backend_runtime_requirements_include_alembic() -> None:
    """确认常规后端镜像会安装启动迁移所需的 Alembic。"""
    requirements = (PROJECT_ROOT / "backend" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "alembic>=1.14,<2" in requirements.splitlines()


async def _bootstrap_legacy_database(database_url: str) -> None:
    """创建 M2 以前的表并写入一条需要跨迁移保留的会话。"""
    engine = create_async_engine(database_url)
    try:
        legacy_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name not in ALEMBIC_MANAGED_TABLE_NAMES
        ]
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=legacy_tables)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            db.add(User(id="fixture-user-migration", display_name="迁移测试用户"))
            db.add(
                Session(
                    id="fixture-session-migration",
                    user_id="fixture-user-migration",
                    mode="chat",
                    title="旧会话",
                )
            )
            db.add(
                Message(
                    session_id="fixture-session-migration",
                    role="user",
                    content="迁移前的虚拟消息",
                )
            )
            await db.commit()
    finally:
        await engine.dispose()


def _assert_legacy_rows_readable(sync_url: str) -> None:
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            session_title = connection.scalar(
                text(
                    "SELECT title FROM sessions "
                    "WHERE id = 'fixture-session-migration'"
                )
            )
            message_content = connection.scalar(
                text(
                    "SELECT content FROM messages "
                    "WHERE session_id = 'fixture-session-migration'"
                )
            )
        assert session_title == "旧会话"
        assert message_content == "迁移前的虚拟消息"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_memory_revision_upgrade_downgrade_reupgrade_preserves_legacy_rows(
    tmp_path: Path,
) -> None:
    """确认迁移可升、可降、可再升，且不删除历史会话和消息。"""
    database_path = tmp_path / "memory-migration.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    asyncio.run(_bootstrap_legacy_database(async_url))

    upgrade_database(async_url)
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        for table_name in ALEMBIC_MANAGED_TABLE_NAMES:
            migrated_columns = {column["name"] for column in inspector.get_columns(table_name)}
            orm_columns = set(Base.metadata.tables[table_name].columns.keys())
            assert migrated_columns == orm_columns
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()
    assert ALEMBIC_MANAGED_TABLE_NAMES.issubset(table_names)
    assert revision == _alembic_head_revision()
    _assert_legacy_rows_readable(sync_url)

    downgrade_database(async_url, allow_isolated=True)
    engine = create_engine(sync_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert ALEMBIC_MANAGED_TABLE_NAMES.isdisjoint(table_names)
    _assert_legacy_rows_readable(sync_url)

    upgrade_database(async_url)
    engine = create_engine(sync_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert ALEMBIC_MANAGED_TABLE_NAMES.issubset(table_names)
    _assert_legacy_rows_readable(sync_url)
