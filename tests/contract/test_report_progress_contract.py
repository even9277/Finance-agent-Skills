"""锁定 D05 报告进度公共协议、访问控制与 REST 兼容合同。"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.application.report_progress.contracts import (
    ReportProgressNotification,
    ReportStage,
    ReportStageStatus,
    ReportTaskStatus,
    ReportTerminalNotification,
)
from backend.application.report_progress.hub import report_progress_hub
from backend.application.report_progress.snapshot import ReportProgressSnapshot
from backend.db.database import get_db
from backend.middleware.auth import AuthContext, require_auth
from backend.routers import report as report_router

class _ScalarResult:
    """返回单条测试报告的最小 SQLAlchemy Result 替身。"""

    def __init__(self, report: object | None) -> None:
        self._report = report

    def scalar_one_or_none(self) -> object | None:
        """返回预置报告或 ``None``。"""
        return self._report


class _ReportSession:
    """只实现报告查询所需的异步会话接口。"""

    def __init__(self, report: object | None) -> None:
        self._report = report

    async def execute(self, *_args: object, **_kwargs: object) -> _ScalarResult:
        """忽略 SQL 细节并返回预置报告。"""
        return _ScalarResult(self._report)


def _target_module(name: str) -> ModuleType:
    """在测试体内加载目标模块，使缺失实现表现为可审计断言失败。"""
    module_path = name.replace(".", "/") + ".py"
    assert (settings.project_root / module_path).is_file(), f"目标模块尚未实现：{module_path}"
    return importlib.import_module(name)


def _report(**overrides: object) -> SimpleNamespace:
    """构造不含数据库副作用的报告快照。"""
    values: dict[str, object] = {
        "id": "report-d05",
        "task_id": "task-d05",
        "user_id": "user-d05",
        "status": "completed",
        "progress": 100,
        "error_msg": None,
        "content": "# 已完成报告",
        "created_at": datetime(2026, 9, 4, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.contract
def test_report_progress_v1_frames_are_typed_strict_and_redacted() -> None:
    """D05-T01：三类公共帧必须共享完整 envelope 并拒绝额外敏感字段。"""
    contracts = _target_module("backend.application.report_progress.contracts")
    schemas = importlib.import_module("backend.schemas.report")

    assert contracts.REPORT_PROGRESS_PROTOCOL_VERSION == "report-progress-v1"
    assert {stage.value for stage in contracts.ReportStage} == {
        "PREPARING",
        "FUNDAMENTAL_ANALYSIS",
        "TECHNICAL_ANALYSIS",
        "VALUATION_ANALYSIS",
        "NEWS_ANALYSIS",
        "PERSONALIZATION",
        "SYNTHESIZING",
    }
    assert {status.value for status in contracts.ReportStageStatus} == {
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
    }

    common = {
        "protocol_version": "report-progress-v1",
        "task_id": "task-d05",
        "report_id": "report-d05",
        "sequence": 1,
        "emitted_at": datetime(2026, 9, 4, tzinfo=UTC),
    }
    ready = schemas.ReportStreamReadyFrame.model_validate(
        {
            **common,
            "type": "stream_ready",
            "status": "running",
            "progress": 20,
            "stages": [],
        }
    )
    stage = schemas.ReportStageUpdateFrame.model_validate(
        {
            **common,
            "sequence": 2,
            "type": "stage_update",
            "stage": "FUNDAMENTAL_ANALYSIS",
            "stage_status": "SUCCEEDED",
            "progress": 35,
        }
    )
    terminal = schemas.ReportTaskTerminalFrame.model_validate(
        {
            **common,
            "sequence": 3,
            "type": "task_terminal",
            "status": "completed",
            "progress": 100,
            "error_code": None,
            "message": None,
        }
    )

    assert [ready.type, stage.type, terminal.type] == [
        "stream_ready",
        "stage_update",
        "task_terminal",
    ]
    with pytest.raises(ValidationError):
        schemas.ReportStageUpdateFrame.model_validate(
            {
                **stage.model_dump(),
                "authorization": "Bearer MUST_NOT_LEAK",
                "raw_event": {"prompt": "MUST_NOT_LEAK"},
            }
        )


@pytest.mark.contract
def test_completed_report_sse_sends_snapshot_then_terminal_and_closes() -> None:
    """D05-T04：已完成任务必须立即发送首帧、终态并关闭连接。"""
    app = FastAPI()
    app.include_router(report_router.router, prefix="/api/report")
    auth = AuthContext(account_id="account-d05", username="user-d05", user_id="user-d05")

    async def override_auth() -> AuthContext:
        return auth

    async def override_db() -> Any:
        yield cast(AsyncSession, _ReportSession(_report()))

    app.dependency_overrides[require_auth] = override_auth
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.get("/api/report/events/task-d05")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: stream_ready" in response.text
    assert "event: task_terminal" in response.text
    assert response.text.index("event: stream_ready") < response.text.index("event: task_terminal")
    assert "# 已完成报告" not in response.text


@pytest.mark.contract
def test_running_report_stream_consumes_hub_events_with_one_terminal() -> None:
    """D05-T03/T04：活动连接按序消费真实通知并在唯一终态后清理。"""

    async def run_case() -> list[Any]:
        initial = ReportProgressSnapshot(
            task_id="task-running-d05",
            report_id="report-running-d05",
            user_id="user-d05",
            status=ReportTaskStatus.RUNNING,
            progress=20,
            error_code=None,
            message=None,
        )
        received: list[Any] = []

        async def consume() -> None:
            async for event in report_router._report_event_stream(initial):
                received.append(event.data)

        with patch.object(
            report_router,
            "_reload_sse_snapshot",
            new=AsyncMock(return_value=initial),
        ):
            consumer = asyncio.create_task(consume())
            for _ in range(20):
                if report_progress_hub.subscriber_count(initial.task_id) == 1:
                    break
                await asyncio.sleep(0)
            assert report_progress_hub.subscriber_count(initial.task_id) == 1

            report_progress_hub.publish(
                ReportProgressNotification(
                    task_id=initial.task_id,
                    report_id=initial.report_id,
                    stage=ReportStage.FUNDAMENTAL_ANALYSIS,
                    stage_status=ReportStageStatus.SUCCEEDED,
                    progress=35,
                )
            )
            report_progress_hub.publish(
                ReportTerminalNotification(
                    task_id=initial.task_id,
                    report_id=initial.report_id,
                    status=ReportTaskStatus.COMPLETED,
                    progress=100,
                )
            )
            await asyncio.wait_for(consumer, timeout=0.5)
        assert report_progress_hub.subscriber_count(initial.task_id) == 0
        return received

    frames = asyncio.run(run_case())
    assert [frame.type for frame in frames] == [
        "stream_ready",
        "stage_update",
        "task_terminal",
    ]
    assert [frame.sequence for frame in frames] == [1, 2, 3]
    assert [frame.progress for frame in frames] == [20, 35, 100]


@pytest.mark.contract
def test_running_stream_immediately_reconciles_terminal_committed_before_subscription() -> None:
    """D05-T03：首查后、订阅前提交的终态不得等待周期 reconcile。"""

    async def run_case() -> list[Any]:
        initial = ReportProgressSnapshot(
            task_id="task-race-d05",
            report_id="report-race-d05",
            user_id="user-d05",
            status=ReportTaskStatus.RUNNING,
            progress=20,
            error_code=None,
            message=None,
        )
        terminal = ReportProgressSnapshot(
            task_id=initial.task_id,
            report_id=initial.report_id,
            user_id=initial.user_id,
            status=ReportTaskStatus.COMPLETED,
            progress=100,
            error_code=None,
            message=None,
        )
        with patch.object(
            report_router,
            "_reload_sse_snapshot",
            new=AsyncMock(return_value=terminal),
        ):
            return [
                event.data
                async for event in report_router._report_event_stream(initial)
            ]

    frames = asyncio.run(run_case())
    assert [frame.type for frame in frames] == ["stream_ready", "task_terminal"]
    assert [frame.sequence for frame in frames] == [1, 2]
    assert [frame.progress for frame in frames] == [20, 100]


@pytest.mark.contract
def test_report_sse_rejects_query_token_and_hides_task_existence() -> None:
    """D05-T04：query token 无效，非所有者与不存在任务都返回同一 404。"""
    auth = AuthContext(account_id="account-a", username="user-a", user_id="user-a")

    async def override_auth() -> AuthContext:
        return auth

    def request_for(report: object | None) -> tuple[int, dict[str, object]]:
        app = FastAPI()
        app.include_router(report_router.router, prefix="/api/report")

        async def override_db() -> Any:
            yield cast(AsyncSession, _ReportSession(report))

        app.dependency_overrides[require_auth] = override_auth
        app.dependency_overrides[get_db] = override_db
        # 该合同验证启用鉴权后的存在性隐藏，不得继承 Compose 的免鉴权环境。
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(settings, "auth_enabled", True)
            with TestClient(app) as client:
                response = client.get("/api/report/events/task-hidden")
        return response.status_code, response.json()

    missing = request_for(None)
    other_owner = request_for(
        _report(id="report-hidden", task_id="task-hidden", user_id="user-b")
    )
    assert missing == other_owner == (404, {"detail": "任务不存在"})

    app = FastAPI()
    app.include_router(report_router.router, prefix="/api/report")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(settings, "auth_enabled", True)
        with TestClient(app) as client:
            query_only = client.get("/api/report/events/task-hidden?token=must-not-work")
    assert query_only.status_code == 401


@pytest.mark.contract
def test_report_status_keeps_existing_fields_for_completed_tasks() -> None:
    """D05-T07：现有 status 消费者必须继续获得原路径和字段。"""
    auth = AuthContext(account_id="account-d05", username="user-d05", user_id="user-d05")

    async def run_case() -> dict[str, object]:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(settings, "auth_enabled", True)
            response = await report_router.get_report_status(
                "task-d05",
                cast(AsyncSession, _ReportSession(_report())),
                auth,
            )
        return response.model_dump()

    assert asyncio.run(run_case()) == {
        "task_id": "task-d05",
        "status": "completed",
        "progress": 100,
        "report_id": "report-d05",
        "error_msg": None,
        "error_code": None,
    }


@pytest.mark.contract
def test_report_status_projects_safe_failure_without_raw_exception() -> None:
    """D05-T07：失败快照只暴露稳定错误码和安全消息。"""
    auth = AuthContext(account_id="account-d05", username="user-d05", user_id="user-d05")
    raw_error = "provider failed Authorization=Bearer SUPER_SECRET"

    async def run_case() -> dict[str, object]:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(settings, "auth_enabled", True)
            response = await report_router.get_report_status(
                "task-d05",
                cast(
                    AsyncSession,
                    _ReportSession(
                        _report(status="failed", progress=65, content=None, error_msg=raw_error)
                    ),
                ),
                auth,
            )
        return response.model_dump()

    payload = asyncio.run(run_case())
    assert payload["progress"] == 65
    assert payload.get("error_code") == "REPORT_GENERATION_FAILED"
    assert payload["error_msg"] == "报告生成失败，请稍后重试"
    assert raw_error not in str(payload)
