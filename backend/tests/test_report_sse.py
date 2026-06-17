import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.db.models import Report
from backend.routers import report as report_router
from backend.services.auth_service import create_access_token
from backend.services.report.sse_manager import (
    clear_connections,
    connection_count,
    publish_status,
)


class _Request:
    async def is_disconnected(self):
        return False


def _report(user_id: str = "u1") -> Report:
    return Report(
        id="report-1",
        task_id="task-1",
        user_id=user_id,
        status="running",
        progress=50,
    )


class _Result:
    def __init__(self, report: Report | None):
        self._report = report

    def scalar_one_or_none(self):
        return self._report


class _Db:
    def __init__(self, report: Report | None):
        self._report = report

    async def execute(self, stmt):
        return _Result(self._report)


def _token(user_id: str) -> str:
    return create_access_token(account_id=f"acct-{user_id}", username=user_id, user_id=user_id)


def test_sse_generator_should_emit_initial_status_and_cleanup():
    async def run():
        await clear_connections()
        gen = report_router._sse_event_generator(
            "task-1",
            _Request(),
            {"task_id": "task-1", "status": "running", "progress": 50},
        )
        first = await anext(gen)
        count_after_start = await connection_count("task-1")
        await gen.aclose()
        count_after_close = await connection_count("task-1")
        return first, count_after_start, count_after_close

    first, count_after_start, count_after_close = asyncio.run(run())
    assert "event: status" in first
    assert '"progress": 50' in first
    assert count_after_start == 1
    assert count_after_close == 0


def test_sse_generator_should_emit_completed_event():
    async def run():
        await clear_connections()
        gen = report_router._sse_event_generator(
            "task-1",
            _Request(),
            {"task_id": "task-1", "status": "running", "progress": 50},
        )
        await anext(gen)
        await publish_status(
            "task-1",
            {
                "task_id": "task-1",
                "report_id": "report-1",
                "status": "completed",
                "progress": 100,
            },
        )
        completed = await anext(gen)
        await gen.aclose()
        return completed

    completed = asyncio.run(run())
    assert "event: completed" in completed
    assert '"progress": 100' in completed


def test_sse_reconnect_should_send_current_status_first():
    async def run():
        await clear_connections()
        gen = report_router._sse_event_generator(
            "task-1",
            _Request(),
            {
                "task_id": "task-1",
                "status": "running",
                "progress": 50,
                "current_stage": "technical_analyst",
            },
        )
        first = await anext(gen)
        await gen.aclose()
        return first

    first = asyncio.run(run())
    assert "event: status" in first
    assert '"current_stage": "technical_analyst"' in first


def test_report_events_should_reject_missing_token():
    async def run():
        await report_router.report_events("task-1", _Request(), None, _Db(_report()))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 401


def test_report_events_should_reject_other_user():
    async def run():
        await report_router.report_events("task-1", _Request(), _token("u2"), _Db(_report("u1")))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 403


def test_report_events_should_return_streaming_response(monkeypatch):
    async def _initial(task_id: str, report: Report):
        return {"task_id": task_id, "status": "running", "progress": 50, "user_id": report.user_id}

    monkeypatch.setattr(report_router, "_current_status_payload", _initial)

    async def run():
        return await report_router.report_events(
            "task-1",
            _Request(),
            _token("u1"),
            _Db(_report("u1")),
        )

    response = asyncio.run(run())
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
