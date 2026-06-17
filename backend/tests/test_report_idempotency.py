import asyncio

from fastapi import BackgroundTasks
import pytest
from backend.db.models import Report, User
from backend.integrations.redis.key_builder import KeyBuilder
from backend.middleware.auth import AuthContext
from backend.routers import report as report_router
from backend.schemas.report import ReportGenerateRequest
from backend.tests.test_redis_cache_service import _build_service


class _ReportStore:
    def __init__(self) -> None:
        self.reports: list[Report] = []

    def session(self):
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, store: _ReportStore) -> None:
        self.store = store

    def add(self, obj):
        if isinstance(obj, Report):
            self.store.reports.append(obj)

    async def commit(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def _generate(store: _ReportStore, command: str, user_id: str = "u1"):
    auth = AuthContext(account_id=f"acct-{user_id}", username=user_id, user_id=user_id)
    async with store.session() as db:
        return await report_router.generate_report(
            ReportGenerateRequest(command=command, user_id=user_id),
            BackgroundTasks(),
            db,
            auth,
        )


def _report_count(store: _ReportStore, user_id: str = "u1") -> int:
    return len([item for item in store.reports if item.user_id == user_id])


def _patch_ensure_user(monkeypatch):
    async def _noop(db, user_id: str):
        return User(id=user_id)

    monkeypatch.setattr(report_router, "_ensure_user", _noop)


def test_idempotency_hit_should_reuse_existing_task(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)
    _patch_ensure_user(monkeypatch)

    async def run():
        store = _ReportStore()
        first = await _generate(store, "帮我分析茅台")
        second = await _generate(store, "帮我分析茅台")
        return first, second, _report_count(store)

    first, second, count = asyncio.run(run())
    assert second.task_id == first.task_id
    assert second.report_id == first.report_id
    assert count == 1


def test_idempotency_miss_should_create_new_task(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)
    _patch_ensure_user(monkeypatch)

    async def run():
        store = _ReportStore()
        first = await _generate(store, "分析茅台")
        second = await _generate(store, "分析腾讯")
        return first, second, _report_count(store)

    first, second, count = asyncio.run(run())
    assert second.task_id != first.task_id
    assert count == 2


def test_idempotency_concurrent_should_create_only_one_report(monkeypatch):
    svc, _, _, _ = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)
    _patch_ensure_user(monkeypatch)

    async def run():
        store = _ReportStore()
        results = await asyncio.gather(
            *[_generate(store, "帮我生成一份贵州茅台的简要投研报告") for _ in range(10)]
        )
        return results, _report_count(store)

    results, count = asyncio.run(run())
    assert len({item.task_id for item in results}) == 1
    assert count == 1


def test_idempotency_expires_should_allow_new_task(
    monkeypatch,
):
    from backend.services.report import idempotency

    svc, _, _, _ = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)
    monkeypatch.setattr(idempotency, "REPORT_IDEMPOTENCY_TTL_SECONDS", 1)
    _patch_ensure_user(monkeypatch)

    async def run():
        store = _ReportStore()
        first = await _generate(store, "分析茅台")
        await asyncio.sleep(2.2)
        second = await _generate(store, "分析茅台")
        return first, second, _report_count(store)

    first, second, count = asyncio.run(run())
    assert second.task_id != first.task_id
    assert count == 2


def test_idempotency_redis_write_failure_should_not_block_db(monkeypatch):
    class BrokenCache:
        key_builder = KeyBuilder("test")

        async def set_if_absent(self, *args, **kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(report_router, "get_cache_service", lambda: BrokenCache())
    _patch_ensure_user(monkeypatch)

    async def run():
        store = _ReportStore()
        response = await _generate(store, "分析茅台")
        return response, _report_count(store)

    response, count = asyncio.run(run())
    assert response.task_id
    assert count == 1


def test_generate_without_redis_should_create_task(monkeypatch):
    monkeypatch.setattr(report_router, "get_cache_service", lambda: None)
    _patch_ensure_user(monkeypatch)

    async def run():
        store = _ReportStore()
        response = await _generate(store, "分析茅台")
        return response, _report_count(store)

    response, count = asyncio.run(run())
    assert response.status == "pending"
    assert count == 1


def test_db_failure_should_release_idempotency_slot(monkeypatch):
    svc, _, _, fake = _build_service()
    monkeypatch.setattr(report_router, "get_cache_service", lambda: svc)

    class _ScalarResult:
        def scalar_one_or_none(self):
            return User(id="u1")

    class _FailingCommitSession:
        async def execute(self, stmt):
            return _ScalarResult()

        def add(self, obj):
            self.obj = obj

        async def commit(self):
            raise RuntimeError("db down")

    auth = AuthContext(account_id="acct-u1", username="u1", user_id="u1")
    async def run():
        with pytest.raises(RuntimeError):
            await report_router.generate_report(
                ReportGenerateRequest(command="分析茅台", user_id="u1"),
                BackgroundTasks(),
                _FailingCommitSession(),
                auth,
            )

    asyncio.run(run())

    assert fake.store == {}
