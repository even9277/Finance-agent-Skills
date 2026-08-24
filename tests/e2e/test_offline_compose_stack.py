"""从前端容器入口验证离线 Compose 的前后端代理链路。"""

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

import pytest


@pytest.mark.e2e
def test_frontend_proxy_reaches_backend_and_fake_chat_chain() -> None:
    """验证 Vue/Nginx/FastAPI/真实工作流/Fake Ports/PostgreSQL 完整链。"""
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

    init_request = Request(
        f"{base_url}/api/user/init",
        data=json.dumps(
            {"user_id": "offline-user", "display_name": "离线验收用户"}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(init_request, timeout=10) as response:  # noqa: S310
        initialized = json.loads(response.read().decode("utf-8"))
    assert initialized["user_id"] == "offline-user"

    request = Request(
        f"{base_url}/api/chat/message",
        data=json.dumps(
            {
                "user_id": "offline-user",
                "message": "查询贵州茅台 600519.SH 的基础信息和近期行情",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310
        chat = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert chat["session_id"]
    assert "600519.SH" in chat["reply"]
    assert "fixture:" in chat["reply"]
    assert chat["memory_profile"] is None
    assert chat["context_window"]["used_tokens"] > 0

    with urlopen(  # noqa: S310
        f"{base_url}/api/chat/sessions/{chat['session_id']}/messages?user_id=offline-user",
        timeout=10,
    ) as response:
        history = json.loads(response.read().decode("utf-8"))
    assert [item["role"] for item in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["content"] == chat["reply"]

    trace_path = Path(os.environ["OFFLINE_TRACE_PATH"])
    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    roots = [item for item in records if item["record_type"] == "trace"]
    spans = [item for item in records if item["record_type"] == "span"]
    assert [item["status"] for item in roots] == ["started", "ok"]
    assert spans[0]["stage"] == "context"
    assert spans[-1]["stage"] == "termination"
    assert len({item["trace_id"] for item in records}) == 1
    assert len({item["run_id"] for item in records}) == 1
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "查询贵州茅台" not in trace_text
    assert "OPENAI_COMPATIBLE_API_KEY" not in trace_text
    assert "TUSHARE_TOKEN" not in trace_text
