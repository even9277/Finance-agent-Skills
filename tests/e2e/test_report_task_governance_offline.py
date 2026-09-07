"""通过双后端离线栈验证 D06 幂等创建与跨实例恢复。"""

from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _required_url(name: str) -> str:
    """读取仅由隔离 Compose 注入的服务地址，否则跳过本机默认测试。"""
    value = os.getenv(name, "").rstrip("/")
    if not value:
        pytest.skip(f"{name} 未设置；仅在 D06 离线 Compose 中执行")
    return value


def _create_report(base_url: str, idempotency_key: str) -> tuple[dict[str, Any], str]:
    """通过生产形态 Nginx 入口发送一个同键报告创建请求。"""
    request = Request(
        f"{base_url}/api/report/generate",
        data=json.dumps(
            {
                "command": "D06 离线分析贵州茅台 600519",
                "user_id": "offline-report-d06-user",
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        assert response.status == 200
        instance = response.headers.get("X-Offline-Backend-Instance", "")
        return json.loads(response.read().decode("utf-8")), instance


def _initialize_user(base_url: str) -> None:
    """按真实前端顺序先初始化报告用户，避免把用户创建竞争混入 D06 验收。"""
    request = Request(
        f"{base_url}/api/user/init",
        data=json.dumps(
            {
                "user_id": "offline-report-d06-user",
                "display_name": "D06 离线报告用户",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310
        assert response.status == 200
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["user_id"] == "offline-report-d06-user"


def _read_terminal_sse(url: str) -> list[dict[str, Any]]:
    """从指定应用实例读取最新快照并等待唯一终态。"""
    frames: list[dict[str, Any]] = []
    request = Request(url, headers={"Accept": "text/event-stream"})
    with urlopen(request, timeout=180) as response:  # noqa: S310
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/event-stream")
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
            if frame["type"] == "task_terminal":
                return frames
    raise AssertionError("跨实例 SSE 在 task_terminal 前关闭")


def _invocation_count() -> int:
    """读取只含固定计数行的离线工作流 artifact。"""
    path_value = os.getenv("OFFLINE_REPORT_INVOCATION_PATH", "")
    if not path_value:
        pytest.skip("OFFLINE_REPORT_INVOCATION_PATH 未设置")
    path = Path(path_value)
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line == "invoked")


async def _wait_for_running_snapshot(task_id: str) -> dict[str, object]:
    """等待数据库出现非初始持久版本，避免只验证创建快照。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        for _ in range(50):
            async with engine.connect() as connection:
                row = (
                    (
                        await connection.execute(
                            text(
                                """
                                SELECT r.status, r.progress, g.snapshot_version
                                FROM reports r
                                JOIN report_task_governance g ON g.report_id = r.id
                                WHERE r.task_id = :task_id
                                """
                            ),
                            {"task_id": task_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if row is not None and int(row["snapshot_version"]) >= 2:
                return dict(row)
            await asyncio.sleep(0.05)
        raise AssertionError("报告任务未在 2.5 秒内进入持久运行快照")
    finally:
        await engine.dispose()


async def _load_terminal_evidence(task_id: str) -> dict[str, object]:
    """读取唯一 Report/治理行和最终版本，不读取报告正文。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT r.status, r.progress, g.snapshot_version,
                                   (SELECT count(*) FROM reports WHERE task_id = :task_id)
                                     AS report_count,
                                   (SELECT count(*) FROM report_task_governance
                                    WHERE task_id = :task_id) AS governance_count
                            FROM reports r
                            JOIN report_task_governance g ON g.report_id = r.id
                            WHERE r.task_id = :task_id
                            """
                        ),
                        {"task_id": task_id},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)
    finally:
        await engine.dispose()


async def _delete_and_count_report_cache() -> tuple[int, int]:
    """只删除隔离 Redis 中 D06 报告 namespace，并返回删除前后重建计数。"""
    client = Redis.from_url(os.environ["TEST_REPORT_REDIS_URL"], decode_responses=True)
    try:
        keys = [
            key
            async for key in client.scan_iter(match="finance-report-offline-e2e:report:v1:*")
        ]
        if keys:
            await client.delete(*keys)
        assert not [
            key
            async for key in client.scan_iter(match="finance-report-offline-e2e:report:v1:*")
        ]
        return len(keys), 0
    finally:
        await client.aclose()


async def _count_report_cache() -> int:
    """统计隔离 D06 namespace 当前可重建键数量。"""
    client = Redis.from_url(os.environ["TEST_REPORT_REDIS_URL"], decode_responses=True)
    try:
        return len(
            [
                key
                async for key in client.scan_iter(
                    match="finance-report-offline-e2e:report:v1:*"
                )
            ]
        )
    finally:
        await client.aclose()


@pytest.mark.e2e
def test_same_key_runs_once_and_recovers_sse_from_the_other_instance() -> None:
    """D06-T08：20 路代理重放只执行一次，另一实例从数据库恢复到终态。"""
    proxy_url = _required_url("OFFLINE_STACK_BASE_URL")
    primary_url = _required_url("OFFLINE_PRIMARY_BACKEND_URL")
    secondary_url = _required_url("OFFLINE_SECONDARY_BACKEND_URL")
    _initialize_user(proxy_url)
    invocation_before = _invocation_count()
    idempotency_key = "66666666-6666-4666-8666-666666666666"

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(
            executor.map(
                lambda _: _create_report(proxy_url, idempotency_key),
                range(20),
            )
        )

    payloads = [payload for payload, _ in results]
    task_ids = {str(payload["task_id"]) for payload in payloads}
    report_ids = {str(payload["report_id"]) for payload in payloads}
    assert len(task_ids) == 1
    assert len(report_ids) == 1
    assert [payload["idempotency_status"] for payload in payloads].count("CREATED") == 1
    assert [payload["idempotency_status"] for payload in payloads].count("REPLAYED") == 19
    assert {instance for _, instance in results} == {"primary", "secondary"}

    created_index = next(
        index for index, payload in enumerate(payloads) if payload["idempotency_status"] == "CREATED"
    )
    creator_instance = results[created_index][1]
    observer_url = secondary_url if creator_instance == "primary" else primary_url
    task_id = task_ids.pop()
    running = asyncio.run(_wait_for_running_snapshot(task_id))
    assert running["status"] in {"running", "completed"}
    deleted_count, remaining_count = asyncio.run(_delete_and_count_report_cache())
    assert deleted_count >= 1
    assert remaining_count == 0

    frames = _read_terminal_sse(f"{observer_url}/api/report/events/{task_id}")

    assert frames[0]["type"] == "stream_ready"
    assert frames[-1]["type"] == "task_terminal"
    assert frames[-1]["status"] == "completed"
    sequences = [int(frame["sequence"]) for frame in frames]
    assert sequences == sorted(set(sequences))
    terminal = asyncio.run(_load_terminal_evidence(task_id))
    assert terminal["status"] == "completed"
    assert terminal["progress"] == 100
    assert terminal["report_count"] == 1
    assert terminal["governance_count"] == 1
    snapshot_version = terminal["snapshot_version"]
    assert isinstance(snapshot_version, int)
    assert snapshot_version in {sequences[-1], sequences[-1] - 1}
    assert _invocation_count() - invocation_before == 1
    assert asyncio.run(_count_report_cache()) >= 1
