import threading
import time

from backend.integrations.redis.metrics import (
    COUNTER_NAMES,
    Counter,
    Histogram,
    MetricsCollector,
    get_metrics_collector,
    reset_metrics_collector,
)


def test_counter_should_increment_and_reset():
    c = Counter()
    c.inc()
    c.inc(2)
    assert c.get() == 3
    c.reset()
    assert c.get() == 0


def test_histogram_should_compute_p50_and_p95():
    h = Histogram()
    for v in [1.0, 2.0, 3.0, 4.0, 100.0]:
        h.record(v)
    assert h.percentile(50) == 3.0
    assert h.percentile(95) == 100.0


def test_histogram_should_return_none_when_empty():
    h = Histogram()
    assert h.percentile(50) is None
    assert h.percentile(95) is None


def test_metrics_collector_snapshot_should_match_contract():
    mc = MetricsCollector()
    mc.inc("cache_hit", 5)
    mc.inc("cache_miss", 3)
    mc.inc("cache_set", 4)
    mc.record_get_latency(0.4)
    mc.record_get_latency(1.1)
    mc.record_set_latency(0.6)
    mc.record_set_latency(1.5)

    snap = mc.snapshot(redis_enabled=True, redis_available=True)
    assert snap["redis_enabled"] is True
    assert snap["redis_available"] is True
    assert snap["counters"]["cache_hit"] == 5
    assert snap["counters"]["cache_miss"] == 3
    assert snap["counters"]["cache_set"] == 4
    assert snap["counters"]["cache_fallback"] == 0
    assert snap["latency_ms"]["get_p50"] is not None
    assert snap["latency_ms"]["get_p95"] is not None
    assert snap["latency_ms"]["set_p50"] is not None
    assert snap["latency_ms"]["set_p95"] is not None


def test_metrics_collector_reset_should_clear_all():
    mc = MetricsCollector()
    mc.inc("cache_hit")
    mc.record_get_latency(1.0)
    mc.reset()
    snap = mc.snapshot()
    assert snap["counters"]["cache_hit"] == 0
    assert snap["latency_ms"]["get_p50"] is None


def test_metrics_collector_should_reject_unknown_counter():
    mc = MetricsCollector()
    try:
        mc.inc("unknown_counter")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_metrics_collector_should_expose_all_planned_counters():
    mc = MetricsCollector()
    snap = mc.snapshot()
    for name in COUNTER_NAMES:
        assert name in snap["counters"]


def test_get_metrics_collector_singleton_should_reset_in_tests():
    reset_metrics_collector()
    a = get_metrics_collector()
    a.inc("cache_hit")
    reset_metrics_collector()
    b = get_metrics_collector()
    assert b is not a
    assert b.snapshot()["counters"]["cache_hit"] == 0


def test_counter_should_be_thread_safe_under_contention():
    c = Counter()
    threads = [
        threading.Thread(target=lambda: [c.inc() for _ in range(100)])
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.get() == 1000


def test_record_latency_should_be_fast_enough():
    mc = MetricsCollector()
    started = time.perf_counter()
    for _ in range(1000):
        mc.record_get_latency(0.5)
    elapsed_ms = (time.perf_counter() - started) * 1000
    # 单次 record 应远小于 1ms；1000 次总耗时应明显低于 1s
    assert elapsed_ms < 500
