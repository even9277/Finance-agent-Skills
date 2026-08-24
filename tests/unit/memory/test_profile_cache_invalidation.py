"""验证结构化画像权威写与 Redis 派生缓存失效顺序。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.cache import MemoryHotCache  # noqa: E402
from backend.infrastructure.memory.runtime import (  # noqa: E402
    set_memory_cache_for_testing,
)
from backend.services import memory_service  # noqa: E402


class _ProfileCacheSpy:
    """记录画像失效调用，并可模拟非标准缓存实现抛错。"""

    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self._events = events
        self._fail = fail

    async def invalidate_profile(self, user_id: str) -> None:
        assert user_id == "profile-user"
        self._events.append("invalidate")
        if self._fail:
            raise RuntimeError("fixture cache failure")


@pytest.mark.unit
@pytest.mark.parametrize("operation", ("update", "delete", "cold_start"))
def test_profile_authority_success_invalidates_cache_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """画像更新、全删和冷启动都必须在权威调用返回后再失效缓存。"""

    async def scenario() -> None:
        events: list[str] = []

        async def authority(*_args, **_kwargs) -> None:
            events.append("authority")

        if operation == "update":
            monkeypatch.setattr(
                memory_service.MemoryService, "update_profile_and_enqueue", authority
            )
        elif operation == "delete":
            monkeypatch.setattr(memory_service.MemoryService, "delete_all", authority)
        else:
            monkeypatch.setattr(memory_service.MemoryService, "cold_start", authority)
        set_memory_cache_for_testing(
            cast(MemoryHotCache, _ProfileCacheSpy(events))
        )
        try:
            if operation == "update":
                assert await memory_service.update_risk_profile(
                    "profile-user", "balanced"
                )
            elif operation == "delete":
                assert await memory_service.delete_all_memories("profile-user")
            else:
                assert await memory_service.cold_start(
                    "profile-user", {"risk_level": "balanced"}
                )
            assert events == ["authority", "invalidate"]
        finally:
            set_memory_cache_for_testing(None)

    asyncio.run(scenario())


@pytest.mark.unit
def test_profile_authority_failure_does_not_invalidate_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """权威画像调用失败时不得删除仍与数据库一致的缓存。"""

    async def scenario() -> None:
        events: list[str] = []

        async def authority_failure(*_args, **_kwargs) -> None:
            events.append("authority_failed")
            raise RuntimeError("fixture authority failure")

        monkeypatch.setattr(
            memory_service.MemoryService,
            "update_profile_and_enqueue",
            authority_failure,
        )
        set_memory_cache_for_testing(
            cast(MemoryHotCache, _ProfileCacheSpy(events))
        )
        try:
            with pytest.raises(RuntimeError, match="authority failure"):
                await memory_service.update_risk_profile("profile-user", "balanced")
            assert events == ["authority_failed"]
        finally:
            set_memory_cache_for_testing(None)

    asyncio.run(scenario())


@pytest.mark.unit
def test_profile_cache_failure_does_not_reverse_authoritative_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画像已权威写入后，Redis 失效异常只能降级且 API 仍成功。"""

    async def scenario() -> None:
        events: list[str] = []

        async def authority(*_args, **_kwargs) -> None:
            events.append("authority")

        monkeypatch.setattr(
            memory_service.MemoryService, "update_profile_and_enqueue", authority
        )
        set_memory_cache_for_testing(
            cast(MemoryHotCache, _ProfileCacheSpy(events, fail=True))
        )
        try:
            assert await memory_service.update_risk_profile("profile-user", "balanced")
            assert events == ["authority", "invalidate"]
        finally:
            set_memory_cache_for_testing(None)

    asyncio.run(scenario())
