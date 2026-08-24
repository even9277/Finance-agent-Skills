"""
SQLAlchemy 异步引擎与会话工厂
Phase 1: SQLite + aiosqlite
Phase 生产: 切换 DATABASE_URL 为 postgresql+asyncpg://...
"""

import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # SQLite 连接参数：允许多线程共用同一连接（asyncio 环境需要）
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url
    else {},
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """
    启动历史表并通过 Alembic 升级新记忆 Schema。

    历史表仍使用 create_all 和既有补列逻辑保持兼容；memory-v1 表明确排除
    在 create_all 之外，只能由版本化 Alembic revision 创建。
    """
    from backend.db import models
    from backend.db.migration_runner import upgrade_database

    async with engine.begin() as conn:
        legacy_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name not in models.ALEMBIC_MANAGED_TABLE_NAMES
        ]
        await conn.run_sync(Base.metadata.create_all, tables=legacy_tables)

    # ── Phase 2/3 增量字段迁移（对已存在的表追加缺失字段）─────
    await _migrate_add_columns()
    # Alembic 的异步模板内部运行事件循环，因此放入工作线程避免嵌套 asyncio.run。
    await asyncio.to_thread(upgrade_database, settings.database_url)


async def _migrate_add_columns() -> None:
    """
    为已存在的表追加缺失的 Phase 2/3 字段。

    先通过 Inspector 判断列是否存在，避免 PostgreSQL 在捕获重复列异常后仍将
    整笔 DDL 事务标记为失败。真实 DDL 错误不得吞掉，以免启动假成功。
    """
    from sqlalchemy import inspect, text

    is_sqlite = "sqlite" in settings.database_url
    is_postgres = "postgresql" in settings.database_url

    migrations = [
        # Phase 2 字段（若已存在则忽略）
        ("messages", "token_count", "INTEGER DEFAULT NULL"),
        ("messages", "is_compressed", "BOOLEAN DEFAULT 0"),
        ("sessions", "running_summary", "TEXT DEFAULT NULL"),
        ("sessions", "turn_count", "INTEGER DEFAULT 0"),
        ("sessions", "last_compress_at", "DATETIME DEFAULT NULL"),
        ("sessions", "context_token_count", "INTEGER DEFAULT 0"),
        ("sessions", "context_budget_tokens", "INTEGER DEFAULT 0"),
        ("sessions", "summary_token_count", "INTEGER DEFAULT 0"),
        ("sessions", "summary_version", "INTEGER DEFAULT 0"),
        ("sessions", "compression_status", "VARCHAR(20) DEFAULT 'idle'"),
        ("sessions", "context_updated_at", "DATETIME DEFAULT NULL"),
        ("sessions", "title", "VARCHAR(200) DEFAULT NULL"),
        ("sessions", "updated_at", "DATETIME DEFAULT NULL"),
        # Phase 3 字段
        ("messages", "used_for_ltm", "BOOLEAN DEFAULT 0"),
        # Phase 2.1：摘要快照增强字段（更直观展示：用户/助手条数 + 时间轴）
        ("session_summaries", "compressed_user_count", "INTEGER DEFAULT 0"),
        ("session_summaries", "compressed_assistant_count", "INTEGER DEFAULT 0"),
        ("session_summaries", "start_message_id", "INTEGER DEFAULT NULL"),
        ("session_summaries", "end_message_id", "INTEGER DEFAULT NULL"),
        # SQLite 对类型不敏感；PostgreSQL 会按 timestamp 存储
        ("session_summaries", "start_created_at", "TIMESTAMP DEFAULT NULL"),
        ("session_summaries", "end_created_at", "TIMESTAMP DEFAULT NULL"),
    ]

    async with engine.begin() as conn:
        existing_columns = await conn.run_sync(
            lambda sync_conn: {
                table: {
                    column["name"]
                    for column in inspect(sync_conn).get_columns(table)
                }
                for table in {table for table, _, _ in migrations}
            }
        )
        for table, column, col_def in migrations:
            if column in existing_columns[table]:
                continue
            dialect_col_def = col_def.replace("DATETIME", "TIMESTAMP") if is_postgres else col_def
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {dialect_col_def}")
            )

        # ── PostgreSQL 专属：字段类型/默认值对齐（幂等）──────────────
        if is_postgres:
            # 1) risk_level 扩容：支持 balanced_conservative 等值
            await conn.execute(
                text(
                    "ALTER TABLE user_invest_profiles "
                    "ALTER COLUMN risk_level TYPE VARCHAR(50)"
                )
            )

            # 2) response_pref / updated_by 可能历史数据为 NULL：补默认，避免后续 NOT NULL 约束爆炸
            #    （即便列允许 NULL，业务也依赖默认值）
            await conn.execute(
                text(
                    "UPDATE user_invest_profiles "
                    "SET response_pref = 'balanced' "
                    "WHERE response_pref IS NULL"
                )
            )
            await conn.execute(
                text(
                    "UPDATE user_invest_profiles "
                    "SET updated_by = 'system' "
                    "WHERE updated_by IS NULL"
                )
            )

            # 3) JSON 字段历史数据可能为 NULL：统一为 []
            await conn.execute(
                text(
                    "UPDATE user_invest_profiles "
                    "SET sectors = '[]'::jsonb "
                    "WHERE sectors IS NULL"
                )
            )
            await conn.execute(
                text(
                    "UPDATE user_invest_profiles "
                    "SET constraints = '[]'::jsonb "
                    "WHERE constraints IS NULL"
                )
            )

        # ── SQLite 专属：保持现有逻辑（无额外动作）───────────────────
        if is_sqlite:
            return


async def get_db():
    """FastAPI 依赖注入：为每个请求提供一个 AsyncSession，请求结束自动关闭。"""
    async with AsyncSessionFactory() as session:
        yield session
