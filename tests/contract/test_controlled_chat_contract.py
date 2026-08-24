"""锁定迁移前 REST/WS 聊天协议与已知错误暴露行为。"""

from __future__ import annotations

import json
import sys
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import chat as chat_router  # noqa: E402
from backend.services import chat_service  # noqa: E402


class _OfflineSessionContext(AbstractAsyncContextManager[object]):
    """为 WebSocket Router 提供不连接数据库的异步上下文。"""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info


@pytest.mark.contract
def test_rest_message_preserves_response_shape_and_service_arguments() -> None:
    """确认 REST Presenter 保持现有四字段响应并透传业务参数。"""
    service_result = (
        "离线刻画回答",
        "session-characterization",
        {"risk_level": "balanced"},
        {
            "used_tokens": 12,
            "budget_tokens": 100,
            "usage_percent": 12,
            "counting_mode": "estimated",
            "compression_status": "idle",
            "strategy": "dynamic_budget",
            "updated_at": None,
        },
    )

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_service,
        "chat_single_turn",
        new=AsyncMock(return_value=service_result),
    ) as chat_mock:
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

    await_call = chat_mock.await_args
    assert await_call is not None
    kwargs = await_call.kwargs
    assert kwargs["user_id"] == "user-characterization"
    assert kwargs["user_message"] == "固定离线问题"
    assert kwargs["session_id"] == "session-existing"
    assert kwargs["db"] is not None


@pytest.mark.contract
def test_rest_validation_rejects_missing_message_before_service_call() -> None:
    """确认无 message 的请求由 Pydantic 边界拒绝，不进入 Chat Service。"""
    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_service,
        "chat_single_turn",
        new=AsyncMock(),
    ) as chat_mock:
        response = TestClient(app).post(
            "/api/chat/message",
            json={"user_id": "user-characterization"},
        )

    assert response.status_code == 422
    chat_mock.assert_not_awaited()


@pytest.mark.contract
def test_websocket_preserves_legacy_frame_order() -> None:
    """确认 WS 仍按会话、内容、上下文、完成的顺序发送兼容帧。"""
    captured: dict[str, Any] = {}

    async def fake_stream_chat_single_turn(**kwargs: Any) -> AsyncIterator[str]:
        captured.update(kwargs)
        yield json.dumps(
            {"type": "session_id", "session_id": "session-characterization"},
            ensure_ascii=False,
        )
        yield "离线-token"
        yield json.dumps(
            {
                "type": "context_update",
                "session_id": "session-characterization",
                "context_window": {"usage_percent": 10},
            },
            ensure_ascii=False,
        )
        yield json.dumps(
            {"type": "done", "session_id": "session-characterization"},
            ensure_ascii=False,
        )

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(
        chat_service,
        "stream_chat_single_turn",
        new=fake_stream_chat_single_turn,
    ):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {
                    "user_id": "user-characterization",
                    "message": "固定流式问题",
                    "session_id": None,
                }
            )
            frames = [websocket.receive_text() for _ in range(4)]

    decoded: list[Any] = [
        json.loads(frame) if frame.startswith("{") else frame for frame in frames
    ]
    assert decoded[0] == {
        "type": "session_id",
        "session_id": "session-characterization",
    }
    assert decoded[1] == "离线-token"
    assert decoded[2]["type"] == "context_update"
    assert decoded[3] == {"type": "done", "session_id": "session-characterization"}
    assert captured["user_id"] == "user-characterization"
    assert captured["user_message"] == "固定流式问题"
    assert captured["session_id"] is None


@pytest.mark.contract
@pytest.mark.xfail(
    strict=True,
    reason="迁移前 WS Router 会把内部异常原文返回客户端；Milestone 6 必须改为稳定错误码和安全文案。",
)
def test_websocket_does_not_expose_internal_exception_text() -> None:
    """登记当前 WS 会泄露内部异常原文的已知安全缺陷。"""

    async def failing_stream(**kwargs: Any) -> AsyncIterator[str]:
        del kwargs
        if False:  # pragma: no cover - 仅把函数声明为异步生成器
            yield ""
        raise RuntimeError("database-internal-detail")

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(
        chat_service,
        "stream_chat_single_turn",
        new=failing_stream,
    ):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {"user_id": "user-characterization", "message": "触发离线异常"}
            )
            frame = websocket.receive_json()

    assert frame == {"type": "error", "message": "对话处理失败"}
