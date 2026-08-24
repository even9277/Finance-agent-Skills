"""从前端容器入口验证离线 Compose 的前后端代理链路。"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pytest
from sqlalchemy import UniqueConstraint, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.memory.contracts import (  # noqa: E402
    MEMORY_SCHEMA_VERSION,
    MemoryErrorCode,
    NewOutboxTask,
    OutboxTaskKind,
    OutboxTaskStatus,
    TurnCommittedPayload,
    build_turn_outbox_key,
)
from backend.db.database import Base  # noqa: E402
from backend.db.migration_runner import (  # noqa: E402
    downgrade_database,
    upgrade_database,
)
from backend.db.models import ALEMBIC_MANAGED_TABLE_NAMES  # noqa: E402
from backend.infrastructure.memory.repository import (  # noqa: E402
    MemoryRepositoryError,
    SqlAlchemyMemoryRepository,
)


def _send_chat_request(
    base_url: str,
    *,
    user_id: str,
    message: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """通过前端代理发送一条真实 HTTP 对话请求。"""
    payload: dict[str, object] = {"user_id": user_id, "message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    request = Request(
        f"{base_url}/api/chat/message",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


async def _load_memory_transaction_evidence(
    session_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """从隔离 PostgreSQL 读取本轮 Working State 与 Outbox 证据。

    Args:
        session_id: HTTP 对话接口返回的权威会话标识。

    Returns:
        Working State 行和事务 Outbox 行的必要安全字段。
    """
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            state_result = await connection.execute(
                text(
                    """
                    SELECT session_id, schema_version, state_version, source_message_id
                    FROM memory_working_states
                    WHERE session_id = :session_id
                    """
                ),
                {"session_id": session_id},
            )
            outbox_result = await connection.execute(
                text(
                    """
                    SELECT task_kind, status, schema_version, payload_json
                    FROM memory_outbox_tasks
                    WHERE session_id = :session_id
                      AND task_kind = 'TURN_COMMITTED'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ),
                {"session_id": session_id},
            )
            state = state_result.mappings().one()
            outbox = outbox_result.mappings().one()
            return dict(state), dict(outbox)
    finally:
        await engine.dispose()


async def _assert_outbox_owner_is_authoritative(
    *,
    session_id: str,
    user_message_id: int,
    assistant_message_id: int,
) -> None:
    """确认 Repository 拒绝其他真实用户引用当前会话和消息。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            intent = NewOutboxTask(
                user_id="offline-user-other",
                session_id=session_id,
                aggregate_type="chat_turn",
                aggregate_id=session_id,
                task_kind=OutboxTaskKind.TURN_COMMITTED,
                idempotency_key=build_turn_outbox_key(session_id, user_message_id),
                payload=TurnCommittedPayload(
                    session_id=session_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    state_version=0,
                ),
            )
            with pytest.raises(MemoryRepositoryError) as error:
                await SqlAlchemyMemoryRepository(db).enqueue_outbox(intent)
            await db.rollback()
        assert error.value.code is MemoryErrorCode.OWNERSHIP_MISMATCH
    finally:
        await engine.dispose()


def _assert_schema_matches_orm(sync_connection) -> None:
    """核对 PostgreSQL 的列、类型、可空性、外键、唯一约束和索引。"""
    inspector = inspect(sync_connection)
    assert ALEMBIC_MANAGED_TABLE_NAMES.issubset(inspector.get_table_names())
    for table_name in ALEMBIC_MANAGED_TABLE_NAMES:
        orm_table = Base.metadata.tables[table_name]
        actual_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        assert set(actual_columns) == set(orm_table.columns.keys())
        for column in orm_table.columns:
            actual = actual_columns[column.name]
            assert actual["nullable"] is column.nullable
            assert actual["type"]._type_affinity is column.type._type_affinity

        actual_foreign_keys = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys(table_name)
        }
        expected_foreign_keys = {
            (
                tuple(element.parent.name for element in constraint.elements),
                next(iter(constraint.elements)).column.table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in orm_table.foreign_key_constraints
        }
        assert actual_foreign_keys == expected_foreign_keys

        actual_unique = {
            (item["name"], tuple(item["column_names"]))
            for item in inspector.get_unique_constraints(table_name)
        }
        expected_unique = {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in orm_table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert actual_unique == expected_unique

        actual_indexes = {
            (item["name"], tuple(item["column_names"]))
            for item in inspector.get_indexes(table_name)
            if not item.get("duplicates_constraint")
        }
        expected_indexes = {
            (item.name, tuple(column.name for column in item.columns))
            for item in orm_table.indexes
        }
        assert actual_indexes == expected_indexes

    required_server_defaults = {
        "memory_working_states": {
            "state_version",
            "candidate_entities",
            "constraints",
            "reply_preference_hint",
            "created_at",
            "updated_at",
        },
        "memory_outbox_tasks": {
            "attempt_count",
            "available_at",
            "created_at",
            "updated_at",
        },
    }
    for table_name, column_names in required_server_defaults.items():
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        assert all(columns[name]["default"] is not None for name in column_names)


async def _assert_postgres_schema_contract() -> None:
    """在真实 PostgreSQL 连接上核对 M2 核心 Schema 结构。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_assert_schema_matches_orm)
    finally:
        await engine.dispose()


