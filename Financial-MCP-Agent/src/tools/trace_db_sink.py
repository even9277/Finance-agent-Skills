"""
Trace 数据库落库（可选，默认关闭）。

开关：ENABLE_TRACE_DB_SINK=true
失败仅记日志，不中断主链路（与 JSONL / Markdown 并行）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
_AGENT_SRC = _TOOLS_DIR.parent
if str(_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENT_SRC))

from src.utils.logging_config import setup_logger

logger = setup_logger("trace_db_sink")

_DB_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trace_db_sink")
_TABLES_LOCK = threading.Lock()
_TABLES_READY = False


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def is_trace_db_sink_enabled() -> bool:
    return _bool_env("ENABLE_TRACE_DB_SINK", False)


def _is_postgres_mode() -> bool:
    db_url = os.getenv("DATABASE_URL", "") or ""
    return db_url.startswith("postgresql")


def _get_sqlite_db_path() -> str:
    return os.getenv(
        "SQLITE_DB_PATH",
        str(_AGENT_SRC.parent.parent / "backend" / "finance.db"),
    )


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _session_id_from_record(record: dict[str, Any]) -> str | None:
    for key in ("session_id", "group_id"):
        val = record.get(key)
        if val:
            return str(val)
    return None


def _span_payload_json(record: dict[str, Any]) -> str:
    payload = {
        "name": record.get("name"),
        "stage": record.get("stage"),
        "data": record.get("data") or {},
        "metrics": record.get("metrics") or {},
        "refs": record.get("refs") or {},
        "record_type": record.get("record_type"),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS trace_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    started_at TEXT,
    updated_at TEXT,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS trace_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    session_id TEXT,
    span_id TEXT,
    parent_span_id TEXT,
    stage_name TEXT,
    status TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_ms REAL,
    data_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trace_spans_session_created
    ON trace_spans (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_id ON trace_spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_stage_created
    ON trace_spans (stage_name, created_at DESC);
"""


async def _ensure_tables_async() -> None:
    global _TABLES_READY
    with _TABLES_LOCK:
        if _TABLES_READY:
            return
        if _is_postgres_mode():
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            migration_path = _AGENT_SRC.parent.parent / "migrations" / "009_trace_observability.sql"
            sql = migration_path.read_text(encoding="utf-8")
            async with AsyncSessionFactory() as db:
                for statement in _split_sql_statements(sql):
                    if statement.strip():
                        await db.execute(text(statement))
                await db.commit()
        else:
            import aiosqlite

            async with aiosqlite.connect(_get_sqlite_db_path()) as db:
                await db.executescript(_SQLITE_DDL)
                await db.commit()
        _TABLES_READY = True
        logger.info("trace_db_sink.tables_ready")


