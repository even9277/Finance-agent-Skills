"""定义记忆生命周期的安全观测合同和进程内指标。

应用层只暴露低基数、无正文的观测字段；具体 JSONL/Langfuse 输出由基础设施适配器负责。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol


class MemoryStage(StrEnum):
    """记忆链路允许使用的稳定阶段名。"""

    PREFLIGHT = "memory.preflight"
    STATE_EXTRACT = "memory.state.extract"
    STATE_MERGE = "memory.state.merge"
    COMPACT = "memory.compact"
    CANDIDATE_EXTRACT = "memory.candidate.extract"
    CANDIDATE_GOVERN = "memory.candidate.govern"
    INDEX = "memory.index"
    RETRIEVE = "memory.retrieve"
    INJECT = "memory.inject"
    MUTATE = "memory.mutate"
    DELETE = "memory.delete"
    CACHE = "memory.cache"
    WORKER = "memory.worker"


class MemoryStatus(StrEnum):
    """记忆阶段对外可见的有限状态。"""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    DEGRADED = "DEGRADED"
    RETRY = "RETRY"
    DEAD_LETTER = "DEAD_LETTER"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class MemoryObservation:
    """一条不携带用户正文的记忆阶段观测。"""

    stage: MemoryStage
    status: MemoryStatus
    trace_id: str = ""
    run_id: str = ""
    reference: str | None = None
    elapsed_ms: float = 0.0
    error_code: str | None = None
    affected_count: int = 0
    version: int | None = None
    consistency_status: str | None = None

    def __post_init__(self) -> None:
        if self.elapsed_ms < 0 or self.affected_count < 0:
            raise ValueError("memory observation numeric fields must be non-negative")
        if self.reference is not None and len(self.reference) > 96:
            raise ValueError("memory observation reference is too long")


class MemoryObserver(Protocol):
    """声明应用层向日志、Trace 和指标适配器发送观测的端口。"""

    def emit(self, observation: MemoryObservation) -> None:
        """写入一条安全观测；观测失败不得反向影响业务事务。"""
        ...


class MemoryMetrics:
    """提供线程安全、可重置且不包含业务正文的进程内计数器。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()

    def record(self, observation: MemoryObservation) -> None:
        """按阶段和状态递增计数，不保存观测正文或用户标识。"""
        with self._lock:
            self._counts["events_total"] += 1
            self._counts[f"stage.{observation.stage.value}"] += 1
            self._counts[f"status.{observation.status.value}"] += 1
            if observation.error_code:
                self._counts[f"error.{observation.error_code}"] += 1

    def snapshot(self) -> dict[str, int]:
        """返回排序后的平面快照，便于健康检查和离线断言。"""
        with self._lock:
            return dict(sorted(self._counts.items()))

    def reset(self) -> None:
        """清空当前进程计数，仅供测试和进程重启使用。"""
        with self._lock:
            self._counts.clear()


memory_metrics = MemoryMetrics()
_default_observer: MemoryObserver | None = None


def get_default_memory_observer() -> MemoryObserver:
    """返回运行时观测适配器；导入延迟以保持应用层与基础设施单向依赖。"""
    global _default_observer
    if _default_observer is None:
        from backend.infrastructure.memory.observability import MemoryTraceSink

        _default_observer = MemoryTraceSink(metrics=memory_metrics)
    return _default_observer


def emit_memory_observation(
    observation: MemoryObservation,
    *,
    observer: MemoryObserver | None = None,
) -> None:
    """发送观测并隔离观测出口故障，保证业务主链不中断。"""
    try:
        (observer or get_default_memory_observer()).emit(observation)
    except Exception:
        # 观测属于旁路能力，具体适配器会记录自身失败；这里不传播异常。
        return
