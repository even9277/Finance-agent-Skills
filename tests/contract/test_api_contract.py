"""验证公开健康接口和聊天响应的最小 HTTP 契约。"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import chat_service  # noqa: E402


@pytest.mark.contract
def test_health_contract_is_public_and_versioned() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": settings.app_version}


@pytest.mark.contract
def test_chat_message_contract_maps_service_result() -> None:
    fake_result = ("离线 fake 回答", "session-test", None, None)

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_service,
        "chat_single_turn",
        new=AsyncMock(return_value=fake_result),
    ) as chat_mock:
        response = TestClient(app).post(
            "/api/chat/message",
            json={"user_id": "user-test", "message": "查询一个离线样例"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "离线 fake 回答",
        "session_id": "session-test",
        "memory_profile": None,
        "context_window": None,
    }
    chat_mock.assert_awaited_once()
