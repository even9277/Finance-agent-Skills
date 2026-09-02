"""从真实 FastAPI WebSocket 入口验收离线流式事务主链。"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.db.database import Base  # noqa: E402
from backend.db.models import Message, User  # noqa: E402
from backend.infrastructure.chat.repository import (  # noqa: E402
    SqlAlchemyConversationRepository,
)
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeToolProvider,
    InMemoryTraceSink,
)
from backend.routers import chat as chat_router  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ModelSynthesisChunk,
    ModelSynthesisRequest,
)
from src.conversation.errors import ModelSynthesisError  # noqa: E402
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402

_USER_ID = "offline-ws-user"
_QUESTION = "查询贵州茅台 600519.SH 的基础信息和近期行情"


@dataclass(slots=True)
class _ChunkedModel:
    """产生两个确定性增量，或在首增量后模拟 Provider 失败。"""

    fail_after_first: bool = False
    calls: list[ModelSynthesisRequest] = field(default_factory=list)

    async def stream_synthesize(self, request: ModelSynthesisRequest):
        """按固定顺序生成跨中文边界的增量。"""
        self.calls.append(request)
        yield ModelSynthesisChunk(content="第一段：行情证据已验收；", index=1)
        if self.fail_after_first:
            raise ModelSynthesisError("offline provider mid-stream detail")
        yield ModelSynthesisChunk(content="第二段：结论保持审慎。", index=2)


def _collect_frames(client: TestClient, *, request_id: str) -> list[dict[str, object]]:
    """发送一轮合法请求并读取到唯一公开终态。"""
    frames: list[dict[str, object]] = []
    with client.websocket_connect("/api/chat/stream") as websocket:
        websocket.send_json(
            {
                "user_id": _USER_ID,
                "message": _QUESTION,
                "request_id": request_id,
            }
        )
        while True:
            frame = websocket.receive_json()
            frames.append(frame)
            if frame["type"] in {"stream_end", "stream_error"}:
                return frames


async def _prepare_database(
    engine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """创建隔离 schema 和外键要求的测试用户。"""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(User(id=_USER_ID, display_name="offline websocket e2e"))
        await session.commit()


async def _read_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Message]:
    """读取当前隔离数据库内的完整消息序列。"""
    async with session_factory() as session:
        result = await session.execute(select(Message).order_by(Message.id))
        return list(result.scalars().all())


def _run_offline_websocket_case(
    tmp_path: Path,
    *,
    model: _ChunkedModel,
    request_id: str,
) -> tuple[list[dict[str, object]], list[Message]]:
    """装配真实 Router/Workflow/Repository 并执行一轮隔离 WS。"""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / f'{request_id}.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    asyncio.run(_prepare_database(engine, session_factory))
    tool = FakeToolProvider()
    trace = InMemoryTraceSink()

    def build_use_case(db: AsyncSession) -> ControlledChatUseCase:
        """为 Router 当前数据库会话装配真实受控工作流。"""
        return ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(model=model, tool=tool, trace=trace),
            repository=SqlAlchemyConversationRepository(db),
        )

    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/chat")
    try:
        with (
            patch.object(settings, "auth_enabled", False),
            patch.object(settings, "enable_memory", False),
            patch.object(settings, "enable_stm", False),
            patch.object(chat_router, "AsyncSessionFactory", new=session_factory),
            patch.object(chat_router, "build_chat_use_case", new=build_use_case),
        ):
            frames = _collect_frames(TestClient(app), request_id=request_id)
        messages = asyncio.run(_read_messages(session_factory))
        return frames, messages
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.e2e
def test_offline_websocket_multichunk_reply_matches_persisted_message(tmp_path: Path) -> None:
    """完整 v2 delta 拼接必须与唯一落库助手消息完全一致。"""
    model = _ChunkedModel()
    frames, messages = _run_offline_websocket_case(
        tmp_path,
        model=model,
        request_id="offline-ws-success",
    )

    assert [frame["sequence"] for frame in frames] == list(range(1, len(frames) + 1))
    assert all(frame["protocol_version"] == "chat-stream-v2" for frame in frames)
    deltas = [frame for frame in frames if frame["type"] == "content_delta"]
    assert [frame["chunk_index"] for frame in deltas] == [1, 2]
    reply = "".join(str(frame["content"]) for frame in deltas)
    terminal = frames[-1]
    assert terminal["type"] == "stream_end"
    assert terminal["chunk_count"] == 2
    assert terminal["content_sha256"] == hashlib.sha256(reply.encode()).hexdigest()
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].content == _QUESTION
    assert messages[1].content == reply
    assert len(model.calls) == 1


@pytest.mark.e2e
def test_offline_websocket_midstream_failure_rolls_back_database(tmp_path: Path) -> None:
    """首增量后 Provider 失败必须返回 Error，且用户/助手消息均不落库。"""
    frames, messages = _run_offline_websocket_case(
        tmp_path,
        model=_ChunkedModel(fail_after_first=True),
        request_id="offline-ws-midstream-failure",
    )

    assert [frame["type"] for frame in frames] == [
        "stream_start",
        "content_delta",
        "stream_error",
    ]
    assert frames[-1]["code"] == "CHAT_STREAM_FAILED"
    assert frames[-1]["chunk_count"] == 1
    assert "offline provider mid-stream detail" not in str(frames[-1])
    assert messages == []
