"""验证报告 Redis 派生观察层的 typed Settings 边界。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config import Settings


@pytest.mark.unit
def test_report_redis_defaults_are_optional_and_bounded() -> None:
    """D06-T03：默认关闭派生 Redis，但保留正 TTL、超时和独立命名空间。"""
    configured = Settings(_env_file=None)  # type: ignore[call-arg]

    assert configured.enable_report_task_governance is True
    assert configured.enable_report_task_redis is False
    assert configured.report_task_redis_namespace != configured.redis_cache_namespace
    assert configured.report_task_snapshot_ttl_sec >= configured.report_idempotency_ttl_sec
    assert configured.report_task_reconcile_sec > 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "override",
    [
        {"report_task_redis_namespace": "bad namespace"},
        {"report_task_snapshot_ttl_sec": 0},
        {"report_task_reconcile_sec": 0},
    ],
)
def test_report_redis_settings_reject_unsafe_values(override: dict[str, object]) -> None:
    """D06-T03：空白命名空间与非正 TTL/对账间隔在启动前失败。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **override)  # type: ignore[call-arg]
