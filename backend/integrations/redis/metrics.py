"""
Redis 缓存指标采集（进程内计数器 + 延迟分位数）。

供 CacheService 与 /api/redis/metrics 复用；后续可替换为 Prometheus 实现。
"""

from __future__ import annotations

import math
import threading
from typing import Dict, List, Optional

# 与计划 §3.4 对齐的计数器名
COUNTER_NAMES = (
    "cache_hit",
    "cache_miss",
    "cache_set",
    "cache_delete",
    "cache_fallback",
    "redis_timeout",
    "redis_error",
    "oversize_count",
)


class Counter:
    """线程安全的单调递增计数器。"""

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def inc(self, delta: int = 1) -> None:
        if delta <= 0:
            return
        with self._lock:
            self._value += delta

    def get(self) -> int:
        with self._lock:
            return self._value

    def reset(self) -> None:
        with self._lock:
            self._value = 0


class Histogram:
    """延迟样本直方图，支持 P50 / P95。"""

    def __init__(self, max_samples: int = 10_000) -> None:
        self._max_samples = max(1, max_samples)
        self._samples: List[float] = []
        self._lock = threading.Lock()

    def record(self, value_ms: float) -> None:
        if value_ms < 0:
            return
        with self._lock:
            self._samples.append(value_ms)
            if len(self._samples) > self._max_samples:
                self._samples = self._samples[-self._max_samples :]

    def percentile(self, p: float) -> Optional[float]:
        """Nearest-rank 分位数，无样本时返回 None。"""
        with self._lock:
            if not self._samples:
                return None
            ordered = sorted(self._samples)
            # ceil(p/100 * n) 的 1-based rank，再转 0-based 索引
            rank = math.ceil((p / 100.0) * len(ordered))
            idx = max(0, min(rank - 1, len(ordered) - 1))
            return round(ordered[idx], 3)

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()


class MetricsCollector:
    """
    Redis 相关指标聚合器。

    - 计数器：cache_hit / cache_miss / cache_set 等
    - 延迟：get/set 操作的 P50、P95（毫秒）
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, Counter] = {
            name: Counter() for name in COUNTER_NAMES
        }
        self._get_latency = Histogram()
        self._set_latency = Histogram()

    def inc(self, name: str, delta: int = 1) -> None:
        counter = self._counters.get(name)
        if counter is None:
            raise KeyError(f"未知计数器: {name}")
        counter.inc(delta)

    def record_get_latency(self, latency_ms: float) -> None:
        self._get_latency.record(latency_ms)

    def record_set_latency(self, latency_ms: float) -> None:
        self._set_latency.record(latency_ms)

    def snapshot(
        self,
        *,
        redis_enabled: bool = False,
        redis_available: bool = False,
    ) -> dict:
        with self._lock:
            counters = {name: c.get() for name, c in self._counters.items()}
            latency_ms = {
                "get_p50": self._get_latency.percentile(50),
                "get_p95": self._get_latency.percentile(95),
                "set_p50": self._set_latency.percentile(50),
                "set_p95": self._set_latency.percentile(95),
            }
        return {
            "redis_enabled": redis_enabled,
            "redis_available": redis_available,
            "counters": counters,
            "latency_ms": latency_ms,
        }

    def reset(self) -> None:
        with self._lock:
            for counter in self._counters.values():
                counter.reset()
            self._get_latency.reset()
            self._set_latency.reset()


# 进程内默认实例，供后续 main / CacheService 挂载
_default_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    global _default_collector
    with _collector_lock:
        if _default_collector is None:
            _default_collector = MetricsCollector()
        return _default_collector


def reset_metrics_collector() -> None:
    """主要用于测试隔离：丢弃单例，下次 get 时重建。"""
    global _default_collector
    with _collector_lock:
        _default_collector = None
