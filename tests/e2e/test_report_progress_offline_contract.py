"""从前端/Nginx 入口锁定 D05 离线报告 SSE 完整旅程。"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


def _base_url() -> str:
    """读取 Compose 注入的前端入口；本机默认测试不启动服务。"""
    value = os.getenv("OFFLINE_STACK_BASE_URL", "").rstrip("/")
    if not value:
        pytest.skip("需要由 docker-compose.offline.yml 注入 OFFLINE_STACK_BASE_URL")
    return value


def _json_request(url: str, *, payload: dict[str, object] | None = None) -> dict[str, Any]:
    """发送离线 HTTP JSON 请求并返回对象响应。"""
    request = Request(
        url,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise AssertionError(f"HTTP {exc.code}: {body}") from exc


def _read_terminal_sse(url: str) -> tuple[list[dict[str, Any]], float]:
    """读取到任务终态并返回业务帧及首帧耗时。"""
    started_at = time.perf_counter()
    frames: list[dict[str, Any]] = []
    request = Request(url, headers={"Accept": "text/event-stream"})
    with urlopen(request, timeout=180) as response:  # noqa: S310
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/event-stream")
        first_frame_seconds: float | None = None
        data_lines: list[str] = []
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
                continue
            if line or not data_lines:
                continue
            frame = json.loads("\n".join(data_lines))
            data_lines.clear()
            frames.append(frame)
            if first_frame_seconds is None:
                first_frame_seconds = time.perf_counter() - started_at
            if frame["type"] == "task_terminal":
                return frames, first_frame_seconds
    raise AssertionError("SSE 在 task_terminal 前关闭")


@pytest.mark.e2e
def test_offline_proxy_streams_real_report_stages_and_persists_terminal_report() -> None:
    """D05-T08：真 Nginx/FastAPI/PostgreSQL 使用 fake Provider 完成报告主链。"""
    base_url = _base_url()

    # 探针必须先证明 endpoint 已注册，避免 M1 阶段误触发旧真实报告工作流。
    try:
        _json_request(f"{base_url}/api/report/events/d05-contract-probe")
    except AssertionError as exc:
        assert '"detail":"任务不存在"' in str(exc), str(exc)

    created = _json_request(
        f"{base_url}/api/report/generate",
        payload={"command": "离线分析茅台 600519", "user_id": "offline-report-user"},
    )
    frames, first_frame_seconds = _read_terminal_sse(
        f"{base_url}/api/report/events/{created['task_id']}"
    )

    assert first_frame_seconds < 5
    assert frames[0]["type"] == "stream_ready"
    assert frames[-1]["type"] == "task_terminal"
    assert frames[-1]["status"] == "completed"
    assert [frame["sequence"] for frame in frames] == list(range(1, len(frames) + 1))
    progress = [int(frame["progress"]) for frame in frames]
    assert progress == sorted(progress)
    stages = {
        frame["stage"]
        for frame in frames
        if frame["type"] == "stage_update" and frame["stage_status"] == "SUCCEEDED"
    }
    stages.update(
        stage["stage"]
        for frame in frames
        if frame["type"] == "stream_ready"
        for stage in frame["stages"]
        if stage["status"] == "SUCCEEDED"
    )
    assert {
        "PREPARING",
        "FUNDAMENTAL_ANALYSIS",
        "TECHNICAL_ANALYSIS",
        "VALUATION_ANALYSIS",
        "NEWS_ANALYSIS",
        "SYNTHESIZING",
    }.issubset(stages)
    serialized = json.dumps(frames, ensure_ascii=False).lower()
    assert "authorization" not in serialized
    assert "api_key" not in serialized
    assert "# 离线报告" not in serialized

    report = _json_request(f"{base_url}/api/report/{created['report_id']}")
    assert report["status"] == "completed"
    assert report["progress"] == 100
    assert report["content"]