async def _delete_working_state_for_concurrency(session_id: str) -> None:
    """仅在隔离测试库移除初始状态，用于复现首次初始化并发。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM memory_working_states WHERE session_id = :session_id"
                ),
                {"session_id": session_id},
            )
    finally:
        await engine.dispose()


async def _load_concurrency_evidence(session_id: str) -> dict[str, int]:
    """读取同会话并发后的消息、状态、任务和轮次计数。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM messages WHERE session_id = :session_id)
                            AS message_count,
                          (SELECT count(*) FROM memory_working_states
                           WHERE session_id = :session_id) AS state_count,
                          (SELECT count(*) FROM memory_outbox_tasks
                           WHERE session_id = :session_id
                             AND task_kind = 'TURN_COMMITTED') AS turn_outbox_count,
                          (SELECT count(*) FROM memory_outbox_tasks
                           WHERE session_id = :session_id
                             AND task_kind = 'SUMMARY_COMPACT') AS summary_outbox_count,
                          (SELECT turn_count FROM sessions WHERE id = :session_id)
                            AS turn_count
                        """
                    ),
                    {"session_id": session_id},
                )
            ).mappings().one()
            return {key: int(value) for key, value in row.items()}
    finally:
        await engine.dispose()


async def _wait_for_summary_evidence(session_id: str) -> dict[str, object]:
    """等待后台摘要任务终态并返回安全边界证据。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        for _ in range(50):
            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            """
                            SELECT s.summary_version,
                                   s.running_summary,
                                   t.status AS task_status,
                                   m.source_start_message_id,
                                   m.source_end_message_id,
                                   m.source_message_count,
                                   CAST(
                                     t.payload_json ->> 'protected_tail_start_message_id'
                                     AS INTEGER
                                   ) AS protected_tail_start_message_id,
                                   (SELECT count(*) FROM messages
                                    WHERE session_id = :session_id
                                      AND is_compressed = true) AS compressed_count,
                                   (SELECT count(*) FROM messages
                                    WHERE session_id = :session_id
                                      AND is_compressed = false) AS raw_count
                            FROM sessions s
                            JOIN memory_outbox_tasks t
                              ON t.session_id = s.id
                             AND t.task_kind = 'SUMMARY_COMPACT'
                             AND t.status = 'SUCCEEDED'
                             AND CAST(
                               t.payload_json ->> 'expected_summary_version' AS INTEGER
                             ) + 1 = s.summary_version
                            LEFT JOIN memory_summary_metadata m
                              ON m.session_id = s.id
                             AND m.summary_version = s.summary_version
                            WHERE s.id = :session_id
                            """
                        ),
                        {"session_id": session_id},
                    )
                ).mappings().one_or_none()
            if row is not None and row["task_status"] == OutboxTaskStatus.SUCCEEDED.value:
                return dict(row)
            await asyncio.sleep(0.2)
        raise AssertionError("summary worker did not reach SUCCEEDED within 10 seconds")
    finally:
        await engine.dispose()


