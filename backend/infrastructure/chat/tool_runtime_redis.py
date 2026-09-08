"""通过 Redis 原子共享工具熔断状态，并在故障时退回本地治理。"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

from src.conversation.contracts import (
    CircuitState,
    ToolRuntimeLease,
    ToolRuntimeOutcome,
)
from src.conversation.errors import ToolCircuitOpenError

from .tool_runtime import LocalToolRuntime, ToolRuntimeConfig

logger = logging.getLogger(__name__)

_ACQUIRE_SCRIPT = """
local state = redis.call('HGET', KEYS[1], 'state') or 'CLOSED'
local opened_at = tonumber(redis.call('HGET', KEYS[1], 'opened_at') or '0')
local probe = tonumber(redis.call('HGET', KEYS[1], 'probe') or '0')
local now_ms = tonumber(ARGV[1])
local open_ms = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if state == 'OPEN' then
  if now_ms - opened_at < open_ms then
    return {0, 'OPEN'}
  end
  redis.call('HSET', KEYS[1], 'state', 'HALF_OPEN', 'probe', '1')
  redis.call('EXPIRE', KEYS[1], ttl)
  return {1, 'HALF_OPEN'}
end
if state == 'HALF_OPEN' then
  if probe == 1 then
    return {0, 'HALF_OPEN'}
  end
  redis.call('HSET', KEYS[1], 'probe', '1')
  redis.call('EXPIRE', KEYS[1], ttl)
  return {1, 'HALF_OPEN'}
end
redis.call('HSET', KEYS[1], 'state', 'CLOSED', 'probe', '0')
redis.call('EXPIRE', KEYS[1], ttl)
return {1, 'CLOSED'}
"""

_RECORD_SCRIPT = """
local state = redis.call('HGET', KEYS[1], 'state') or 'CLOSED'
local outcome = ARGV[1]
local now_ms = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local min_samples = tonumber(ARGV[4])
local failure_rate = tonumber(ARGV[5])
local ttl = tonumber(ARGV[6])
local half_open_probe = ARGV[7] == '1'
if state == 'OPEN' then
  redis.call('EXPIRE', KEYS[1], ttl)
  return 'OPEN'
end
if state == 'HALF_OPEN' then
  if not half_open_probe then
    redis.call('EXPIRE', KEYS[1], ttl)
    return 'HALF_OPEN'
  end
  if outcome == 'TRANSIENT_FAILURE' then
    redis.call('HSET', KEYS[1], 'state', 'OPEN', 'opened_at', now_ms, 'probe', '0')
    redis.call('EXPIRE', KEYS[1], ttl)
    return 'OPEN'
  end
  if outcome == 'SUCCESS' or outcome == 'PERMANENT_FAILURE' then
    redis.call('DEL', KEYS[2])
    redis.call('HSET', KEYS[1], 'state', 'CLOSED', 'opened_at', '0', 'probe', '0')
    redis.call('EXPIRE', KEYS[1], ttl)
    return 'CLOSED'
  end
  redis.call('HSET', KEYS[1], 'probe', '0')
  redis.call('EXPIRE', KEYS[1], ttl)
  return 'HALF_OPEN'
end
if outcome == 'CANCELLED' or outcome == 'PERMANENT_FAILURE' then
  redis.call('EXPIRE', KEYS[1], ttl)
  return 'CLOSED'
end
if outcome == 'SUCCESS' or outcome == 'TRANSIENT_FAILURE' then
  local failed = outcome == 'TRANSIENT_FAILURE' and '1' or '0'
  redis.call('LPUSH', KEYS[2], failed)
  redis.call('LTRIM', KEYS[2], 0, window - 1)
  redis.call('EXPIRE', KEYS[2], ttl)
  local values = redis.call('LRANGE', KEYS[2], 0, -1)
  if #values >= min_samples then
    local failures = 0
    for _, value in ipairs(values) do
      failures = failures + tonumber(value)
    end
    if failures / #values >= failure_rate then
      redis.call('HSET', KEYS[1], 'state', 'OPEN', 'opened_at', now_ms, 'probe', '0')
      redis.call('EXPIRE', KEYS[1], ttl)
      return 'OPEN'
    end
  end
