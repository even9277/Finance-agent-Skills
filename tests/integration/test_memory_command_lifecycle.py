"""验证 M7 pending confirmation 的所有权、版本和一次性消费语义。"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for _path in (PROJECT_ROOT, AGENT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.application.memory.commands import (
    MemoryCommandStatus,
    MemoryCommandUseCase,
    parse_memory_command,
)
from backend.db.database import Base
from backend.db.models import MemoryPendingCommandRow, MemoryRecordRow, Session, User
from src.memory.contracts import MEMORY_POLICY_VERSION


async def _factory(tmp_path: Path):
    """创建启用外键的 SQLite 隔离库，覆盖 Alembic 管理模型的 ORM 合同。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'm7.sqlite').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory, *, user_id: str, session_id: str, record_id: str) -> None:
    """写入一名用户、会话和一条文本权威记忆。"""
    async with session_factory() as db:
        db.add(User(id=user_id, display_name="M7 fixture"))
        db.add(Session(id=session_id, user_id=user_id, mode="chat"))
        await db.commit()
        db.add(
            MemoryRecordRow(
                id=record_id,
                user_id=user_id,
                kind="text",
                category="topic_interest",
                content="合成测试记忆，不代表真实用户偏好",
                status="ACTIVE",
                scope="user",
                version=1,
                source="user_command",
                evidence_ref="fixture:message-1",
                policy_version=MEMORY_POLICY_VERSION,
                activation_source="explicit_user",
            )
        )
        await db.commit()


def _intent(message: str, *, user_id: str = "fixture-user", session_id: str = "fixture-session"):
    """构造测试命令并确保 parser 没有静默降级。"""
    result = parse_memory_command(message, user_id=user_id, session_id=session_id)
    assert result is not None
    return result


@pytest.mark.integration
def test_forget_confirm_is_one_shot_and_soft_deletes_authority(tmp_path: Path) -> None:
    """宽范围删除先 pending，再确认一次并写入 authority/outbox。"""

    async def run() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed(session_factory, user_id="fixture-user", session_id="fixture-session", record_id="record-a")
            async with session_factory() as db:
                use_case = MemoryCommandUseCase(db)
                preview = await use_case.execute(_intent("忘掉我的文本记忆"))
                assert preview.status is MemoryCommandStatus.CONFIRMATION_REQUIRED
                await db.commit()

            async with session_factory() as db:
                use_case = MemoryCommandUseCase(db)
                confirmed = await use_case.execute(_intent("确认"))
                assert confirmed.status is MemoryCommandStatus.SUCCEEDED
                await db.commit()

            async with session_factory() as db:
                row = await db.scalar(select(MemoryRecordRow).where(MemoryRecordRow.id == "record-a"))
                assert row is not None and row.status == "INACTIVE"
                replay = await use_case_result(db, "确认")
                assert replay.error_code == "CONFIRMATION_NOT_FOUND"
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.integration
def test_pending_confirmation_cannot_cross_user_or_session(tmp_path: Path) -> None:
    """不同用户或会话只能得到找不到 pending 的 fail-closed 结果。"""

    async def run() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed(session_factory, user_id="fixture-user", session_id="fixture-session", record_id="record-a")
            async with session_factory() as db:
                await MemoryCommandUseCase(db).execute(_intent("忘掉我的文本记忆"))
                await db.commit()
            async with session_factory() as db:
                other_user = await MemoryCommandUseCase(db).execute(
                    _intent("确认", user_id="fixture-user-b", session_id="fixture-session")
                )
                other_session = await MemoryCommandUseCase(db).execute(
                    _intent("确认", user_id="fixture-user", session_id="fixture-session-b")
                )
                assert other_user.error_code == "CONFIRMATION_NOT_FOUND"
                assert other_session.error_code == "CONFIRMATION_NOT_FOUND"
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.integration
def test_expired_pending_is_rejected_without_mutating_record(tmp_path: Path) -> None:
    """超过 TTL 的确认只能进入 EXPIRED，权威记录保持有效。"""

    async def run() -> None:
        engine, session_factory = await _factory(tmp_path)
        try:
            await _seed(session_factory, user_id="fixture-user", session_id="fixture-session", record_id="record-a")
            async with session_factory() as db:
                await MemoryCommandUseCase(db).execute(_intent("忘掉我的文本记忆"))
                pending = await db.scalar(select(MemoryPendingCommandRow))
                assert pending is not None
                pending.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
                await db.commit()
            async with session_factory() as db:
                result = await MemoryCommandUseCase(db).execute(_intent("确认"))
                assert result.status is MemoryCommandStatus.EXPIRED
                await db.commit()
                row = await db.scalar(select(MemoryRecordRow).where(MemoryRecordRow.id == "record-a"))
                assert row is not None and row.status == "ACTIVE"
        finally:
            await engine.dispose()

    asyncio.run(run())


async def use_case_result(db, message: str):
    """在新事务中执行一条命令，供 replay 断言复用。"""
    result = await MemoryCommandUseCase(db).execute(_intent(message))
    await db.commit()
    return result
