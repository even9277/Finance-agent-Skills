"""锁定公开 REST/WS 统一应用用例与兼容协议。"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import sys
import time
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.application.chat.contracts import (  # noqa: E402
    ChatContentDelta,
    ChatContextWindowData,
    ChatOutcome,
    ChatStreamCompleted,
    ChatStreamFailed,
    ChatStreamFailureCode,
    ChatStreamStarted,
)
from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import chat as chat_router  # noqa: E402
from src.conversation.contracts import TerminalStatus  # noqa: E402


class _OfflineSessionContext(AbstractAsyncContextManager[object]):
    """为 WebSocket Router 提供不连接数据库的异步上下文。"""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info


class _DisconnectingWebSocket:
    """在首个内容帧写入时模拟客户端断连。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        """记录开始帧，并在正文写入时抛出标准断连异常。"""
        if payload["type"] == "content_delta":
            raise WebSocketDisconnect(code=1001)
        self.frames.append(payload)


class _CollectingWebSocket:
    """收集一个并发连接实际收到的全部公开 JSON 帧。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        """保存当前连接帧，并主动让出调度以制造交错执行。"""
        self.frames.append(payload)
        await asyncio.sleep(0)


class _ObservedDisconnectWebSocket:
    """在首个正文帧写入后通过接收侧报告浏览器断连。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []
        self.delta_sent = asyncio.Event()

    async def send_json(self, payload: dict[str, object]) -> None:
        """允许发送成功，复现 TCP 写入未立即报错的浏览器行为。"""
        self.frames.append(payload)
        if payload["type"] == "content_delta":
            self.delta_sent.set()

    async def receive(self) -> dict[str, object]:
        """等待首个增量后返回标准 ASGI disconnect 事件。"""
        await self.delta_sent.wait()
        return {"type": "websocket.disconnect", "code": 1001}


def _outcome() -> ChatOutcome:
    """构造 REST/WS 共用的稳定应用输出。"""
    return ChatOutcome(
        reply="离线刻画回答",
        session_id="session-characterization",
        status=TerminalStatus.SUCCEEDED,
        memory_profile={"risk_level": "balanced"},
        context_window=ChatContextWindowData(
            used_tokens=12,
            budget_tokens=100,
            usage_percent=12,
            counting_mode="estimated",
            compression_status="idle",
            strategy="dynamic_budget",
        ),
    )


async def _successful_stream(command):
    """产生两个增量和一个已提交终态，供 WS Presenter 合同消费。"""
    outcome = _outcome()
    request_id = command.request_id or "request-characterization"
    yield ChatStreamStarted(session_id=outcome.session_id, request_id=request_id)
    yield ChatContentDelta(
        session_id=outcome.session_id,
        request_id=request_id,
        content="离线刻画",
        chunk_index=1,
    )
    yield ChatContentDelta(
        session_id=outcome.session_id,
        request_id=request_id,
        content="回答",
        chunk_index=2,
    )
    yield ChatStreamCompleted(
        session_id=outcome.session_id,
        request_id=request_id,
        outcome=outcome,
        chunk_count=2,
        content_sha256=hashlib.sha256(outcome.reply.encode()).hexdigest(),
        ttft_ms=12.5,
        elapsed_ms=42.0,
    )


async def _failed_stream(command):
    """产生已回滚的技术失败终态，不携带内部异常正文。"""
    request_id = command.request_id or "request-characterization"
    yield ChatStreamStarted(
        session_id="session-characterization",
        request_id=request_id,
    )
    yield ChatStreamFailed(
        session_id="session-characterization",
        request_id=request_id,
        error_code=ChatStreamFailureCode.STREAM_FAILED,
        chunk_count=0,
        ttft_ms=None,
        elapsed_ms=8.0,
    )


