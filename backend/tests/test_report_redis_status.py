import asyncio

import pytest
from fastapi import HTTPException

from backend.db.models import Report
from backend.middleware.auth import AuthContext
from backend.routers import report as report_router
from backend.services.report import workflow_runner
from backend.tests.test_redis_cache_service import _build_service


def _report(
    *,
    status: str = "running",
    progress: int = 35,
    content: str | None = None,
) -> Report:
    return Report(
        id="report-1",
        task_id="task-1",
        user_id="u1",
        status=status,
        progress=progress,
        content=content,
    )


def test_sync_status_to_redis_should_write_lightweight_snapshot(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(workflow_runner, "get_cache_service", lambda: svc)

    async def run():
        await workflow_runner._sync_status_to_redis(
            _report(),
            current_stage="fundamental_analyst",
            current_stage_label="基本面分析中",
        )
        key = svc.key_builder.report_status("task-1")
        envelope, _ = await svc.get(key)
        return envelope

    envelope = asyncio.run(run())
    assert envelope is not None
    assert envelope.data["task_id"] == "task-1"
    assert envelope.data["user_id"] == "u1"
    assert envelope.data["progress"] == 35
    assert envelope.data["current_stage_label"] == "基本面分析中"
    assert "content" not in envelope.data


def test_sync_status_to_redis_completion_should_not_store_content(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(workflow_runner, "get_cache_service", lambda: svc)

    async def run():
        await workflow_runner._sync_status_to_redis(
            _report(status="completed", progress=100, content="完整报告正文"),
            current_stage="completed",
            current_stage_label="生成完成",
        )
        envelope, _ = await svc.get(svc.key_builder.report_status("task-1"))
        return envelope

    envelope = asyncio.run(run())
    assert envelope is not None
    assert envelope.data["status"] == "completed"
    assert envelope.data["report_id"] == "report-1"
    assert "content" not in envelope.data


def test_sync_status_to_redis_failure_should_not_raise(monkeypatch):
    class BrokenCache:
        key_builder = _build_service()[0].key_builder

        async def set(self, *args, **kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(workflow_runner, "get_cache_service", lambda: BrokenCache())
    asyncio.run(workflow_runner._sync_status_to_redis(_report()))


def test_get_report_status_should_return_redis_snapshot_without_db(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)

    class _DbShouldNotBeUsed:
        async def execute(self, stmt):
            raise AssertionError("DB should not be queried on Redis hit")

    async def run():
        await svc.set(
            svc.key_builder.report_status("task-1"),
            {
                "task_id": "task-1",
                "report_id": "report-1",
                "user_id": "u1",
                "status": "running",
                "progress": 50,
                "current_stage": "technical_analyst",
                "current_stage_label": "技术面分析中",
                "error_msg": None,
                "updated_at": "2026-06-16T00:00:00",
            },
            ttl_seconds=600,
            source="test",
        )
        return await report_router.get_report_status(
            "task-1",
            _DbShouldNotBeUsed(),
            AuthContext(account_id="a", username="u1", user_id="u1"),
        )

    response = asyncio.run(run())
    assert response.progress == 50
    assert response.current_stage_label == "技术面分析中"
    assert response.report_id is None


def test_get_report_status_should_reject_other_user_from_redis(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)

    class _DbShouldNotBeUsed:
        async def execute(self, stmt):
            raise AssertionError("DB should not be queried on Redis hit")

    async def run():
        await svc.set(
            svc.key_builder.report_status("task-1"),
            {
                "task_id": "task-1",
                "report_id": "report-1",
                "user_id": "u1",
                "status": "running",
                "progress": 50,
            },
            ttl_seconds=600,
            source="test",
        )
        return await report_router.get_report_status(
            "task-1",
            _DbShouldNotBeUsed(),
            AuthContext(account_id="a", username="u2", user_id="u2"),
        )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 403


def test_get_report_status_without_redis_should_read_db(monkeypatch):
    monkeypatch.setattr(report_router, "get_cache_service", lambda: None)

    class _Result:
        def scalar_one_or_none(self):
            return _report(status="completed", progress=100)

    class _Db:
        async def execute(self, stmt):
            return _Result()

    response = asyncio.run(
        report_router.get_report_status(
            "task-1",
            _Db(),
            AuthContext(account_id="a", username="u1", user_id="u1"),
        )
    )

    assert response.status == "completed"
    assert response.report_id == "report-1"
    assert response.current_stage_label is None
