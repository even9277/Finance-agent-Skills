"""实现受控对话工具的进程内限流、退避与三态熔断。"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
from typing import cast

from src.conversation.contracts import (
    CircuitState,
    ToolPolicy,
    ToolRuntimeLease,
    ToolRuntimeOutcome,
)
from src.conversation.errors import ToolCircuitOpenError
from src.conversation.ports import ToolRuntimePort

Monotonic = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]
Jitter = Callable[[float], float]
logger = logging.getLogger(__name__)


def _random_jitter(upper: float) -> float:
    """返回不超过退避比例上限的非负随机抖动。"""
    return random.uniform(0.0, upper)


@dataclass(frozen=True, slots=True)
class ToolRuntimeConfig:
    """定义本地工具治理的熔断窗口和重试退避边界。"""

    circuit_window_size: int = 100
    circuit_min_samples: int = 10
    circuit_failure_rate: float = 0.30
    circuit_open_ms: int = 300_000
    retry_base_delay_ms: int = 200
    retry_max_delay_ms: int = 2_000

    def __post_init__(self) -> None:
        if self.circuit_window_size < 1:
            raise ValueError("circuit_window_size must be positive")
        if not 1 <= self.circuit_min_samples <= self.circuit_window_size:
            raise ValueError("circuit_min_samples must fit the circuit window")
        if not 0 < self.circuit_failure_rate <= 1:
            raise ValueError("circuit_failure_rate must be in (0, 1]")
        if self.circuit_open_ms < 1:
            raise ValueError("circuit_open_ms must be positive")
        if not 1 <= self.retry_base_delay_ms <= self.retry_max_delay_ms:
            raise ValueError("retry delay bounds are invalid")


@dataclass(slots=True)
class _FamilyGate:
    """保存一个 API family 的进程级并发和启动间隔状态。"""

    max_concurrency: int
    semaphore: asyncio.Semaphore = field(init=False)
    interval_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_started_at: float | None = None
    active: int = 0
    max_active: int = 0

    def __post_init__(self) -> None:
        self.semaphore = asyncio.Semaphore(self.max_concurrency)


@dataclass(slots=True)
class _CircuitRecord:
    """保存一个工具的有界瞬时结果窗口与 HalfOpen 探测权。"""

    outcomes: deque[bool]
    state: CircuitState = CircuitState.CLOSED
    opened_at: float | None = None
    probe_in_flight: bool = False


class LocalToolRuntime:
    """在单进程内实施 API family 调度和工具级三态熔断。"""

    def __init__(
        self,
        config: ToolRuntimeConfig,
        *,
        monotonic: Monotonic = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
        jitter: Jitter = _random_jitter,
    ) -> None:
        self._config = config
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter
        self._families: dict[str, _FamilyGate] = {}
        self._circuits: dict[str, _CircuitRecord] = {}
        self._state_lock = asyncio.Lock()
        self._metrics = {
            "admitted": 0,
            "rate_waits": 0,
            "circuit_rejected": 0,
            "circuit_opened": 0,
            "half_open_probes": 0,
        }

    async def acquire(self, policy: ToolPolicy, *, trace_id: str) -> ToolRuntimeLease:
        """取得工具执行许可，并把治理等待计入返回值。

        Args:
            policy: 已冻结到请求权限快照中的工具治理政策。
            trace_id: 当前调用关联标识；仅供上层日志使用，不保存到运行时。

        Returns:
            持有接口族 Semaphore 的许可；调用方必须确定性释放。

        Raises:
            ToolCircuitOpenError: 工具仍在 Open 或已有 HalfOpen 探测。
        """
        del trace_id
        state, probe = await self._reserve_circuit(policy.tool_name)
        gate = self._family_gate(policy)
        started = self._monotonic()
        semaphore_acquired = False
        try:
            await gate.semaphore.acquire()
            semaphore_acquired = True
            async with gate.interval_lock:
                wait_seconds = self._interval_wait(gate, policy.min_interval_ms)
                if wait_seconds > 0:
                    self._metrics["rate_waits"] += 1
                    await self._sleep(wait_seconds)
                gate.last_started_at = self._monotonic()
            gate.active += 1
            gate.max_active = max(gate.max_active, gate.active)
        except BaseException:
            if semaphore_acquired:
                gate.semaphore.release()
            if probe:
                await self._cancel_probe(policy.tool_name)
            raise
        self._metrics["admitted"] += 1
        waited_ms = max(0.0, (self._monotonic() - started) * 1000)
        if waited_ms > 0:
            logger.info(
                "tool_runtime_admitted stage=%s status=%s tool_name=%s "
                "api_family=%s waited_ms=%.2f circuit_state=%s",
                "tool.runtime.admission",
                "SUCCEEDED",
                policy.tool_name,
                policy.api_family,
                waited_ms,
                state.value,
            )
        return ToolRuntimeLease(
            tool_name=policy.tool_name,
            api_family=policy.api_family,
            circuit_state=state,
            waited_ms=waited_ms,
            half_open_probe=probe,
        )

    async def release(
        self,
        lease: ToolRuntimeLease,
        outcome: ToolRuntimeOutcome,
    ) -> None:
        """先提交熔断结果，再释放接口族许可，避免下一调用抢先准入。"""
        gate = self._families[lease.api_family]
        try:
            async with self._state_lock:
                record = self._circuit(lease.tool_name)
                if lease.half_open_probe:
                    if outcome is ToolRuntimeOutcome.TRANSIENT_FAILURE:
                        self._open(record)
                        return
                    if outcome in {
                        ToolRuntimeOutcome.SUCCESS,
                        ToolRuntimeOutcome.PERMANENT_FAILURE,
                    }:
                        record.outcomes.clear()
                        record.state = CircuitState.CLOSED
                        record.opened_at = None
                    record.probe_in_flight = False
                    return

                # Closed 时已放行的迟到结果不得改变新的 Open/HalfOpen 周期。
                if record.state is not CircuitState.CLOSED:
                    return
                if outcome is ToolRuntimeOutcome.SUCCESS:
                    record.outcomes.append(False)
                elif outcome is ToolRuntimeOutcome.TRANSIENT_FAILURE:
                    record.outcomes.append(True)
                    self._open_if_threshold_reached(record)
        finally:
            gate.active = max(0, gate.active - 1)
            gate.semaphore.release()

    def retry_delay_ms(self, *, attempt: int, retry_after_ms: int | None = None) -> int:
        """计算有界指数退避；供应商 Retry-After 同样受总上限保护。"""
        if attempt < 1:
            raise ValueError("attempt must start from one")
        exponential = self._config.retry_base_delay_ms * (2 ** (attempt - 1))
        base = max(exponential, retry_after_ms or 0)
        bounded = min(base, self._config.retry_max_delay_ms)
        jitter = self._jitter(max(0.0, bounded * 0.25))
        return min(self._config.retry_max_delay_ms, int(round(bounded + jitter)))

    async def wait_before_retry(
        self,
        *,
        attempt: int,
        retry_after_ms: int | None = None,
    ) -> int:
        """在总尝试预算内执行一次有界退避。"""
        delay_ms = self.retry_delay_ms(
            attempt=attempt,
            retry_after_ms=retry_after_ms,
        )
        await self._sleep(delay_ms / 1000)
        return delay_ms

    async def health(self) -> dict[str, object]:
        """以异步统一接口返回本地治理健康摘要。"""
        return self.snapshot()

    async def close(self) -> None:
        """本地运行时没有外部资源，保留统一生命周期接口。"""

    def mark_degraded(self) -> None:
        """记录共享状态不可用后退回本地治理。"""
        self._metrics.setdefault("degraded", 0)
        self._metrics["degraded"] += 1

    def circuit_state(self, tool_name: str) -> CircuitState:
        """返回当前进程看到的工具熔断状态，不触发状态转换。"""
        return self._circuit(tool_name).state

    def snapshot(self) -> dict[str, object]:
        """返回不含请求、参数、标的或外部地址的低敏健康摘要。"""
        return {
            "enabled": True,
            "status": "READY",
            "metrics": dict(self._metrics),
            "families": {
                name: {
                    "max_concurrency": gate.max_concurrency,
                    "active": gate.active,
                    "max_active": gate.max_active,
                }
                for name, gate in sorted(self._families.items())
            },
            "circuits": {
                state.value: sum(
                    record.state is state for record in self._circuits.values()
                )
                for state in CircuitState
            },
        }

    async def _reserve_circuit(self, tool_name: str) -> tuple[CircuitState, bool]:
        async with self._state_lock:
            record = self._circuit(tool_name)
            if record.state is CircuitState.OPEN:
                opened_at = record.opened_at
                elapsed_ms = (
                    0.0
                    if opened_at is None
                    else (self._monotonic() - opened_at) * 1000
                )
                if elapsed_ms < self._config.circuit_open_ms:
                    self._metrics["circuit_rejected"] += 1
                    raise ToolCircuitOpenError("tool circuit is open")
                record.state = CircuitState.HALF_OPEN
            if record.state is CircuitState.HALF_OPEN:
                if record.probe_in_flight:
                    self._metrics["circuit_rejected"] += 1
                    raise ToolCircuitOpenError("tool circuit probe is already running")
                record.probe_in_flight = True
                self._metrics["half_open_probes"] += 1
                return CircuitState.HALF_OPEN, True
            return CircuitState.CLOSED, False

    async def _cancel_probe(self, tool_name: str) -> None:
        async with self._state_lock:
            self._circuit(tool_name).probe_in_flight = False

    def _family_gate(self, policy: ToolPolicy) -> _FamilyGate:
        gate = self._families.get(policy.api_family)
        if gate is None:
            gate = _FamilyGate(policy.family_max_concurrency)
            self._families[policy.api_family] = gate
        elif gate.max_concurrency != policy.family_max_concurrency:
            raise ValueError("api family policies must share one concurrency limit")
        return gate

    def _circuit(self, tool_name: str) -> _CircuitRecord:
        record = self._circuits.get(tool_name)
        if record is None:
            record = _CircuitRecord(deque(maxlen=self._config.circuit_window_size))
            self._circuits[tool_name] = record
        return record

    def _interval_wait(self, gate: _FamilyGate, min_interval_ms: int) -> float:
        if gate.last_started_at is None or min_interval_ms <= 0:
            return 0.0
        earliest = gate.last_started_at + (min_interval_ms / 1000)
        return max(0.0, earliest - self._monotonic())

    def _open_if_threshold_reached(self, record: _CircuitRecord) -> None:
        if len(record.outcomes) < self._config.circuit_min_samples:
            return
        if sum(record.outcomes) / len(record.outcomes) >= self._config.circuit_failure_rate:
            self._open(record)

    def _open(self, record: _CircuitRecord) -> None:
        record.state = CircuitState.OPEN
        record.opened_at = self._monotonic()
        record.probe_in_flight = False
        self._metrics["circuit_opened"] += 1


def _config_from_settings() -> ToolRuntimeConfig:
    """从唯一 typed Settings 构建运行时参数，不读取散落环境变量。"""
    from backend.config import settings

    return ToolRuntimeConfig(
        circuit_window_size=settings.tool_circuit_window_size,
        circuit_min_samples=settings.tool_circuit_min_samples,
        circuit_failure_rate=settings.tool_circuit_failure_rate,
        circuit_open_ms=settings.tool_circuit_open_ms,
        retry_base_delay_ms=settings.tool_retry_base_delay_ms,
        retry_max_delay_ms=settings.tool_retry_max_delay_ms,
    )


def create_tool_runtime(*, enable_redis: bool) -> ToolRuntimePort:
    """创建本地运行时或带 Redis 共享熔断的运行时。

    Args:
        enable_redis: 是否装配 Redis 共享熔断状态；本地治理始终启用。

    Returns:
        进程级可复用的工具治理 Port。
    """
    config = _config_from_settings()
    if not enable_redis:
        return LocalToolRuntime(config)

    from redis.asyncio import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    from backend.config import settings

    from .tool_runtime_redis import (
        AsyncRedisClient,
        RedisCircuitConfig,
        RedisCircuitStore,
        RedisSharedToolRuntime,
    )

    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=settings.redis_connect_timeout_sec,
        socket_timeout=settings.redis_socket_timeout_sec,
        max_connections=settings.redis_max_connections,
        retry=Retry(NoBackoff(), 0),
    )
    store = RedisCircuitStore(
        cast(AsyncRedisClient, client),
        RedisCircuitConfig(
            namespace=settings.tool_runtime_redis_namespace,
            ttl_sec=settings.tool_runtime_redis_ttl_sec,
        ),
        config,
    )
    return RedisSharedToolRuntime(config, store=store)


_tool_runtime: ToolRuntimePort | None = None


async def initialize_tool_runtime() -> ToolRuntimePort:
    """按配置初始化进程级治理器；Redis 不可达仍返回本地可用 Runtime。"""
    global _tool_runtime
    from backend.config import settings

    runtime = create_tool_runtime(enable_redis=settings.enable_tool_runtime_redis)
    _tool_runtime = runtime
    health = await runtime.health()
    logger.info(
        "tool_runtime_initialized stage=%s status=%s error_code=%s shared=%s",
        "tool.runtime.bootstrap",
        health["status"],
        health.get("error_code"),
        settings.enable_tool_runtime_redis,
    )
    return runtime


def get_tool_runtime() -> ToolRuntimePort:
    """返回进程级 Runtime；未运行 lifespan 的隔离入口使用本地治理。"""
    global _tool_runtime
    if _tool_runtime is None:
        _tool_runtime = LocalToolRuntime(_config_from_settings())
    return _tool_runtime


async def close_tool_runtime() -> None:
    """确定性关闭共享资源并清空进程级引用。"""
    global _tool_runtime
    runtime = _tool_runtime
    _tool_runtime = None
    if runtime is not None:
        await runtime.close()


def set_tool_runtime_for_testing(runtime: ToolRuntimePort | None) -> None:
    """仅供隔离测试替换进程级治理器。"""
    global _tool_runtime
    _tool_runtime = runtime


__all__ = [
    "LocalToolRuntime",
    "ToolRuntimeConfig",
    "close_tool_runtime",
    "create_tool_runtime",
    "get_tool_runtime",
    "initialize_tool_runtime",
    "set_tool_runtime_for_testing",
]
