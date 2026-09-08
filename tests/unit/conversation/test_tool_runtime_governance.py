"""锁定 D08 工具接口族调度、退避和三态熔断合同。"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.infrastructure.chat.tool_runtime import (  # noqa: E402
    LocalToolRuntime,
    ToolRuntimeConfig,
)
from src.conversation.contracts import (  # noqa: E402
    CircuitState,
    ConversationRunContext,
    Entity,
    EntityType,
    ErrorCode,
    EvidenceDimension,
    EvidenceFact,
    ToolArgumentKind,
    ToolInputSpec,
    ToolObservation,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
    ToolPolicy,
    ToolRuntimeOutcome,
    ValidatedToolPlan,
)
from src.conversation.errors import ToolCircuitOpenError, ToolRateLimitError  # noqa: E402
from src.conversation.execution import ControlledExecutor  # noqa: E402
from src.conversation.tool_governance import ToolGovernanceCatalog  # noqa: E402


class _ManualClock:
    """用可控单调时钟消除限流和熔断测试中的真实等待。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _policy(
    tool_name: str = "get_market_bars",
    *,
    api_family: str = "tushare-market",
    family_max_concurrency: int = 1,
    min_interval_ms: int = 100,
) -> ToolPolicy:
    return ToolPolicy(
        tool_name=tool_name,
        evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
        supported_entity_types=(EntityType.STOCK,),
        input_fields=(ToolInputSpec(name="symbol", kind=ToolArgumentKind.STRING),),
        api_family=api_family,
        retryable=True,
        family_max_concurrency=family_max_concurrency,
        min_interval_ms=min_interval_ms,
    )


def _single_step_plan(policy: ToolPolicy) -> ValidatedToolPlan:
    """构造只包含一个已授权行情步骤的最小执行合同。"""
    entity = Entity(symbol="600519.SH", name="贵州茅台", entity_type=EntityType.STOCK)
    step = ToolPlanStep(
        step_id="s1",
        tool_name=policy.tool_name,
        symbol=entity.symbol,
        evidence_dimension=policy.evidence_dimension,
        required=True,
        idempotency_key="market:600519.SH",
    )
    permissions = ToolPermissionSnapshot.create(
        permissions=(policy,),
        source="d08-test",
        version="d08-test-v1",
    )
    return ValidatedToolPlan(
        plan=ToolPlan(
            plan_id="plan-d08",
            entity=entity,
            steps=(step,),
            requirements=(),
        ),
        permissions=permissions,
        execution_layers=((step.step_id,),),
    )


class _RateLimitedOnceTool:
    """首次返回带 Retry-After 的限流，第二次返回有效证据。"""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, call):
        self.calls += 1
        if self.calls == 1:
            raise ToolRateLimitError("private provider response", retry_after_ms=500)
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=(EvidenceFact(key="close", value="1500"),),
            source="fixture:d08",
            observed_at=date(2026, 9, 8),
            attempts=1,
        )


@pytest.mark.unit
def test_catalog_splits_provider_capabilities_into_stable_api_families() -> None:
    """行情、财务、基金、指数板块和网页不得继续共享一个粗粒度族。"""
    catalog = ToolGovernanceCatalog.default()

    assert catalog.require("get_market_bars").api_family == "tushare-market"
    assert catalog.require("get_income").api_family == "tushare-financial"
    assert catalog.require("get_fund_nav").api_family == "tushare-fund"
    assert catalog.require("get_index_bars").api_family == "tushare-index-sector"
    assert catalog.require("search_web_news").api_family == "web-search-read"
    assert all(policy.family_max_concurrency >= 1 for policy in catalog.policies)
    assert all(policy.min_interval_ms >= 0 for policy in catalog.policies)


