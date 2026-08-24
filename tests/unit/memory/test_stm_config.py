"""验证短期记忆后台任务的启动配置契约。"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_summary_lease_exceeds_provider_timeout_with_safety_margin() -> None:
    """默认租约必须覆盖模型超时和提交阶段的安全余量。"""
    configured = Settings(
        stm_summary_timeout_sec=30,
        stm_worker_lease_sec=60,
    )

    assert configured.stm_worker_lease_sec > configured.stm_summary_timeout_sec + 5


def test_unsafe_summary_lease_configuration_fails_fast() -> None:
    """启动时拒绝会让正常模型调用必然丢失 lease 的参数组合。"""
    with pytest.raises(ValidationError, match="stm_worker_lease_sec"):
        Settings(stm_summary_timeout_sec=60, stm_worker_lease_sec=60)


@pytest.mark.parametrize(
    ("field_name", "invalid_settings"),
    (
        ("stm_keep_recent", lambda: Settings(stm_keep_recent=0)),
        ("stm_worker_interval_sec", lambda: Settings(stm_worker_interval_sec=0)),
        ("stm_worker_batch_size", lambda: Settings(stm_worker_batch_size=0)),
        ("stm_worker_max_retries", lambda: Settings(stm_worker_max_retries=0)),
        ("stm_summary_timeout_sec", lambda: Settings(stm_summary_timeout_sec=0)),
        ("stm_worker_lease_sec", lambda: Settings(stm_worker_lease_sec=0)),
    ),
)
def test_non_positive_stm_runtime_settings_are_rejected(
    field_name: str,
    invalid_settings: Callable[[], Settings],
) -> None:
    """会破坏预算或 Worker 活性的非正配置不得进入运行期。"""
    with pytest.raises(ValidationError, match=field_name):
        invalid_settings()


def test_redis_cache_defaults_to_optional_and_uses_bounded_settings() -> None:
    """Redis 默认关闭，启用后的 TTL、租约、等待和超时均为有限正值。"""
    configured = Settings()

    assert configured.enable_redis_cache is False
    assert configured.redis_url.startswith("redis://")
    assert configured.redis_cache_ttl_sec > configured.redis_cache_lease_sec > 0
    assert configured.redis_singleflight_wait_ms > 0
    assert configured.redis_connect_timeout_sec > 0
    assert configured.redis_socket_timeout_sec > 0


@pytest.mark.parametrize(
    "invalid_settings",
    (
        lambda: Settings(redis_cache_ttl_sec=0),
        lambda: Settings(redis_cache_lease_sec=0),
        lambda: Settings(redis_singleflight_wait_ms=0),
        lambda: Settings(redis_connect_timeout_sec=0),
        lambda: Settings(redis_socket_timeout_sec=0),
        lambda: Settings(redis_max_connections=0),
        lambda: Settings(redis_url="http://localhost:6379"),
        lambda: Settings(redis_cache_namespace="bad namespace"),
    ),
)
def test_redis_cache_rejects_unsafe_settings(
    invalid_settings: Callable[[], Settings],
) -> None:
    """不安全的 Redis 运行参数必须在应用启动前 fail-fast。"""
    with pytest.raises(ValidationError):
        invalid_settings()