def _split_sql_statements(sql: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return parts


async def _upsert_session(record: dict[str, Any]) -> None:
    session_id = _session_id_from_record(record)
    if not session_id:
        return
    user_id = record.get("user_id")
    now = datetime.utcnow()
    started_at = _parse_ts(record.get("started_at")) or _parse_ts(record.get("timestamp")) or now
    updated_at = _parse_ts(record.get("ended_at")) or _parse_ts(record.get("timestamp")) or now
    meta_json = json.dumps(record, ensure_ascii=False, default=str)

    if _is_postgres_mode():
        from sqlalchemy import text
        from backend.db.database import AsyncSessionFactory

        async with AsyncSessionFactory() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO trace_sessions (session_id, user_id, started_at, updated_at, meta_json)
                    VALUES (:session_id, :user_id, :started_at, :updated_at, CAST(:meta_json AS JSONB))
                    ON CONFLICT (session_id) DO UPDATE SET
                        user_id = COALESCE(EXCLUDED.user_id, trace_sessions.user_id),
                        updated_at = EXCLUDED.updated_at,
                        meta_json = EXCLUDED.meta_json
                    """
                ),
                {
                    "session_id": session_id,
                    "user_id": str(user_id) if user_id else None,
                    "started_at": started_at,
                    "updated_at": updated_at,
                    "meta_json": meta_json,
                },
            )
            await db.commit()
        return

    import aiosqlite

    async with aiosqlite.connect(_get_sqlite_db_path()) as db:
        await db.execute(
            """
            INSERT INTO trace_sessions (session_id, user_id, started_at, updated_at, meta_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id = COALESCE(excluded.user_id, trace_sessions.user_id),
                updated_at = excluded.updated_at,
                meta_json = excluded.meta_json
            """,
            (
                session_id,
                str(user_id) if user_id else None,
                started_at.isoformat(),
                updated_at.isoformat(),
                meta_json,
            ),
        )
        await db.commit()


async def _insert_span(record: dict[str, Any]) -> None:
    trace_id = str(record.get("trace_id") or "").strip()
    if not trace_id:
        return
    session_id = _session_id_from_record(record)
    span_id = record.get("span_id")
    parent_span_id = record.get("parent_span_id")
    stage_name = record.get("stage") or record.get("name")
    status = record.get("status")
    started_at = _parse_ts(record.get("started_at"))
    ended_at = _parse_ts(record.get("ended_at"))
    duration_ms = record.get("duration_ms")
    data_json = _span_payload_json(record)
    created_at = _parse_ts(record.get("timestamp")) or datetime.utcnow()

    if _is_postgres_mode():
        from sqlalchemy import text
        from backend.db.database import AsyncSessionFactory

        async with AsyncSessionFactory() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO trace_spans (
                        trace_id, session_id, span_id, parent_span_id, stage_name,
                        status, started_at, ended_at, duration_ms, data_json, created_at
                    ) VALUES (
                        :trace_id, :session_id, :span_id, :parent_span_id, :stage_name,
                        :status, :started_at, :ended_at, :duration_ms,
                        CAST(:data_json AS JSONB), :created_at
                    )
                    """
                ),
                {
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "span_id": str(span_id) if span_id else None,
                    "parent_span_id": str(parent_span_id) if parent_span_id else None,
                    "stage_name": stage_name,
                    "status": status,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_ms": float(duration_ms) if duration_ms is not None else None,
                    "data_json": data_json,
                    "created_at": created_at,
                },
            )
            await db.commit()
        return

    import aiosqlite

    async with aiosqlite.connect(_get_sqlite_db_path()) as db:
        await db.execute(
            """
            INSERT INTO trace_spans (
                trace_id, session_id, span_id, parent_span_id, stage_name,
                status, started_at, ended_at, duration_ms, data_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                session_id,
                str(span_id) if span_id else None,
                str(parent_span_id) if parent_span_id else None,
                stage_name,
                status,
                started_at.isoformat() if started_at else None,
                ended_at.isoformat() if ended_at else None,
                float(duration_ms) if duration_ms is not None else None,
                data_json,
                created_at.isoformat(),
            ),
        )
        await db.commit()


async def write_trace_record_async(record: dict[str, Any]) -> None:
    if not is_trace_db_sink_enabled():
        return
    await _ensure_tables_async()
    record_type = str(record.get("record_type") or "")
    if record_type == "trace":
        await _upsert_session(record)
    elif record_type == "span":
        await _insert_span(record)


def _write_sync(record: dict[str, Any]) -> None:
    try:
        asyncio.run(write_trace_record_async(record))
    except Exception as exc:
        logger.warning(
            "trace_db_sink.write_failed %s",
            {"error": str(exc), "record_type": record.get("record_type")},
        )


def enqueue_trace_record(record: dict[str, Any]) -> None:
    """非阻塞入队；观测失败不影响主流程。"""
    if not is_trace_db_sink_enabled():
        return
    try:
        _DB_EXECUTOR.submit(_write_sync, dict(record))
    except Exception as exc:
        logger.warning("trace_db_sink.enqueue_failed %s", {"error": str(exc)})
