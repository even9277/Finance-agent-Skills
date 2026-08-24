"""从 HTTP 入口验证离线 fake 聊天链路的主路径和失败路径。"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import chat_service  # noqa: E402


@pytest.mark.e2e
def test_offline_chat_request_reaches_fake_provider_and_returns_response() -> None:
    fake_result = ("fake-provider: answer", "offline-session", None, None)

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_service,
        "chat_single_turn",
        new=AsyncMock(return_value=fake_result),
    ) as fake_provider:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/chat/message",
            json={"user_id": "offline-user", "message": "请给出固定的离线回答"},
        )

    assert response.status_code == 200
    assert response.json()["reply"] == "fake-provider: answer"
    fake_provider.assert_awaited_once()


@pytest.mark.e2e
def test_offline_chat_provider_failure_returns_non_success_contract() -> None:
    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_service,
        "chat_single_turn",
        new=AsyncMock(side_effect=RuntimeError("fake provider timeout")),
    ):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/chat/message",
            json={"user_id": "offline-user", "message": "触发 fake 超时"},
        )

    assert response.status_code >= 500
    assert response.status_code < 600
