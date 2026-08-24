"""锁定迁移前同步聊天的提交、失败回滚和用户会话隔离行为。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.database import Base  # noqa: E402
from backend.db.models import Message, Session  # noqa: E402
from backend.services import chat_service  # noqa: E402

AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))
from src.tools import skill_trace  # noqa: E402


def _skill_result(reply: str = "离线刻画回答") -> tuple[str, None, dict[str, Any], str]:
    """构造与当前 Chat Service 相同的离线 Skill 返回合同。"""
    return (
        reply,
        None,
        {
            "selected_skill_family": "tushare-data",
            "selected_skill": "tushare-data",
            "skill_name": None,
            "analysis_mode": "single_stock_data",
            "execution_policy": "deterministic",
            "confidence": 0.9,
            "evidence_ok": True,
        },
        "",
    )


async def _create_session_factory(database_path: Path):
    """创建只服务于单个测试的 SQLite 引擎和 SessionFactory。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.integration
def test_sync_turn_commits_exactly_one_user_and_one_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认成功单轮提交一对消息，并同步更新会话轮次和标题。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "success.db")
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", tmp_path / "success-trace.jsonl")
        skill_trace.clear_trace_exporters()
        try:
            async with session_factory() as database_session:
                with patch.object(chat_service.settings, "enable_memory", False), patch.object(
                    chat_service.settings,
                    "enable_stm",
                    False,
                ), patch.object(
                    chat_service,
                    "_run_skill_chat_if_enabled",
                    new=AsyncMock(return_value=_skill_result()),
                ):
                    reply, session_id, memory_profile, context_window = (
                        await chat_service.chat_single_turn(
                            db=database_session,
                            user_id="user-a",
                            user_message="查询 600519.SH 最新行情",
                        )
                    )

            async with session_factory() as verification_session:
                stored_session = (
                    await verification_session.execute(
                        select(Session).where(Session.id == session_id)
                    )
                ).scalar_one()
                messages = list(
                    (
                        await verification_session.execute(
                            select(Message)
                            .where(Message.session_id == session_id)
                            .order_by(Message.created_at)
                        )
                    )
                    .scalars()
                    .all()
                )

            assert reply == "离线刻画回答"
            assert memory_profile is None
            assert context_window is not None
            assert stored_session.user_id == "user-a"
            assert stored_session.turn_count == 1
            assert stored_session.title == "查询 600519.SH 最新行情"
            assert [(message.role, message.content) for message in messages] == [
                ("user", "查询 600519.SH 最新行情"),
                ("assistant", "离线刻画回答"),
            ]
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_sync_turn_failure_rolls_back_when_request_session_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认执行失败后关闭请求 Session 不会留下未提交会话或用户消息。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "failure.db")
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", tmp_path / "failure-trace.jsonl")
        skill_trace.clear_trace_exporters()
        try:
            with pytest.raises(RuntimeError, match="offline executor failure"):
                async with session_factory() as database_session:
                    with patch.object(
                        chat_service.settings,
                        "enable_memory",
                        False,
                    ), patch.object(
                        chat_service.settings,
                        "enable_stm",
                        False,
                    ), patch.object(
                        chat_service,
                        "_run_skill_chat_if_enabled",
                        new=AsyncMock(side_effect=RuntimeError("offline executor failure")),
                    ):
                        await chat_service.chat_single_turn(
                            db=database_session,
                            user_id="user-failure",
                            user_message="触发离线失败",
                        )

            async with session_factory() as verification_session:
                session_count = await verification_session.scalar(
                    select(func.count(Session.id)).where(Session.user_id == "user-failure")
                )
                message_count = await verification_session.scalar(select(func.count(Message.id)))

            assert session_count == 0
            assert message_count == 0
            records = [
                json.loads(line)
                for line in (tmp_path / "failure-trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            terminal = [
                record
                for record in records
                if record["record_type"] == "trace" and record["status"] == "error"
            ]
            assert len(terminal) == 1
            assert terminal[0]["data"]["final_status"] == "error"
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_cross_user_session_id_creates_new_isolated_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认用户 B 传入用户 A 的 session_id 时不会复用 A 的会话。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "isolation.db")
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", tmp_path / "isolation-trace.jsonl")
        skill_trace.clear_trace_exporters()
        try:
            with patch.object(chat_service.settings, "enable_memory", False), patch.object(
                chat_service.settings,
                "enable_stm",
                False,
            ), patch.object(
                chat_service,
                "_run_skill_chat_if_enabled",
                new=AsyncMock(return_value=_skill_result()),
            ):
                async with session_factory() as first_database_session:
                    _, first_session_id, _, _ = await chat_service.chat_single_turn(
                        db=first_database_session,
                        user_id="user-a",
                        user_message="用户 A 的问题",
                    )

                async with session_factory() as second_database_session:
                    _, second_session_id, _, _ = await chat_service.chat_single_turn(
                        db=second_database_session,
                        user_id="user-b",
                        user_message="用户 B 的问题",
                        session_id=first_session_id,
                    )

            async with session_factory() as verification_session:
                sessions = list(
                    (
                        await verification_session.execute(
                            select(Session).order_by(Session.user_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                message_counts = {
                    session.id: await verification_session.scalar(
                        select(func.count(Message.id)).where(Message.session_id == session.id)
                    )
                    for session in sessions
                }

            assert second_session_id != first_session_id
            assert [(session.user_id, session.id) for session in sessions] == [
                ("user-a", first_session_id),
                ("user-b", second_session_id),
            ]
            assert message_counts == {first_session_id: 2, second_session_id: 2}
        finally:
            await engine.dispose()

    asyncio.run(run_case())
