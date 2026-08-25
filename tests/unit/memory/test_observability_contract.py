"""验证记忆阶段、脱敏观测和指标快照合同。"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.observability import (  # noqa: E402
    MemoryObservation,
    MemoryStage,
    MemoryStatus,
    MemoryMetrics,
    emit_memory_observation,
)
from backend.infrastructure.memory.observability import MemoryTraceSink  # noqa: E402


@pytest.mark.unit
def test_observation_metrics_are_flat_bounded_and_resettable() -> None:
    """指标只保留阶段、状态和错误码，不保存正文或用户标识。"""
    metrics = MemoryMetrics()
    sink = MemoryTraceSink(metrics=metrics)
    with patch("backend.infrastructure.memory.observability.log_memory_stage"):
        sink.emit(
            MemoryObservation(
                stage=MemoryStage.RETRIEVE,
                status=MemoryStatus.DEGRADED,
                trace_id="trace-safe",
                run_id="run-safe",
                reference="task_safe",
                affected_count=2,
                error_code="PROVIDER_UNAVAILABLE",
            )
        )
    snapshot = metrics.snapshot()
    assert snapshot["events_total"] == 1
    assert snapshot["stage.memory.retrieve"] == 1
    assert snapshot["status.DEGRADED"] == 1
    assert snapshot["error.PROVIDER_UNAVAILABLE"] == 1
    assert all("用户" not in key for key in snapshot)
    metrics.reset()
    assert metrics.snapshot() == {}


@pytest.mark.unit
def test_trace_sink_does_not_log_private_payload(caplog: pytest.LogCaptureFixture) -> None:
    """日志只出现低基数字段，命令正文和记忆正文不会进入消息。"""
    sink = MemoryTraceSink(metrics=MemoryMetrics())
    with patch("backend.infrastructure.memory.observability.log_memory_stage"):
        with caplog.at_level(logging.INFO):
            sink.emit(
                MemoryObservation(
                    stage=MemoryStage.DELETE,
                    status=MemoryStatus.SUCCEEDED,
                    trace_id="trace-safe",
                    run_id="run-safe",
                    reference="mcmd_safe",
                    affected_count=1,
                )
            )
    output = " ".join(record.getMessage() for record in caplog.records)
    assert "忘掉我的文本记忆" not in output
    assert "合成测试记忆" not in output
    assert "memory.delete" in output
    assert "SUCCEEDED" in output


@pytest.mark.unit
def test_observation_export_failure_is_fail_open() -> None:
    """Trace 出口故障只能影响旁路观测，不能让应用层抛错。"""
    observation = MemoryObservation(
        stage=MemoryStage.COMPACT,
        status=MemoryStatus.FAILED,
        error_code="PROVIDER_UNAVAILABLE",
    )
    class FailingObserver:
        """模拟不可用的观测出口。"""

        def emit(self, observation: MemoryObservation) -> None:
            del observation
            raise RuntimeError("trace sink unavailable")

    observer = FailingObserver()
    emit_memory_observation(observation, observer=observer)
