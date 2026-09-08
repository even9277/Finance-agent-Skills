"""验证 D08 Redis 跨实例熔断与不可达时的本地降级。"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import cast

import pytest

redis = pytest.importorskip("redis.asyncio")
ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.infrastructure.chat.tool_runtime import ToolRuntimeConfig  # noqa: E402
from backend.infrastructure.chat.tool_runtime_redis import (  # noqa: E402
    RedisCircuitConfig,
    RedisCircuitStore,
    RedisSharedToolRuntime,
)
from src.conversation.contracts import (  # noqa: E402
    EntityType,
    EvidenceDimension,
    ToolPolicy,
    ToolRuntimeOutcome,
)
from src.conversation.errors import ToolCircuitOpenError  # noqa: E402


def _redis_url() -> str:
    """只允许显式隔离的本地或 Compose Redis。"""
    if os.getenv("RUN_D08_ISOLATED_INFRA_TESTS", "").lower() != "true":
        pytest.skip("需要 RUN_D08_ISOLATED_INFRA_TESTS=true")
    value = os.getenv("TEST_REDIS_URL", "").strip()
    if not value.startswith("redis://redis-e2e:") and not value.startswith(
        "redis://127.0.0.1:"
    ):
        pytest.fail("D08 Redis 测试拒绝未识别的目标")
    return value


def _policy() -> ToolPolicy:
    return ToolPolicy(
        tool_name="get_market_bars",
        evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
        supported_entity_types=(EntityType.STOCK,),
        input_fields=(),
        api_family="tushare-market",
        retryable=True,
        family_max_concurrency=2,
        min_interval_ms=0,
    )


@pytest.mark.integration
def test_real_redis_shares_circuit_and_single_half_open_probe() -> None:
    """两个 Runtime 必须观察同一 Open 状态并只放一个恢复探测。"""

    async def scenario() -> None:
        redis_url = _redis_url()
        namespace = f"finance-d08-{uuid.uuid4().hex}"
        client_a = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
        client_b = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
        config = ToolRuntimeConfig(
            circuit_window_size=2,
            circuit_min_samples=2,
            circuit_failure_rate=0.5,
            circuit_open_ms=50,
        )
        runtime_a = RedisSharedToolRuntime(
            config,
            store=RedisCircuitStore(
                client_a,
                RedisCircuitConfig(namespace=namespace, ttl_sec=20),
                config,
            ),
        )
        runtime_b = RedisSharedToolRuntime(
            config,
            store=RedisCircuitStore(
                client_b,
                RedisCircuitConfig(namespace=namespace, ttl_sec=20),
                config,
            ),
        )
        policy = _policy()
        try:
            for index in range(2):
                lease = await runtime_a.acquire(policy, trace_id=f"trace-fail-{index}")
                await runtime_a.release(lease, ToolRuntimeOutcome.TRANSIENT_FAILURE)
            with pytest.raises(ToolCircuitOpenError):
                await runtime_b.acquire(policy, trace_id="trace-open")

            await asyncio.sleep(0.06)
            probe = await runtime_b.acquire(policy, trace_id="trace-probe")
            with pytest.raises(ToolCircuitOpenError):
                await runtime_a.acquire(policy, trace_id="trace-second-probe")
            await runtime_b.release(probe, ToolRuntimeOutcome.SUCCESS)
            recovered = await runtime_a.acquire(policy, trace_id="trace-recovered")
            await runtime_a.release(recovered, ToolRuntimeOutcome.SUCCESS)

            keys = await client_a.keys(f"{namespace}:*")
            assert keys
            assert all(policy.tool_name not in key for key in keys)
            ttl_values = [await client_a.ttl(key) for key in keys]
            assert all(0 < ttl <= 20 for ttl in ttl_values)
        finally:
            keys = await client_a.keys(f"{namespace}:*")
            if keys:
                await client_a.delete(*keys)
            await runtime_a.close()
            await runtime_b.close()

    asyncio.run(scenario())


@pytest.mark.integration
def test_unreachable_redis_falls_back_to_local_governance() -> None:
    """共享状态不可达时调用仍受本地许可和熔断保护。"""

    async def scenario() -> None:
        client = redis.Redis.from_url(
            "redis://127.0.0.1:1/15",
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=0.05,
            socket_timeout=0.05,
        )
        config = ToolRuntimeConfig()
        runtime = RedisSharedToolRuntime(
            config,
            store=RedisCircuitStore(
                client,
                RedisCircuitConfig(namespace="finance-d08-unreachable", ttl_sec=20),
                config,
            ),
        )
        try:
            lease = await asyncio.wait_for(
                runtime.acquire(_policy(), trace_id="trace-degraded"),
                timeout=1,
            )
            await runtime.release(lease, ToolRuntimeOutcome.SUCCESS)
            health = await runtime.health()
            assert health["status"] == "DEGRADED"
            local = cast(dict[str, object], health["local"])
            metrics = cast(dict[str, int], local["metrics"])
            assert metrics["degraded"] >= 1
        finally:
            await runtime.close()

    asyncio.run(scenario())


@pytest.mark.integration
def test_real_redis_ignores_success_from_a_call_admitted_before_open() -> None:
    """Open 后到达的旧成功结果不得跨周期关闭共享熔断器。"""

    async def scenario() -> None:
        redis_url = _redis_url()
        namespace = f"finance-d08-stale-{uuid.uuid4().hex}"
        client = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
        config = ToolRuntimeConfig(
            circuit_window_size=1,
            circuit_min_samples=1,
            circuit_failure_rate=1.0,
        )
        runtime = RedisSharedToolRuntime(
            config,
            store=RedisCircuitStore(
                client,
                RedisCircuitConfig(namespace=namespace, ttl_sec=20),
                config,
            ),
        )
        policy = _policy()
        try:
            failed_call = await runtime.acquire(policy, trace_id="trace-failed")
            stale_success = await runtime.acquire(policy, trace_id="trace-stale")
            await runtime.release(failed_call, ToolRuntimeOutcome.TRANSIENT_FAILURE)
            await runtime.release(stale_success, ToolRuntimeOutcome.SUCCESS)

            with pytest.raises(ToolCircuitOpenError):
                await runtime.acquire(policy, trace_id="trace-must-stay-open")
        finally:
            keys = await client.keys(f"{namespace}:*")
            if keys:
                await client.delete(*keys)
            await runtime.close()

    asyncio.run(scenario())