end
redis.call('HSET', KEYS[1], 'state', 'CLOSED', 'probe', '0')
redis.call('EXPIRE', KEYS[1], ttl)
return 'CLOSED'
"""


class AsyncRedisClient(Protocol):
    """收窄 redis-py 到共享熔断所需的异步命令。"""

    async def eval(self, script: str, numkeys: int, *values: object) -> object: ...

    async def ping(self) -> object: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RedisCircuitConfig:
    """定义共享熔断键空间和派生状态 TTL。"""

    namespace: str
    ttl_sec: int = 600

    def __post_init__(self) -> None:
        normalized = self.namespace.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("tool runtime Redis namespace is invalid")
        if self.ttl_sec < 1:
            raise ValueError("tool runtime Redis ttl must be positive")
        object.__setattr__(self, "namespace", normalized)


@dataclass(frozen=True, slots=True)
class SharedCircuitDecision:
    """表示 Redis 熔断器的一次原子准入结果。"""

    allowed: bool
    state: CircuitState


class RedisCircuitStore:
    """用 Lua 原子维护跨实例工具熔断状态。"""

    def __init__(
        self,
        client: AsyncRedisClient,
        config: RedisCircuitConfig,
        runtime_config: ToolRuntimeConfig,
    ) -> None:
        self._client = client
        self._config = config
        self._runtime_config = runtime_config
        self._metrics = {"acquires": 0, "records": 0, "errors": 0}
        self._last_error_code: str | None = None

    async def acquire(self, tool_name: str, *, now_ms: int) -> SharedCircuitDecision | None:
        """原子检查 Open 窗口并争抢唯一 HalfOpen 探测权。"""
        state_key, _ = self._keys(tool_name)
        try:
            raw = await self._client.eval(
                _ACQUIRE_SCRIPT,
                1,
                state_key,
                now_ms,
                self._runtime_config.circuit_open_ms,
                self._config.ttl_sec,
            )
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                raise ValueError("shared circuit decision is malformed")
            allowed = int(raw[0]) == 1
            state = CircuitState(_text(raw[1]))
        except Exception as exc:
            self._mark_error(exc, "tool.runtime.redis.acquire")
            return None
        self._metrics["acquires"] += 1
        self._last_error_code = None
        return SharedCircuitDecision(allowed=allowed, state=state)

    async def record(
        self,
        tool_name: str,
        outcome: ToolRuntimeOutcome,
        *,
        now_ms: int,
        half_open_probe: bool = False,
    ) -> bool:
        """原子记录有界结果窗口，并拒绝迟到结果跨熔断周期改写状态。"""
        state_key, outcomes_key = self._keys(tool_name)
        try:
            await self._client.eval(
                _RECORD_SCRIPT,
                2,
                state_key,
                outcomes_key,
                outcome.value,
                now_ms,
                self._runtime_config.circuit_window_size,
                self._runtime_config.circuit_min_samples,
                self._runtime_config.circuit_failure_rate,
                self._config.ttl_sec,
                int(half_open_probe),
            )
        except Exception as exc:
            self._mark_error(exc, "tool.runtime.redis.record")
            return False
        self._metrics["records"] += 1
        self._last_error_code = None
        return True

    async def health(self) -> dict[str, object]:
        """返回不含 Redis 地址、键或请求材料的安全健康摘要。"""
        try:
            await self._client.ping()
            status = "READY"
        except Exception as exc:
            self._mark_error(exc, "tool.runtime.redis.health")
            status = "DEGRADED"
        return {
            "enabled": True,
            "status": status,
            "error_code": self._last_error_code,
            "metrics": dict(self._metrics),
        }

    async def close(self) -> None:
        """关闭共享 Redis 连接池。"""
        try:
            await self._client.aclose()
        except Exception as exc:
            self._mark_error(exc, "tool.runtime.redis.close")

    def _keys(self, tool_name: str) -> tuple[str, str]:
        tool_ref = hashlib.sha256(tool_name.encode()).hexdigest()
        prefix = f"{self._config.namespace}:tool-runtime:v1:{tool_ref}"
        return f"{prefix}:state", f"{prefix}:outcomes"

    def _mark_error(self, exc: Exception, stage: str) -> None:
        self._metrics["errors"] += 1
        self._last_error_code = "TOOL_RUNTIME_REDIS_UNAVAILABLE"
        logger.warning(
            "tool_runtime_redis_failed stage=%s status=%s error_code=%s error_type=%s",
            stage,
            "DEGRADED",
            self._last_error_code,
            type(exc).__name__,
        )


class RedisSharedToolRuntime(LocalToolRuntime):
    """优先使用共享熔断状态，Redis 故障时继续本地治理。"""

    def __init__(
        self,
        config: ToolRuntimeConfig,
        *,
        store: RedisCircuitStore,
    ) -> None:
        super().__init__(config)
        self._store = store

    async def _reserve_circuit(self, tool_name: str) -> tuple[CircuitState, bool]:
        decision = await self._store.acquire(tool_name, now_ms=self._wall_now_ms())
        if decision is None:
            self.mark_degraded()
            return await super()._reserve_circuit(tool_name)
        if not decision.allowed:
            raise ToolCircuitOpenError("shared tool circuit is open")
        return decision.state, decision.state is CircuitState.HALF_OPEN

    async def release(
        self,
        lease: ToolRuntimeLease,
        outcome: ToolRuntimeOutcome,
    ) -> None:
        """在释放本地许可前提交共享结果，避免后继调用越过状态更新。"""
        try:
            if not await self._store.record(
                lease.tool_name,
                outcome,
                now_ms=self._wall_now_ms(),
                half_open_probe=lease.half_open_probe,
            ):
                self.mark_degraded()
        finally:
            await super().release(lease, outcome)

    async def health(self) -> dict[str, object]:
        """组合本地与共享状态的低敏健康摘要。"""
        local = self.snapshot()
        shared = await self._store.health()
        return {
            "enabled": True,
            "status": shared["status"],
            "error_code": shared["error_code"],
            "local": local,
            "shared": shared,
        }

    async def close(self) -> None:
        """关闭共享 Redis 连接池。"""
        await self._store.close()

    @staticmethod
    def _wall_now_ms() -> int:
        """为 Redis 多实例状态提供跨进程可比较的 UTC epoch 毫秒。"""
        import time

        return int(time.time() * 1000)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise ValueError("shared circuit state is not text")


__all__ = [
    "RedisCircuitConfig",
    "RedisCircuitStore",
    "RedisSharedToolRuntime",
    "SharedCircuitDecision",
]
