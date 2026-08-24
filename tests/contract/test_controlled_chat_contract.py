"""锁定公开 REST/WS 统一应用用例与兼容协议。"""

from __future__ import annotations

import ast
import json
import sys
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.application.chat.contracts import ChatContextWindowData, ChatOutcome  # noqa: E402
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
def test_websocket_maps_same_outcome_to_legacy_frame_order() -> None:
    """确认 WS 将同一应用输出映射为会话、内容、上下文、完成帧。"""
    use_case = Mock()
    use_case.execute = AsyncMock(return_value=_outcome())

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
                }
            )
            frames = [websocket.receive_text() for _ in range(4)]

    decoded: list[Any] = [
        json.loads(frame) if frame.startswith("{") else frame for frame in frames
    ]
    assert decoded[0] == {"type": "session_id", "session_id": "session-characterization"}
    assert decoded[1] == "离线刻画回答"
    assert decoded[2]["type"] == "context_update"
    assert decoded[3] == {"type": "done", "session_id": "session-characterization"}

    command = use_case.execute.await_args.args[0]
    assert command.user_id == "user-characterization"
    assert command.message == "固定流式问题"
    assert command.session_id is None


@pytest.mark.contract
def test_websocket_does_not_expose_internal_exception_text() -> None:
    """确认未知异常只返回稳定错误码和安全文案。"""
    use_case = Mock()
    use_case.execute = AsyncMock(side_effect=RuntimeError("database-internal-detail"))

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(chat_router, "build_chat_use_case", return_value=use_case):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {"user_id": "user-characterization", "message": "触发离线异常"}
            )
            frame = websocket.receive_json()

    assert frame == {
        "type": "error",
        "code": "CHAT_INTERNAL_ERROR",
        "message": "对话处理失败",
    }
