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
