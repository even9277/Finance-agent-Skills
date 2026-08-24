"""配置 Alembic 在异步 SQLAlchemy URL 上执行版本化迁移。"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.db import models  # noqa: F401
from backend.db.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _is_direct_downgrade_command() -> bool:
    """识别 Alembic CLI 传入的 downgrade 命令，不影响程序化受控入口。"""
    command_options = getattr(config, "cmd_opts", None)
    command_spec = getattr(command_options, "cmd", None)
    if not isinstance(command_spec, tuple) or not command_spec:
        return False
    return getattr(command_spec[0], "__name__", "") == "downgrade"


if _is_direct_downgrade_command():
    isolated_confirmation = os.getenv(
        "ALLOW_ISOLATED_MEMORY_DOWNGRADE",
        "",
    ).strip().lower()
    if isolated_confirmation not in {"1", "true"}:
        raise RuntimeError(
            "memory downgrade requires explicit isolated-database confirmation"
        )

if not (config.get_main_option("sqlalchemy.url") or "").strip():
    migration_url = os.getenv("MIGRATION_DATABASE_URL", "").strip()
    if not migration_url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is required for direct Alembic commands"
        )
    # ConfigParser 会解释百分号；双写只影响配置传递。
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在不创建 Engine 的情况下生成或执行离线 SQL。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """创建短生命周期异步 Engine 并在单连接上执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
