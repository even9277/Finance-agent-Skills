"""
Redis 分布式锁薄封装（基于 redis-py Lock）。
"""

from __future__ import annotations

from typing import Any, Optional


class RedisLockHandle:
    """async context manager，封装 redis-py Lock 的 acquire/release。"""

    def __init__(self, lock: Any) -> None:
        self._lock = lock
        self.acquired = False

    async def __aenter__(self) -> "RedisLockHandle":
        self.acquired = await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.acquired:
            await self._lock.release()


class NoOpLockHandle:
    """Redis 不可用时的占位锁：不阻塞，不真正加锁。"""

    async def __aenter__(self) -> "NoOpLockHandle":
        self.acquired = False
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def create_lock(
    client: Any,
    lock_key: str,
    ttl_ms: int,
    *,
    blocking_timeout_ms: Optional[int] = None,
) -> RedisLockHandle | NoOpLockHandle:
    if client is None:
        return NoOpLockHandle()
    timeout_sec = max(ttl_ms / 1000.0, 0.001)
    blocking_sec = (
        blocking_timeout_ms / 1000.0
        if blocking_timeout_ms is not None
        else timeout_sec
    )
    lock = client.lock(
        lock_key,
        timeout=timeout_sec,
        blocking_timeout=blocking_sec,
    )
    return RedisLockHandle(lock)
