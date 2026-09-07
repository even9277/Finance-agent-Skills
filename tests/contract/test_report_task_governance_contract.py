"""从报告 HTTP 入口锁定 D06 幂等、冲突、隔离与派发合同。"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.db.database import Base, get_db
from backend.db.models import User
from backend.middleware.auth import AuthContext, require_auth
from backend.routers import report as report_router


class _DispatchAudit:
    """线程安全统计真正进入 BackgroundTasks 的报告执行次数。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []

    async def run(self, *, task_id: str, report_id: str, **_: Any) -> None:
        """记录低敏任务标识，不执行模型、工具或报告工作流。"""
        with self._lock:
            self.calls.append((task_id, report_id))


@contextmanager
def _report_client(
    database_url: str,
    *,
    users: tuple[str, ...] = ("user-d06-a", "user-d06-b"),
) -> Iterator[tuple[TestClient, _DispatchAudit]]:
    """构造使用隔离数据库和真实 FastAPI BackgroundTasks 的报告客户端。"""
    # TestClient 与准备/清理各自拥有事件循环，禁用连接池可避免 asyncpg 跨循环复用。
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            for user_id in users:
                if await session.get(User, user_id) is None:
                    session.add(User(id=user_id, display_name="D06 contract fixture"))
            await session.commit()

    asyncio.run(prepare())
    app = FastAPI()
    app.include_router(report_router.router, prefix="/api/report")
    audit = _DispatchAudit()

    async def override_db() -> Any:
        async with session_factory() as session:
            yield session

    async def override_auth(request: Request) -> AuthContext:
        user_id = request.headers.get("X-Test-User", users[0])
        return AuthContext(
            account_id=f"account-{user_id}",
            username=user_id,
            user_id=user_id,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_auth] = override_auth
    try:
        with patch.object(report_router, "run_report_task", new=audit.run):
            with TestClient(app) as client:
                yield client, audit
    finally:
        asyncio.run(engine.dispose())


def _payload(user_id: str, command: str = "分析贵州茅台 600519") -> dict[str, str]:
    """构造只包含公开创建字段的虚拟请求。"""
    return {"user_id": user_id, "command": command}


@pytest.mark.contract
def test_same_explicit_key_replays_and_conflicting_command_is_rejected(tmp_path: Path) -> None:
    """D06-T05：相同键同请求复用，相同键不同请求返回安全 409。"""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'explicit-key.db').as_posix()}"
    headers = {"Idempotency-Key": "request-d06-explicit-0001"}
    with _report_client(url) as (client, audit):
        first = client.post("/api/report/generate", json=_payload("user-d06-a"), headers=headers)
        replay = client.post("/api/report/generate", json=_payload("user-d06-a"), headers=headers)
        conflict = client.post(
            "/api/report/generate",
            json=_payload("user-d06-a", "分析招商银行 600036"),
            headers=headers,
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["idempotency_status"] == "CREATED"
    assert replay.json()["idempotency_status"] == "REPLAYED"
    assert replay.json()["task_id"] == first.json()["task_id"]
    assert replay.json()["report_id"] == first.json()["report_id"]
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert "招商银行" not in conflict.text
    assert len(audit.calls) == 1


@pytest.mark.contract
def test_legacy_client_reuses_normalized_command_for_ten_minute_window(tmp_path: Path) -> None:
    """D06-T05：不传 header 的旧客户端仍按同用户、规范化命令复用。"""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'legacy-key.db').as_posix()}"
    with _report_client(url) as (client, audit):
        first = client.post(
            "/api/report/generate",
            json=_payload("user-d06-a", "分析   贵州茅台\t600519"),
        )
        replay = client.post(
            "/api/report/generate",
            json=_payload("user-d06-a", "  分析 贵州茅台　600519 "),
        )

    assert first.status_code == replay.status_code == 200
    assert replay.json()["task_id"] == first.json()["task_id"]
    assert replay.json()["idempotency_status"] == "REPLAYED"
    assert len(audit.calls) == 1


