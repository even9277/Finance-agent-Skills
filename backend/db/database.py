"""
SQLAlchemy 异步引擎与会话工厂
Phase 1: SQLite + aiosqlite
Phase 生产: 切换 DATABASE_URL 为 postgresql+asyncpg://...
"""

import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

logger = logging.getLogger("db.database")

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

    # 先清理已经下线的旧链路残留对象，再补齐当前仍需保留的字段。
    await _cleanup_legacy_objects()

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

    # PostgreSQL 无 DATETIME 类型；误用会导致 ADD COLUMN 失败且被静默忽略，ORM 列缺失
    datetime_null_def = (
        "TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL"
        if is_postgres
        else "DATETIME DEFAULT NULL"
    )

    json_null_def = "JSON DEFAULT NULL" if is_sqlite else "JSONB DEFAULT NULL"

    migrations = [
        # Phase 2 字段（若已存在则忽略）
        ("messages", "token_count", "INTEGER DEFAULT NULL"),
        ("messages", "is_compressed", "BOOLEAN DEFAULT 0"),
        ("sessions", "running_summary", "TEXT DEFAULT NULL"),
        ("sessions", "running_summary_state", json_null_def),
        ("sessions", "working_state", json_null_def),
        ("sessions", "working_state_version", "INTEGER DEFAULT 0"),
        ("sessions", "working_state_updated_at", datetime_null_def),
        ("sessions", "running_summary_mode", "VARCHAR(32) DEFAULT NULL"),
        ("sessions", "turn_count", "INTEGER DEFAULT 0"),
        ("sessions", "last_compress_at", datetime_null_def),
        ("sessions", "context_token_count", "INTEGER DEFAULT 0"),
        ("sessions", "context_budget_tokens", "INTEGER DEFAULT 0"),
        ("sessions", "summary_token_count", "INTEGER DEFAULT 0"),
        ("sessions", "summary_version", "INTEGER DEFAULT 0"),
        ("sessions", "compression_status", "VARCHAR(20) DEFAULT 'idle'"),
        ("sessions", "context_updated_at", datetime_null_def),
        ("sessions", "title", "VARCHAR(200) DEFAULT NULL"),
        ("sessions", "updated_at", datetime_null_def),
        ("session_summaries", "summary_payload", json_null_def),
        ("session_summaries", "summary_mode", "VARCHAR(32) DEFAULT NULL"),
        ("session_summaries", "summary_trigger", "VARCHAR(64) DEFAULT NULL"),
        ("session_summaries", "compressed_message_count", "INTEGER DEFAULT 0"),
        ("session_summaries", "total_message_count", "INTEGER DEFAULT 0"),
        # Phase 3 字段
        ("messages", "used_for_ltm", "BOOLEAN DEFAULT 0"),
        # FIX-8: user-facing route summary persisted on assistant messages
        ("messages", "route_summary_json", json_null_def),
        # P5 Plan-and-Execute artifacts, nullable for old rows and disabled rollout.
        ("messages", "plan_artifact_json", json_null_def),
        ("messages", "skill_artifact_json", json_null_def),
        ("messages", "verification_json", json_null_def),
        ("messages", "allowed_claim_level", "VARCHAR(20) DEFAULT NULL"),
    ]

    async def _column_exists(conn, table: str, column: str) -> bool:
        if is_postgres:
            result = await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                      AND column_name = :column_name
                    LIMIT 1
                    """
                ),
                {"table_name": table, "column_name": column},
            )
            return result.first() is not None

        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        rows = result.fetchall()
        return any(str(row[1]) == column for row in rows)

    # PostgreSQL：同一事务内任一条语句失败后事务即中止，不能再执行后续 SQL。
    # 每条 ADD COLUMN 用独立 transaction；失败时由 begin 回滚，避免 InFailedSQLTransactionError。
    for table, column, col_def in migrations:
        try:
            async with engine.begin() as conn:
                exists = False
                try:
                    exists = await _column_exists(conn, table, column)
                except Exception:
                    exists = False
                if exists:
                    logger.info("[db.init] column exists: %s.%s", table, column)
                    continue
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                )
                logger.info("[db.init] added column: %s.%s", table, column)
        except Exception:
            logger.exception("[db.init] failed to add column %s.%s", table, column)

    required_columns = [
        ("sessions", "running_summary_state"),
        ("sessions", "working_state"),
        ("sessions", "working_state_version"),
        ("sessions", "running_summary_mode"),
        ("session_summaries", "summary_payload"),
        ("session_summaries", "summary_mode"),
        ("session_summaries", "summary_trigger"),
        ("session_summaries", "compressed_message_count"),
        ("session_summaries", "total_message_count"),
    ]
    async with engine.begin() as conn:
        for table, column in required_columns:
            if not await _column_exists(conn, table, column):
                raise RuntimeError(f"missing required rolling-summary column: {table}.{column}")

    # ── PostgreSQL 专属：字段类型/默认值对齐（幂等，每条独立事务）────
    if is_postgres:
        async def _pg_risk_level_widen() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "ALTER TABLE user_invest_profiles "
                        "ALTER COLUMN risk_level TYPE VARCHAR(50)"
                    )
                )

        async def _pg_backfill_response_pref() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET response_pref = 'balanced' "
                        "WHERE response_pref IS NULL"
                    )
                )

        async def _pg_backfill_updated_by() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET updated_by = 'system' "
                        "WHERE updated_by IS NULL"
                    )
                )

        async def _pg_backfill_sectors() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET sectors = '[]'::jsonb "
                        "WHERE sectors IS NULL"
                    )
                )

        async def _pg_backfill_constraints() -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE user_invest_profiles "
                        "SET constraints = '[]'::jsonb "
                        "WHERE constraints IS NULL"
                    )
                )

        for _fn in (
            _pg_risk_level_widen,
            _pg_backfill_response_pref,
            _pg_backfill_updated_by,
            _pg_backfill_sectors,
            _pg_backfill_constraints,
        ):
            try:
                await _fn()
            except Exception:
                pass


async def _cleanup_legacy_objects() -> None:
    """
    清理已下线旧链路的残留表和字段。
    采用 best-effort 策略：每条 SQL 独立执行，失败时忽略，避免影响当前可用主链路启动。
    """
    from sqlalchemy import text

    is_postgres = "postgresql" in settings.database_url

    legacy_tables = [
        "stm_compaction_tasks",
        "memory_audit_logs",
        "memory_candidates",
    ]
    legacy_columns = [
        ("session_summaries", "compressed_user_count"),
        ("session_summaries", "compressed_assistant_count"),
        ("session_summaries", "start_message_id"),
        ("session_summaries", "end_message_id"),
        ("session_summaries", "start_created_at"),
        ("session_summaries", "end_created_at"),
        ("session_summaries", "state_snapshot"),
    ]

    async def _column_exists(conn, table: str, column: str) -> bool:
        if is_postgres:
            result = await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                      AND column_name = :column_name
                    LIMIT 1
                    """
                ),
                {"table_name": table, "column_name": column},
            )
            return result.first() is not None

        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        rows = result.fetchall()
        return any(str(row[1]) == column for row in rows)

    for table_name in legacy_tables:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        except Exception:
            pass

    for table_name, column_name in legacy_columns:
        try:
            async with engine.begin() as conn:
                if not await _column_exists(conn, table_name, column_name):
                    continue
                sql = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
                await conn.execute(text(sql))
        except Exception:
            pass


async def get_db():
    """FastAPI 依赖注入：为每个请求提供一个 AsyncSession，请求结束自动关闭。"""
    async with AsyncSessionFactory() as session:
        yield session
