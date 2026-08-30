"""验证 explicit Skill 与确认载荷的公开 REST/WS 兼容合同。"""

from __future__ import annotations

import json
import sys
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.application.chat.contracts import ChatOutcome  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import chat as chat_router  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    SkillConfirmation,
    SkillConfirmationCandidate,
    TerminalStatus,
)


class _OfflineSessionContext(AbstractAsyncContextManager[object]):
    """为 WebSocket Router 提供不连接数据库的异步上下文。"""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info


def _confirmation() -> SkillConfirmation:
    """构造不含工具权限或正文的公开确认载荷。"""
    return SkillConfirmation(
        candidates=(
            SkillConfirmationCandidate(
                skill_name="fund-compare",
                confidence=0.72,
                version="1.1.0",
                reason="基金比较语义相近",
            ),
            SkillConfirmationCandidate(
                skill_name="etf-screen",
                confidence=0.66,
                version="1.1.0",
                reason="ETF 筛选语义相近",
            ),
        ),
        reason="需要用户确认专业分析任务",
        registry_snapshot_hash="a" * 64,
    )


def _confirmation_outcome() -> ChatOutcome:
    """构造公开协议应转换为确认卡的应用输出。"""
    return ChatOutcome(
        reply="请选择更符合意图的分析 Skill。",
        session_id="session-confirm",
        status=TerminalStatus.NEEDS_CLARIFICATION,
        skill_confirmation=_confirmation(),
    )


@pytest.mark.contract
def test_rest_forwards_explicit_skill_and_returns_optional_confirmation() -> None:
    """REST 必须透传显式选择，并仅在需要时增量返回确认载荷。"""
    use_case = Mock()
    use_case.execute = AsyncMock(return_value=_confirmation_outcome())

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router, "build_chat_use_case", return_value=use_case
    ):
        response = TestClient(app).post(
            "/api/chat/message",
            json={
                "user_id": "user-confirm",
                "message": "比较两只黄金基金",
                "session_id": "session-confirm",
                "explicit_skill": "fund-compare",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_confirmation"]["registry_snapshot_hash"] == "a" * 64
    assert [item["skill_name"] for item in payload["skill_confirmation"]["candidates"]] == [
        "fund-compare",
        "etf-screen",
    ]
    command = use_case.execute.await_args.args[0]
    assert command.session_id == "session-confirm"
    assert command.explicit_skill == "fund-compare"


@pytest.mark.contract
def test_websocket_emits_skill_confirm_frame_without_changing_normal_text_frame() -> None:
    """中置信 WS 应先发确认控制帧，同时保留旧文本澄清和 done。"""
    use_case = Mock()
    use_case.execute = AsyncMock(return_value=_confirmation_outcome())

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(chat_router, "build_chat_use_case", return_value=use_case):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {
                    "user_id": "user-confirm",
                    "message": "帮我分析一下黄金相关产品",
                    "session_id": "session-confirm",
                }
            )
            frames = [websocket.receive_text() for _ in range(4)]

    assert json.loads(frames[0]) == {"type": "session_id", "session_id": "session-confirm"}
    confirmation_frame = json.loads(frames[1])
    assert confirmation_frame["type"] == "skill_confirm"
    assert confirmation_frame["session_id"] == "session-confirm"
    assert confirmation_frame["confirmation"]["reason"] == "需要用户确认专业分析任务"
    assert frames[2] == "请选择更符合意图的分析 Skill。"
    assert json.loads(frames[3]) == {"type": "done", "session_id": "session-confirm"}


@pytest.mark.contract
def test_websocket_forwards_explicit_skill_on_same_session() -> None:
    """确认后的 WS 重提必须携带原 session 与 explicit Skill。"""
    use_case = Mock()
    use_case.execute = AsyncMock(
        return_value=ChatOutcome(
            reply="已按基金比较执行。",
            session_id="session-confirm",
            status=TerminalStatus.SUCCEEDED,
        )
    )

    with patch.object(settings, "auth_enabled", False), patch.object(
        chat_router,
        "AsyncSessionFactory",
        new=lambda: _OfflineSessionContext(),
    ), patch.object(chat_router, "build_chat_use_case", return_value=use_case):
        with TestClient(app).websocket_connect("/api/chat/stream") as websocket:
            websocket.send_json(
                {
                    "user_id": "user-confirm",
                    "message": "比较两只黄金基金",
                    "session_id": "session-confirm",
                    "explicit_skill": "fund-compare",
                }
            )
            frames = [websocket.receive_text() for _ in range(3)]

    assert json.loads(frames[0])["type"] == "session_id"
    assert frames[1] == "已按基金比较执行。"
    assert json.loads(frames[2])["type"] == "done"
    command = use_case.execute.await_args.args[0]
    assert command.session_id == "session-confirm"
    assert command.explicit_skill == "fund-compare"