@pytest.mark.unit
def test_local_runtime_enforces_family_limit_and_minimum_start_interval() -> None:
    """同族调用必须先拿并发许可，并按单调时钟留出最小启动间隔。"""

    async def scenario() -> None:
        clock = _ManualClock()
        runtime = LocalToolRuntime(
            ToolRuntimeConfig(),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            jitter=lambda _upper: 0.0,
        )
        policy = _policy()

        first = await runtime.acquire(policy, trace_id="trace-1")
        await runtime.release(first, ToolRuntimeOutcome.SUCCESS)
        second = await runtime.acquire(policy, trace_id="trace-2")
        await runtime.release(second, ToolRuntimeOutcome.SUCCESS)

        assert second.waited_ms == pytest.approx(100.0)
        assert clock.sleeps == [pytest.approx(0.1)]
        families = cast(dict[str, dict[str, object]], runtime.snapshot()["families"])
        assert families["tushare-market"]["max_active"] == 1

    asyncio.run(scenario())


@pytest.mark.unit
def test_local_runtime_opens_half_opens_and_closes_per_tool_circuit() -> None:
    """达到失败阈值后快速失败，恢复期只放探测且成功后关闭。"""

    async def scenario() -> None:
        clock = _ManualClock()
        runtime = LocalToolRuntime(
            ToolRuntimeConfig(
                circuit_window_size=2,
                circuit_min_samples=2,
                circuit_failure_rate=0.5,
                circuit_open_ms=500,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            jitter=lambda _upper: 0.0,
        )
        policy = _policy(min_interval_ms=0)

        failed = await runtime.acquire(policy, trace_id="trace-fail-1")
        await runtime.release(failed, ToolRuntimeOutcome.TRANSIENT_FAILURE)
        failed = await runtime.acquire(policy, trace_id="trace-fail-2")
        await runtime.release(failed, ToolRuntimeOutcome.TRANSIENT_FAILURE)

        assert runtime.circuit_state(policy.tool_name) is CircuitState.OPEN
        with pytest.raises(ToolCircuitOpenError):
            await runtime.acquire(policy, trace_id="trace-open")

        clock.advance(0.5)
        probe = await runtime.acquire(policy, trace_id="trace-probe")
        assert probe.circuit_state is CircuitState.HALF_OPEN
        with pytest.raises(ToolCircuitOpenError):
            await runtime.acquire(policy, trace_id="trace-second-probe")
        await runtime.release(probe, ToolRuntimeOutcome.SUCCESS)

        assert runtime.circuit_state(policy.tool_name) is CircuitState.CLOSED

    asyncio.run(scenario())


@pytest.mark.unit
def test_local_runtime_ignores_stale_success_after_circuit_opens() -> None:
    """同批已放行调用的迟到成功不得关闭新开启的熔断周期。"""

    async def scenario() -> None:
        runtime = LocalToolRuntime(
            ToolRuntimeConfig(
                circuit_window_size=1,
                circuit_min_samples=1,
                circuit_failure_rate=1.0,
            )
        )
        policy = _policy(family_max_concurrency=2, min_interval_ms=0)
        failed_call = await runtime.acquire(policy, trace_id="trace-failed")
        stale_success = await runtime.acquire(policy, trace_id="trace-stale")

        await runtime.release(failed_call, ToolRuntimeOutcome.TRANSIENT_FAILURE)
        await runtime.release(stale_success, ToolRuntimeOutcome.SUCCESS)

        assert runtime.circuit_state(policy.tool_name) is CircuitState.OPEN
        with pytest.raises(ToolCircuitOpenError):
            await runtime.acquire(policy, trace_id="trace-must-stay-open")

    asyncio.run(scenario())


@pytest.mark.unit
def test_permanent_failures_do_not_poison_circuit_and_retry_delay_is_bounded() -> None:
    """调用方错误不进入瞬时失败率，退避与 Retry-After 均受上限约束。"""

    async def scenario() -> None:
        clock = _ManualClock()
        runtime = LocalToolRuntime(
            ToolRuntimeConfig(
                circuit_window_size=2,
                circuit_min_samples=2,
                circuit_failure_rate=0.5,
                retry_base_delay_ms=100,
                retry_max_delay_ms=600,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            jitter=lambda _upper: 0.0,
        )
        policy = _policy(min_interval_ms=0)

        lease = await runtime.acquire(policy, trace_id="trace-permanent")
        await runtime.release(lease, ToolRuntimeOutcome.PERMANENT_FAILURE)
        assert runtime.circuit_state(policy.tool_name) is CircuitState.CLOSED
        assert runtime.retry_delay_ms(attempt=1) == 100
        assert runtime.retry_delay_ms(attempt=4) == 600
        assert runtime.retry_delay_ms(attempt=1, retry_after_ms=5_000) == 600

    asyncio.run(scenario())


@pytest.mark.unit
def test_runtime_snapshot_contains_only_low_cardinality_governance_fields() -> None:
    """健康摘要不得包含 trace、参数、标的或 Redis 地址。"""
    runtime = LocalToolRuntime(ToolRuntimeConfig())
    snapshot = runtime.snapshot()

    assert snapshot["status"] == "READY"
    metrics = cast(dict[str, int], snapshot["metrics"])
    assert metrics["admitted"] == 0
    serialized = repr(snapshot).lower()
    for forbidden in ("trace_id", "symbol", "arguments", "redis://"):
        assert forbidden not in serialized
    assert ErrorCode.TOOL_RATE_LIMITED.value == "TOOL_RATE_LIMITED"
    assert ErrorCode.TOOL_CIRCUIT_OPEN.value == "TOOL_CIRCUIT_OPEN"


@pytest.mark.unit
def test_executor_uses_runtime_retry_after_without_leaking_provider_error() -> None:
    """Executor 必须经 Runtime 退避后重试，并只返回稳定结果合同。"""

    async def scenario() -> None:
        clock = _ManualClock()
        runtime = LocalToolRuntime(
            ToolRuntimeConfig(retry_base_delay_ms=100, retry_max_delay_ms=600),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            jitter=lambda _upper: 0.0,
        )
        policy = _policy(min_interval_ms=0)
        tool = _RateLimitedOnceTool()
        result = await ControlledExecutor(tool, runtime=runtime).execute(
            _single_step_plan(policy),
            ConversationRunContext(
                trace_id="trace-d08-retry",
                run_id="run-d08-retry",
                session_id="session-d08",
                request_id="request-d08",
                turn_index=1,
            ),
        )

        assert tool.calls == 2
        assert result.tool_call_count == 2
        assert result.observations[0].attempts == 2
        assert result.observations[0].error_code is None
        assert clock.sleeps == [pytest.approx(0.5)]
        assert "private provider response" not in repr(result)

    asyncio.run(scenario())


@pytest.mark.unit
def test_executor_fast_fails_open_circuit_without_provider_call() -> None:
    """Open 熔断器必须在 Provider STARTED 前拒绝且不计真实调用。"""

    async def scenario() -> None:
        runtime = LocalToolRuntime(
            ToolRuntimeConfig(
                circuit_window_size=1,
                circuit_min_samples=1,
                circuit_failure_rate=1.0,
            )
        )
        policy = _policy(min_interval_ms=0)
        lease = await runtime.acquire(policy, trace_id="trace-prime-open")
        await runtime.release(lease, ToolRuntimeOutcome.TRANSIENT_FAILURE)
        tool = _RateLimitedOnceTool()

        result = await ControlledExecutor(tool, runtime=runtime).execute(
            _single_step_plan(policy),
            ConversationRunContext(
                trace_id="trace-d08-open",
                run_id="run-d08-open",
                session_id="session-d08",
                request_id="request-d08-open",
                turn_index=1,
            ),
        )

        assert tool.calls == 0
        assert result.tool_call_count == 0
        assert result.observations[0].error_code is ErrorCode.TOOL_CIRCUIT_OPEN

    asyncio.run(scenario())