async def _assert_legacy_rows_after_downgrade(session_id: str) -> None:
    """确认降级只移除 M2 表，历史会话和消息仍可读取。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            message_count = await connection.scalar(
                text("SELECT count(*) FROM messages WHERE session_id = :session_id"),
                {"session_id": session_id},
            )
        assert ALEMBIC_MANAGED_TABLE_NAMES.isdisjoint(table_names)
        assert message_count == 6
    finally:
        await engine.dispose()


@pytest.mark.e2e
def test_frontend_proxy_reaches_backend_and_fake_chat_chain() -> None:
    """验证 Vue/Nginx/FastAPI/真实工作流/Fake Ports/PostgreSQL 完整链。"""
    base_url = os.getenv("OFFLINE_STACK_BASE_URL", "").rstrip("/")
    if not base_url:
        pytest.skip("OFFLINE_STACK_BASE_URL 未设置；仅在 Compose 完整链路中执行")

    with urlopen(f"{base_url}/", timeout=10) as response:  # noqa: S310
        frontend_html = response.read().decode("utf-8")
    assert response.status == 200
    assert '<div id="app"></div>' in frontend_html

    with urlopen(f"{base_url}/api/health", timeout=10) as response:  # noqa: S310
        health = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert health["status"] == "ok"
    assert health["version"]
    assert health["components"]["memory_cache"]["enabled"] is True
    assert health["components"]["memory_cache"]["status"] == "UP"

    init_request = Request(
        f"{base_url}/api/user/init",
        data=json.dumps(
            {"user_id": "offline-user", "display_name": "离线验收用户"}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(init_request, timeout=10) as response:  # noqa: S310
        initialized = json.loads(response.read().decode("utf-8"))
    assert initialized["user_id"] == "offline-user"

    chat = _send_chat_request(
        base_url,
        user_id="offline-user",
        message="查询贵州茅台 600519.SH 的基础信息和近期行情",
    )

    assert chat["session_id"]
    assert "600519.SH" in chat["reply"]
    assert "fixture:" in chat["reply"]
    assert chat["memory_profile"] is None
    assert chat["context_window"]["used_tokens"] > 0

    with urlopen(  # noqa: S310
        f"{base_url}/api/chat/sessions/{chat['session_id']}/messages?user_id=offline-user",
        timeout=10,
    ) as response:
        history = json.loads(response.read().decode("utf-8"))
    assert [item["role"] for item in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["content"] == chat["reply"]

    # HTTP 返回成功后，消息、Working State 与安全 Outbox 引用必须同时可见。
    state, outbox = asyncio.run(_load_memory_transaction_evidence(chat["session_id"]))
    assert state["session_id"] == chat["session_id"]
    assert state["schema_version"] == MEMORY_SCHEMA_VERSION
    assert state["state_version"] == 1
    assert state["source_message_id"] == history["messages"][0]["id"]
    assert outbox["task_kind"] == OutboxTaskKind.TURN_COMMITTED.value
    assert outbox["status"] == OutboxTaskStatus.PENDING.value
    assert outbox["schema_version"] == MEMORY_SCHEMA_VERSION
    assert outbox["payload_json"] == {
        "session_id": chat["session_id"],
        "user_message_id": history["messages"][0]["id"],
        "assistant_message_id": history["messages"][1]["id"],
        "state_version": 1,
    }

    other_user_request = Request(
        f"{base_url}/api/user/init",
        data=json.dumps(
            {"user_id": "offline-user-other", "display_name": "跨用户负例"}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(other_user_request, timeout=10) as response:  # noqa: S310
        assert response.status == 200
    asyncio.run(
        _assert_outbox_owner_is_authoritative(
            session_id=str(chat["session_id"]),
            user_message_id=int(history["messages"][0]["id"]),
            assistant_message_id=int(history["messages"][1]["id"]),
        )
    )

    trace_path = Path(os.environ["OFFLINE_TRACE_PATH"])
    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    roots = [item for item in records if item["record_type"] == "trace"]
    spans = [item for item in records if item["record_type"] == "span"]
    assert [item["status"] for item in roots] == ["started", "ok"]
    assert spans[0]["stage"] == "context"
    assert spans[-1]["stage"] == "termination"
    assert len({item["trace_id"] for item in records}) == 1
    assert len({item["run_id"] for item in records}) == 1
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "查询贵州茅台" not in trace_text
    assert "OPENAI_COMPATIBLE_API_KEY" not in trace_text
    assert "TUSHARE_TOKEN" not in trace_text

    # 删除测试状态后并发进入同一已存在会话，复现首次初始化竞争窗口。
    asyncio.run(_delete_working_state_for_concurrency(str(chat["session_id"])))

    async def send_concurrent_turns() -> tuple[dict[str, Any], dict[str, Any]]:
        first, second = await asyncio.gather(
            asyncio.to_thread(
                _send_chat_request,
                base_url,
                user_id="offline-user",
                session_id=str(chat["session_id"]),
                message="继续分析 600519.SH 的盈利质量",
            ),
            asyncio.to_thread(
                _send_chat_request,
                base_url,
                user_id="offline-user",
                session_id=str(chat["session_id"]),
                message="再看 600519.SH 的估值风险",
            ),
        )
        return first, second

    concurrent_results = asyncio.run(send_concurrent_turns())
    assert all(item["session_id"] == chat["session_id"] for item in concurrent_results)
    concurrency_evidence = asyncio.run(
        _load_concurrency_evidence(str(chat["session_id"]))
    )
    assert concurrency_evidence["message_count"] == 6
    assert concurrency_evidence["state_count"] == 1
    assert concurrency_evidence["turn_outbox_count"] == 3
    assert concurrency_evidence["summary_outbox_count"] >= 1
    assert concurrency_evidence["turn_count"] == 3
    summary_evidence = asyncio.run(_wait_for_summary_evidence(str(chat["session_id"])))
    assert summary_evidence["summary_version"] == 1
    assert summary_evidence["running_summary"]
    source_message_count = summary_evidence["source_message_count"]
    assert isinstance(source_message_count, int)
    assert source_message_count >= 2
    source_end_message_id = summary_evidence["source_end_message_id"]
    protected_tail_start_message_id = summary_evidence[
        "protected_tail_start_message_id"
    ]
    assert isinstance(source_end_message_id, int)
    assert isinstance(protected_tail_start_message_id, int)
    assert source_end_message_id < protected_tail_start_message_id
    compressed_count = summary_evidence["compressed_count"]
    raw_count = summary_evidence["raw_count"]
    assert isinstance(compressed_count, int)
    assert isinstance(raw_count, int)
    assert compressed_count == source_message_count
    assert raw_count >= 2
    assert compressed_count + raw_count == 6

    # 用独立会话验证第二轮复用缓存，避免改变上述摘要边界的确定性样例。
    cache_seed = _send_chat_request(
        base_url,
        user_id="offline-user",
        message="缓存验收会话：查询 000001.SZ",
    )
    follow_up = _send_chat_request(
        base_url,
        user_id="offline-user",
        session_id=cache_seed["session_id"],
        message="继续说明它的风险点",
    )
    assert follow_up["session_id"] == cache_seed["session_id"]
    with urlopen(f"{base_url}/api/health", timeout=10) as response:  # noqa: S310
        cache_health = json.loads(response.read().decode("utf-8"))["components"][
            "memory_cache"
        ]
    assert cache_health["status"] == "UP"
    assert cache_health["metrics"]["hits"] >= 1

    # 在同一个 tmpfs PostgreSQL 上验证核心约束，并做 downgrade/re-upgrade。
    asyncio.run(_assert_postgres_schema_contract())
    database_url = os.environ["TEST_DATABASE_URL"]
    downgrade_database(database_url, allow_isolated=True)
    asyncio.run(_assert_legacy_rows_after_downgrade(str(chat["session_id"])))
    upgrade_database(database_url)
    asyncio.run(_assert_postgres_schema_contract())
