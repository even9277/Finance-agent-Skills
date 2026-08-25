"""把记忆观测合同桥接到结构化日志、JSONL Trace 和进程指标。"""

from __future__ import annotations

import logging

from backend.application.memory.observability import MemoryMetrics, MemoryObservation
from src.tools.skill_trace import log_memory_stage

logger = logging.getLogger(__name__)


class MemoryTraceSink:
    """输出安全记忆事件；不接收命令原文、记忆正文或用户 ID。"""

    def __init__(self, *, metrics: MemoryMetrics) -> None:
        self._metrics = metrics

    def emit(self, observation: MemoryObservation) -> None:
        """记录阶段、状态、耗时和数量，并隔离可选 Trace 出口异常。"""
        self._metrics.record(observation)
        fields = {
            "stage": observation.stage.value,
            "status": observation.status.value,
            "elapsed_ms": round(observation.elapsed_ms, 2),
            "error_code": observation.error_code,
            "affected_count": observation.affected_count,
            "version": observation.version,
            "consistency_status": observation.consistency_status,
        }
        if observation.reference:
            fields["reference"] = observation.reference
        logger.info("memory.lifecycle %s", fields)
        try:
            log_memory_stage(
                trace_id=observation.trace_id or "memory-trace",
                run_id=observation.run_id or "memory-run",
                stage=observation.stage.value,
                status=observation.status.value,
                elapsed_ms=observation.elapsed_ms,
                error_code=observation.error_code,
                metrics={
                    "affected_count": observation.affected_count,
                    "version": observation.version,
                },
                refs={"reference": observation.reference} if observation.reference else None,
            )
        except Exception as exc:
            logger.warning(
                "memory.trace_export_failed stage=%s status=%s error_code=%s error_type=%s",
                "memory.trace",
                "DEGRADED",
                "TRACE_EXPORT_FAILED",
                type(exc).__name__,
            )
