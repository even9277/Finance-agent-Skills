"""验证受控聊天应用用例的事务、持久化和用户隔离。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for path in (ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.application.chat.session_use_case import ChatSessionUseCase  # noqa: E402
from backend.db.database import Base  # noqa: E402
from backend.db.models import Message, Session  # noqa: E402
from backend.infrastructure.chat.repository import (  # noqa: E402
    SqlAlchemyConversationRepository,
)
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryTraceSink,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402


async def _create_session_factory(database_path: Path):
    """创建只服务于单个测试的 SQLite 引擎和 SessionFactory。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _workflow() -> ControlledConversationWorkflow:
    """构造不访问网络但执行真实领域阶段的工作流。"""
    return ControlledConversationWorkflow(
        model=FakeModelProvider(),
        tool=FakeToolProvider(),
        trace=InMemoryTraceSink(),
    )


@pytest.mark.integration
def test_use_case_commits_exactly_one_user_and_one_assistant(tmp_path: Path) -> None:
    """确认成功终态一次提交一对消息和会话元数据。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "success-v2.db")
        try:
            async with session_factory() as db:
                outcome = await ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(db),
                ).execute(
                    ChatCommand(
                        user_id="user-a",
                        message="查询贵州茅台 600519.SH 的基础信息和近期行情",
                    )
                )

            async with session_factory() as verification:
                stored_session = await verification.get(Session, outcome.session_id)
                messages = list(
                    (
                        await verification.execute(
                            select(Message)
                            .where(Message.session_id == outcome.session_id)
                            .order_by(Message.id)
                        )
                    )
                    .scalars()
                    .all()
                )

            assert stored_session is not None
            assert stored_session.user_id == "user-a"
            assert stored_session.turn_count == 1
            assert [(item.role, item.content) for item in messages] == [
                ("user", "查询贵州茅台 600519.SH 的基础信息和近期行情"),
                ("assistant", outcome.reply),
            ]
            assert outcome.context_window is not None
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
@pytest.mark.parametrize("failure", [RuntimeError("offline failure"), asyncio.CancelledError()])
def test_use_case_rolls_back_on_exception_or_cancellation(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    """确认异常和客户端取消都不会留下半轮消息。"""

    class FailingWorkflow:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise failure

    async def run_case() -> None:
        suffix = type(failure).__name__.lower()
        engine, session_factory = await _create_session_factory(tmp_path / f"{suffix}.db")
        try:
            async with session_factory() as db:
                use_case = ControlledChatUseCase(
                    workflow=FailingWorkflow(),  # type: ignore[arg-type]
                    repository=SqlAlchemyConversationRepository(db),
                )
                with pytest.raises(type(failure)):
                    await use_case.execute(
                        ChatCommand(user_id="user-failure", message="触发失败")
                    )

            async with session_factory() as verification:
                sessions = await verification.scalar(select(func.count(Session.id)))
                messages = await verification.scalar(select(func.count(Message.id)))
            assert sessions == 0
            assert messages == 0
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_cross_user_session_id_creates_new_isolated_session(tmp_path: Path) -> None:
    """确认用户 B 不能复用用户 A 的 session_id。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "isolation-v2.db")
        try:
            async with session_factory() as first_db:
                first = await ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(first_db),
                ).execute(ChatCommand(user_id="user-a", message="贵州茅台 600519.SH 行情"))

            async with session_factory() as second_db:
                second = await ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(second_db),
                ).execute(
                    ChatCommand(
                        user_id="user-b",
                        session_id=first.session_id,
                        message="贵州茅台 600519.SH 行情",
                    )
                )

            assert second.session_id != first.session_id
            async with session_factory() as verification:
                sessions = list(
                    (
                        await verification.execute(select(Session).order_by(Session.user_id))
                    )
                    .scalars()
                    .all()
                )
            assert [(item.user_id, item.id) for item in sessions] == [
                ("user-a", first.session_id),
                ("user-b", second.session_id),
            ]
        finally:
            await engine.dispose()

    asyncio.run(run_case())


@pytest.mark.integration
def test_session_management_uses_same_user_isolated_repository(tmp_path: Path) -> None:
    """确认列表、消息、重命名和删除不再依赖旧 Chat Service。"""

    async def run_case() -> None:
        engine, session_factory = await _create_session_factory(tmp_path / "sessions-v2.db")
        try:
            async with session_factory() as db:
                outcome = await ControlledChatUseCase(
                    workflow=_workflow(),
                    repository=SqlAlchemyConversationRepository(db),
                ).execute(ChatCommand(user_id="user-a", message="贵州茅台 600519.SH 行情"))

            async with session_factory() as db:
                sessions = ChatSessionUseCase(SqlAlchemyConversationRepository(db))
                listed = await sessions.list_sessions("user-a")
                page = await sessions.get_messages(outcome.session_id, "user-a")
                hidden = await sessions.get_messages(outcome.session_id, "user-b")
                changed = await sessions.rename_session(
                    outcome.session_id, "user-a", "新的会话标题"
                )

            assert [item.session_id for item in listed] == [outcome.session_id]
            assert [item.role for item in page.messages] == ["user", "assistant"]
            assert hidden.messages == ()
            assert changed is True

            async with session_factory() as db:
                sessions = ChatSessionUseCase(SqlAlchemyConversationRepository(db))
                assert (await sessions.list_sessions("user-a"))[0].title == "新的会话标题"
                assert await sessions.delete_session(outcome.session_id, "user-b") is False
                assert await sessions.delete_session(outcome.session_id, "user-a") is True

            async with session_factory() as db:
                assert await db.get(Session, outcome.session_id) is None
        finally:
            await engine.dispose()

    asyncio.run(run_case())
