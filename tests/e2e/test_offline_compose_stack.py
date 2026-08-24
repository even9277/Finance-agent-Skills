"""从前端容器入口验证离线 Compose 的前后端代理链路。"""

import json
import os
from urllib.request import Request, urlopen

import pytest


@pytest.mark.e2e
def test_frontend_proxy_reaches_backend_and_fake_chat_chain() -> None:
    """验证 Vue 静态入口、Nginx 代理、FastAPI 契约和 Fake 聊天结果。"""
    base_url = os.getenv("OFFLINE_STACK_BASE_URL", "").rstrip("/")
    if not base_url:
        pytest.skip("OFFLINE_STACK_BASE_URL 未设置；仅在 Compose 完整链路中执行")

    with urlopen(f"{base_url}/", timeout=10) as response:  # noqa: S310
        frontend_html = response.read().decode("utf-8")
    assert response.status == 200
    assert '<div id="app"></div>' in frontend_html

    with urlopen(f"{base_url}/api/health", timeout=10) as response:  # noqa: S310
        health = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert health["status"] == "ok"
    assert health["version"]

    request = Request(
        f"{base_url}/api/chat/message",
        data=json.dumps(
            {"user_id": "offline-user", "message": "请给出固定的离线回答"}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310
        chat = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert chat == {
        "reply": "fake-provider: answer",
        "session_id": "offline-session",
        "memory_profile": None,
        "context_window": None,
    }