@pytest.mark.contract
def test_chat_router_has_no_legacy_chat_service_dependency() -> None:
    """确认公开入口不能通过导入或转发继续保留旧双轨。"""
    tree = ast.parse(Path(chat_router.__file__).read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert "backend.services.chat_service" not in imported_modules
    assert not any(module == "backend.services" for module in imported_modules)


@pytest.mark.contract
def test_rest_message_preserves_response_shape_and_use_case_command() -> None:
    """确认 REST Presenter 保持四字段响应并只调用统一应用用例。"""
    use_case = Mock()
    use_case.execute = AsyncMock(return_value=_outcome())

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
        response = TestClient(app).post(
            "/api/chat/message",
            json={
                "user_id": "user-characterization",
                "message": "固定离线问题",
                "session_id": "session-existing",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"reply", "session_id", "memory_profile", "context_window"}
    assert payload["reply"] == "离线刻画回答"
    assert payload["session_id"] == "session-characterization"
    assert payload["memory_profile"] == {"risk_level": "balanced"}
    assert payload["context_window"]["usage_percent"] == 12

    command = use_case.execute.await_args.args[0]
    assert command.user_id == "user-characterization"
    assert command.message == "固定离线问题"
    assert command.session_id == "session-existing"


@pytest.mark.contract
def test_rest_validation_rejects_missing_message_before_use_case_call() -> None:
    """确认无 message 的请求在边界拒绝，不进入应用用例。"""
    use_case = Mock()
    use_case.execute = AsyncMock()

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
        response = TestClient(app).post(
            "/api/chat/message", json={"user_id": "user-characterization"}
        )

    assert response.status_code == 422
    use_case.execute.assert_not_awaited()


@pytest.mark.contract
def test_rest_validation_rejects_blank_message_before_use_case_call() -> None:
    """确认纯空白消息返回 422，而不是在应用层变成内部错误。"""
    use_case = Mock()
    use_case.execute = AsyncMock()

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
        response = TestClient(app).post(
            "/api/chat/message",
            json={"user_id": "user-characterization", "message": "   "},
        )

    assert response.status_code == 422
    use_case.execute.assert_not_awaited()


@pytest.mark.contract
def test_websocket_maps_application_stream_to_v2_json_lifecycle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """确认 WS 只发送带关联字段、严格顺序和无重复全文的 v2 JSON。"""
    caplog.set_level(logging.INFO, logger="backend.routers.chat")
    use_case = Mock()
    use_case.execute = AsyncMock(side_effect=AssertionError("legacy execute path must not run"))
    use_case.stream = Mock(side_effect=_successful_stream)

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(chat_router, "build_chat_use_case", return_value=use_case):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {
                    "user_id": "user-characterization",
                    "message": "固定流式问题",
                    "session_id": None,
                    "request_id": "request-characterization",
                }
            )
            frames = [websocket.receive_json() for _ in range(5)]

    assert [frame["type"] for frame in frames] == [
        "stream_start",
        "content_delta",
        "content_delta",
        "context_update",
        "stream_end",
    ]
    assert [frame["sequence"] for frame in frames] == [1, 2, 3, 4, 5]
    assert all(frame["protocol_version"] == "chat-stream-v2" for frame in frames)
    assert all(frame["request_id"] == "request-characterization" for frame in frames)
    assert all(frame["session_id"] == "session-characterization" for frame in frames)
    assert frames[1]["content"] == "离线刻画"
    assert frames[1]["chunk_index"] == 1
    assert frames[2]["content"] == "回答"
    assert frames[4]["status"] == "SUCCEEDED"
    assert frames[4]["chunk_count"] == 2
    assert frames[4]["content_sha256"] == hashlib.sha256("离线刻画回答".encode()).hexdigest()
    assert "content" not in frames[4]
    assert "chunk_count=2" in caplog.text
    assert "output_chars=6" in caplog.text
    assert "server_ttft_ms=" in caplog.text
    assert "离线刻画回答" not in caplog.text

    command = use_case.stream.call_args.args[0]
    assert command.user_id == "user-characterization"
    assert command.message == "固定流式问题"
    assert command.session_id is None
    assert command.request_id == "request-characterization"


@pytest.mark.contract
def test_websocket_does_not_expose_internal_exception_text() -> None:
    """确认未知异常只返回稳定错误码和安全文案。"""
    use_case = Mock()
    use_case.execute = AsyncMock(side_effect=AssertionError("legacy execute path must not run"))
    use_case.stream = Mock(side_effect=_failed_stream)

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(chat_router, "build_chat_use_case", return_value=use_case):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {
                    "user_id": "user-characterization",
                    "message": "触发离线异常",
                    "request_id": "request-characterization",
                }
            )
            started = websocket.receive_json()
            failed = websocket.receive_json()

    assert started["type"] == "stream_start"
    assert failed == {
        "type": "stream_error",
        "protocol_version": "chat-stream-v2",
        "request_id": "request-characterization",
        "session_id": "session-characterization",
        "sequence": 2,
        "code": "CHAT_STREAM_FAILED",
        "message": "对话处理失败",
        "chunk_count": 0,
    }
    assert "database-internal-detail" not in json.dumps(failed, ensure_ascii=False)


@pytest.mark.contract
def test_websocket_send_failure_closes_application_stream() -> None:
    """发送失败必须立即关闭 Application generator，不能遗留后台生成任务。"""

    async def run_case() -> None:
        finalized = asyncio.Event()

        async def event_stream():
            try:
                yield ChatStreamStarted(
                    session_id="session-disconnect",
                    request_id="request-disconnect",
                )
                yield ChatContentDelta(
                    session_id="session-disconnect",
                    request_id="request-disconnect",
                    content="不会成功写入",
                    chunk_index=1,
                )
                await asyncio.Event().wait()
            finally:
                finalized.set()

        websocket = _DisconnectingWebSocket()
        state = chat_router._WebSocketStreamState(
            request_id="request-disconnect",
            session_id="session-disconnect",
            started_at=time.perf_counter(),
        )

        with pytest.raises(WebSocketDisconnect):
            await chat_router._present_chat_stream(
                cast(WebSocket, websocket),
                event_stream(),
                state,
            )

        assert finalized.is_set()
        assert [frame["type"] for frame in websocket.frames] == ["stream_start"]
        assert state.terminal_sent is False

    asyncio.run(run_case())


