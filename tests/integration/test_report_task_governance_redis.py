"""锁定 D06 报告快照 Redis 镜像、校验、故障与通知合同。"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

redis = pytest.importorskip("redis.asyncio")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _module(name: str) -> ModuleType:
    """加载目标模块并把尚未实现转换为清晰契约失败。"""
    path = PROJECT_ROOT / (name.replace(".", "/") + ".py")
    assert path.is_file(), f"D06 Redis 合同尚未实现：{path.relative_to(PROJECT_ROOT)}"
    return importlib.import_module(name)


def _redis_url() -> str:
    """只允许显式隔离的 Redis 集成环境。"""
    if os.getenv("RUN_D06_ISOLATED_INFRA_TESTS", "").lower() != "true":
        pytest.skip("需要 RUN_D06_ISOLATED_INFRA_TESTS=true 的隔离 Compose")
    value = os.getenv("TEST_REDIS_URL", "").strip()
    if not value.startswith("redis://redis-e2e:") and not value.startswith(
        "redis://127.0.0.1:"
    ):
        pytest.fail("D06 Redis 测试拒绝未识别的目标")
    return value


def _snapshot(contracts: ModuleType, *, version: int = 7) -> Any:
    """构造不含命令、用户身份或报告正文的快照。"""
    return contracts.ReportTaskSnapshot(
        task_id="task-d06-cache",
        report_id="report-d06-cache",
        snapshot_version=version,
        status="running",
        progress=65,
        stages=(
            contracts.ReportStageSnapshot(
                stage="FUNDAMENTAL_ANALYSIS",
                status="SUCCEEDED",
            ),
        ),
        updated_at=datetime(2026, 9, 5, tzinfo=UTC),
        error_code=None,
        message=None,
    )


@pytest.mark.integration
def test_report_redis_adapter_contract_is_explicit_before_real_service() -> None:
    """D06-T03：报告 Redis 有独立 typed adapter，不反向依赖 Memory 业务。"""
    module = _module("backend.infrastructure.report_tasks.redis_store")

    assert hasattr(module, "RedisReportTaskSnapshotStore")
    assert hasattr(module, "ReportTaskRedisConfig")
    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "backend.infrastructure.memory" not in source
    assert "os.getenv" not in source


@pytest.mark.integration
def test_real_redis_snapshot_ttl_redaction_corruption_and_pubsub() -> None:
    """D06-T03/T06：真 Redis 只保存安全快照，损坏回源，通知可跨实例。"""

    async def scenario() -> None:
        redis_url = _redis_url()
        contracts = _module("backend.application.report_tasks.contracts")
        adapter = _module("backend.infrastructure.report_tasks.redis_store")
        namespace = f"finance-d06-{uuid.uuid4().hex}"
        client_a = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
        client_b = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
        config = adapter.ReportTaskRedisConfig(namespace=namespace, ttl_sec=20)
        store_a = adapter.RedisReportTaskSnapshotStore(client_a, config)
        store_b = adapter.RedisReportTaskSnapshotStore(client_b, config)
        user_id = "private-user-d06-cache"
        key_digest = "a" * 64
        fingerprint = "b" * 64
        snapshot = _snapshot(contracts)
        try:
            await store_a.set_snapshot(
                user_id=user_id,
                key_digest=key_digest,
                request_fingerprint=fingerprint,
                snapshot=snapshot,
            )
            hit = await store_b.get_snapshot(
                user_id=user_id,
                key_digest=key_digest,
                request_fingerprint=fingerprint,
            )
            assert hit == snapshot
            assert await store_b.get_snapshot(
                user_id="another-user",
                key_digest=key_digest,
                request_fingerprint=fingerprint,
            ) is None

            keys = await client_a.keys(f"{namespace}:*")
            snapshot_keys = [key for key in keys if ":snapshot:" in key]
            assert len(snapshot_keys) == 1
            raw = await client_a.get(snapshot_keys[0])
            assert raw is not None
            assert all(
                secret not in raw and secret not in snapshot_keys[0]
                for secret in (user_id, key_digest, fingerprint)
            )
            assert 0 < await client_a.ttl(snapshot_keys[0]) <= 20

            async with store_b.subscribe(snapshot.task_id) as subscription:
                await store_a.publish_version(snapshot.task_id, snapshot.snapshot_version)
                observed = await asyncio.wait_for(subscription.receive(), timeout=2)
            assert observed.task_id == snapshot.task_id
            assert observed.snapshot_version == snapshot.snapshot_version

            corrupted = json.dumps({"schema_version": "unknown", "payload": {}})
            await client_a.set(snapshot_keys[0], corrupted, ex=20)
            assert await store_b.get_snapshot(
                user_id=user_id,
                key_digest=key_digest,
                request_fingerprint=fingerprint,
            ) is None
            assert await client_a.exists(snapshot_keys[0]) == 0
            health = await store_b.health()
            assert health["metrics"]["malformed"] >= 1
            assert health["metrics"]["subscriptions_opened"] == 1
            assert health["metrics"]["subscriptions_closed"] == 1
        finally:
            remaining = await client_a.keys(f"{namespace}:*")
            if remaining:
                await client_a.delete(*remaining)
            await client_a.aclose()
            await client_b.aclose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_unreachable_report_redis_is_bounded_and_degraded() -> None:
    """D06-T03：Redis 不可达在一秒内安全降级，不伪造命中或抛给 API。"""

    async def scenario() -> None:
        adapter = _module("backend.infrastructure.report_tasks.redis_store")
        client = redis.Redis.from_url(
            "redis://127.0.0.1:1/15",
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=0.05,
            socket_timeout=0.05,
        )
        store = adapter.RedisReportTaskSnapshotStore(
            client,
            adapter.ReportTaskRedisConfig(namespace="finance-d06-unreachable", ttl_sec=20),
        )
        try:
            result = await asyncio.wait_for(
                store.get_snapshot(
                    user_id="user-d06",
                    key_digest="a" * 64,
                    request_fingerprint="b" * 64,
                ),
                timeout=1,
            )
            assert result is None
            assert (await store.health())["status"] == "DEGRADED"
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_report_runtime_lifecycle_is_fail_open_and_closes_global_reference() -> None:
    """D06-T03：启动时 Redis 不可达仍返回 DEGRADED 运行时，关闭后清空引用。"""

    async def scenario() -> None:
        runtime_module = _module("backend.infrastructure.report_tasks.runtime")
        settings_module = importlib.import_module("backend.config")
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(settings_module.settings, "enable_report_task_redis", True)
            monkeypatch.setattr(
                settings_module.settings,
                "redis_url",
                "redis://127.0.0.1:1/15",
            )
            monkeypatch.setattr(settings_module.settings, "redis_connect_timeout_sec", 0.05)
            monkeypatch.setattr(settings_module.settings, "redis_socket_timeout_sec", 0.05)
            runtime = await asyncio.wait_for(
                runtime_module.initialize_report_task_runtime(),
                timeout=1,
            )
            assert runtime is not None
            assert (await runtime.health())["status"] == "DEGRADED"
            await runtime_module.close_report_task_runtime()
            assert runtime_module.get_report_task_runtime() is None

    asyncio.run(scenario())