@pytest.mark.contract
def test_same_key_is_isolated_between_authenticated_users(tmp_path: Path) -> None:
    """D06-T05：相同显式键不能跨用户复用或泄露任务标识。"""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'owner-isolation.db').as_posix()}"
    key = {"Idempotency-Key": "request-d06-shared-0001"}
    with _report_client(url) as (client, audit):
        first = client.post(
            "/api/report/generate",
            json=_payload("user-d06-a"),
            headers={**key, "X-Test-User": "user-d06-a"},
        )
        other = client.post(
            "/api/report/generate",
            json=_payload("user-d06-b"),
            headers={**key, "X-Test-User": "user-d06-b"},
        )

    assert first.status_code == other.status_code == 200
    assert first.json()["task_id"] != other.json()["task_id"]
    assert len(audit.calls) == 2


@pytest.mark.contract
def test_invalid_idempotency_key_is_422_without_echo(tmp_path: Path) -> None:
    """D06-T05：非法 header 在创建前失败，且响应不回显其原值。"""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'invalid-key.db').as_posix()}"
    with _report_client(url) as (client, audit):
        response = client.post(
            "/api/report/generate",
            json=_payload("user-d06-a"),
            headers={"Idempotency-Key": "short"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "INVALID_IDEMPOTENCY_KEY"
    assert "short" not in response.text
    assert audit.calls == []


@pytest.mark.contract
def test_generate_requires_bearer_auth_before_claiming_task() -> None:
    """D06-T05：未认证创建必须返回 401，不能写治理行或回显请求键。"""
    app = FastAPI()
    app.include_router(report_router.router, prefix="/api/report")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(report_router.settings, "auth_enabled", True)
        with TestClient(app) as client:
            response = client.post(
                "/api/report/generate",
                json=_payload("user-d06-a"),
                headers={"Idempotency-Key": "request-d06-private-0001"},
            )

    assert response.status_code == 401
    assert "request-d06-private-0001" not in response.text


def _isolated_postgres_url() -> str:
    """只接受由 D06 隔离 Compose 显式授权的 PostgreSQL URL。"""
    if os.getenv("RUN_D06_ISOLATED_INFRA_TESTS", "").lower() != "true":
        pytest.skip("需要 RUN_D06_ISOLATED_INFRA_TESTS=true 的隔离 Compose")
    value = os.getenv("TEST_DATABASE_URL", "").strip()
    if not value.startswith("postgresql+asyncpg://e2e:"):
        pytest.fail("D06 并发测试拒绝未识别的 PostgreSQL 目标")
    return value


@pytest.mark.contract
@pytest.mark.integration
def test_twenty_concurrent_requests_create_and_dispatch_once() -> None:
    """D06-T02/T05：两实例等价并发必须由数据库收敛为一次派发。"""
    database_url = _isolated_postgres_url()
    user_id = f"d06-{uuid.uuid4().hex}"
    headers = {
        "Idempotency-Key": f"request-d06-{uuid.uuid4().hex}",
        "X-Test-User": user_id,
    }
    with _report_client(database_url, users=(user_id,)) as (client, audit):
        with ThreadPoolExecutor(max_workers=20) as executor:
            responses = list(
                executor.map(
                    lambda _: client.post(
                        "/api/report/generate",
                        json=_payload(user_id),
                        headers=headers,
                    ),
                    range(20),
                )
            )

    assert {response.status_code for response in responses} == {200}
    payloads = [response.json() for response in responses]
    assert len({item["task_id"] for item in payloads}) == 1
    assert len({item["report_id"] for item in payloads}) == 1
    assert [item["idempotency_status"] for item in payloads].count("CREATED") == 1
    assert [item["idempotency_status"] for item in payloads].count("REPLAYED") == 19
    assert len(audit.calls) == 1
