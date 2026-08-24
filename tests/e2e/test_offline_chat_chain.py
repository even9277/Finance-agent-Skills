"""从 HTTP 入口验证离线 fake 聊天链路的主路径和失败路径。"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import chat as chat_router  # noqa: E402
from backend.application.chat.contracts import ChatOutcome  # noqa: E402
from src.conversation.contracts import TerminalStatus  # noqa: E402


@pytest.mark.e2e
def test_offline_chat_request_reaches_fake_provider_and_returns_response() -> None:
    use_case = Mock()
    use_case.execute = AsyncMock(
        return_value=ChatOutcome(
            reply="fake-provider: answer",
            session_id="offline-session",
            status=TerminalStatus.SUCCEEDED,
        )
    )

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/chat/message",
            json={"user_id": "offline-user", "message": "请给出固定的离线回答"},
        )

    assert response.status_code == 200
    assert response.json()["reply"] == "fake-provider: answer"
    use_case.execute.assert_awaited_once()


@pytest.mark.e2e
def test_offline_chat_provider_failure_returns_non_success_contract() -> None:
    use_case = Mock()
    use_case.execute = AsyncMock(side_effect=RuntimeError("fake provider timeout"))
    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/chat/message",
            json={"user_id": "offline-user", "message": "触发 fake 超时"},
        )

    assert response.status_code >= 500
    assert response.status_code < 600