@pytest.mark.contract
def test_websocket_receive_side_disconnect_cancels_hanging_application_stream() -> None:
    """发送未报错时也必须主动消费 disconnect，并关闭仍在生成的上游流。"""

    async def run_case() -> None:
        finalized = asyncio.Event()

        async def event_stream():
            try:
                yield ChatStreamStarted(
                    session_id="session-observed-disconnect",
                    request_id="request-observed-disconnect",
                )
                yield ChatContentDelta(
                    session_id="session-observed-disconnect",
                    request_id="request-observed-disconnect",
                    content="首个可见增量",
                    chunk_index=1,
                )
                await asyncio.Event().wait()
            finally:
                finalized.set()

        websocket = _ObservedDisconnectWebSocket()
        state = chat_router._WebSocketStreamState(
            request_id="request-observed-disconnect",
            session_id="session-observed-disconnect",
            started_at=time.perf_counter(),
        )

        with pytest.raises(WebSocketDisconnect) as error:
            await asyncio.wait_for(
                chat_router._present_chat_stream_until_disconnect(
                    cast(WebSocket, websocket),
                    event_stream(),
                    state,
                ),
                timeout=1,
            )

        assert error.value.code == 1001
        assert finalized.is_set()
        assert [frame["type"] for frame in websocket.frames] == [
            "stream_start",
            "content_delta",
        ]
        assert state.terminal_sent is False

    asyncio.run(run_case())


@pytest.mark.contract
def test_websocket_invalid_json_uses_v2_error_envelope() -> None:
    """输入尚未形成业务命令时也不得回退到旧 error 帧。"""
    with patch.object(settings, "auth_enabled", False):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_text("{")
            frame = websocket.receive_json()

    assert frame["type"] == "stream_error"
    assert frame["protocol_version"] == "chat-stream-v2"
    assert frame["sequence"] == 1
    assert frame["code"] == "CHAT_INVALID_JSON"
    assert frame["session_id"] == "unavailable"
    assert frame["request_id"].startswith("req_")


@pytest.mark.contract
def test_concurrent_websocket_presenters_keep_request_and_session_isolated() -> None:
    """两个交错连接的关联字段、sequence 和正文不得发生串流。"""

    async def run_case() -> None:
        async def event_stream(request_id: str, session_id: str, content: str):
            outcome = ChatOutcome(
                reply=content,
                session_id=session_id,
                status=TerminalStatus.SUCCEEDED,
            )
            yield ChatStreamStarted(session_id=session_id, request_id=request_id)
            await asyncio.sleep(0)
            yield ChatContentDelta(
                session_id=session_id,
                request_id=request_id,
                content=content,
                chunk_index=1,
            )
            await asyncio.sleep(0)
            yield ChatStreamCompleted(
                session_id=session_id,
                request_id=request_id,
                outcome=outcome,
                chunk_count=1,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                ttft_ms=1.0,
                elapsed_ms=2.0,
            )

        websocket_a = _CollectingWebSocket()
        websocket_b = _CollectingWebSocket()
        state_a = chat_router._WebSocketStreamState(
            request_id="request-a",
            session_id="session-a",
            started_at=time.perf_counter(),
        )
        state_b = chat_router._WebSocketStreamState(
            request_id="request-b",
            session_id="session-b",
            started_at=time.perf_counter(),
        )

        await asyncio.gather(
            chat_router._present_chat_stream(
                cast(WebSocket, websocket_a),
                event_stream("request-a", "session-a", "回答 A"),
                state_a,
            ),
            chat_router._present_chat_stream(
                cast(WebSocket, websocket_b),
                event_stream("request-b", "session-b", "回答 B"),
                state_b,
            ),
        )

        assert [frame["sequence"] for frame in websocket_a.frames] == [1, 2, 3]
        assert [frame["sequence"] for frame in websocket_b.frames] == [1, 2, 3]
        assert {frame["request_id"] for frame in websocket_a.frames} == {"request-a"}
        assert {frame["session_id"] for frame in websocket_a.frames} == {"session-a"}
        assert {frame["request_id"] for frame in websocket_b.frames} == {"request-b"}
        assert {frame["session_id"] for frame in websocket_b.frames} == {"session-b"}
        assert websocket_a.frames[1]["content"] == "回答 A"
        assert websocket_b.frames[1]["content"] == "回答 B"

    asyncio.run(run_case())
