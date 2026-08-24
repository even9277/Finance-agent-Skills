"""验证公开健康接口和聊天响应的最小 HTTP 契约。"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import chat as chat_router  # noqa: E402
from backend.application.chat.contracts import ChatOutcome  # noqa: E402
from src.conversation.contracts import TerminalStatus  # noqa: E402


@pytest.mark.contract
def test_health_contract_is_public_and_versioned() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": settings.app_version}


@pytest.mark.contract
def test_chat_message_contract_maps_use_case_result() -> None:
    use_case = Mock()
    use_case.execute = AsyncMock(
        return_value=ChatOutcome(
            reply="离线 fake 回答",
            session_id="session-test",
            status=TerminalStatus.SUCCEEDED,
        )
    )

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
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
    use_case.execute.assert_awaited_once()
