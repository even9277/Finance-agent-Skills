"""
SQLAlchemy 异步引擎与会话工厂
Phase 1: SQLite + aiosqlite
Phase 生产: 切换 DATABASE_URL 为 postgresql+asyncpg://...
"""

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
    应用启动时创建所有表（Phase 1/2/3 直接建表，生产环境换 Alembic）。
    对于已存在的表，通过 try-catch 方式追加 Phase 2/3 新增字段（增量迁移）。
    """
    from backend.db import models  # noqa: F401

    async with engine.begin() as conn:
        # 创建所有新表（已存在的表不会被覆盖）
        await conn.run_sync(Base.metadata.create_all)

    # ── Phase 2/3 增量字段迁移（对已存在的表追加缺失字段）─────
    await _migrate_add_columns()


async def _migrate_add_columns() -> None:
    """
    为已存在的表追加缺失的 Phase 2/3 字段。
    SQLite 支持 ALTER TABLE ADD COLUMN（不支持 NOT NULL 无默认值的列）。
    对于已有字段，忽略异常（OperationalError: duplicate column name）。
    """
    from sqlalchemy import text

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
        for table, column, col_def in migrations:
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                )
            except Exception:
                # 字段已存在时会抛出 OperationalError，直接忽略
                pass

        # ── PostgreSQL 专属：字段类型/默认值对齐（幂等）──────────────
        if is_postgres:
            # 1) risk_level 扩容：支持 balanced_conservative 等值
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE user_invest_profiles "
                        "ALTER COLUMN risk_level TYPE VARCHAR(50)"
                    )
                )
            except Exception:
                pass

            # 2) response_pref / updated_by 可能历史数据为 NULL：补默认，避免后续 NOT NULL 约束爆炸
            #    （即便列允许 NULL，业务也依赖默认值）
            try:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET response_pref = 'balanced' "
                        "WHERE response_pref IS NULL"
                    )
                )
            except Exception:
                pass
            try:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET updated_by = 'system' "
                        "WHERE updated_by IS NULL"
                    )
                )
            except Exception:
                pass

            # 3) JSON 字段历史数据可能为 NULL：统一为 []
            try:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET sectors = '[]'::jsonb "
                        "WHERE sectors IS NULL"
                    )
                )
            except Exception:
                pass
            try:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET constraints = '[]'::jsonb "
                        "WHERE constraints IS NULL"
                    )
                )
            except Exception:
                pass

        # ── SQLite 专属：保持现有逻辑（无额外动作）───────────────────
        if is_sqlite:
            return


async def get_db():
    """FastAPI 依赖注入：为每个请求提供一个 AsyncSession，请求结束自动关闭。"""
    async with AsyncSessionFactory() as session:
        yield session
