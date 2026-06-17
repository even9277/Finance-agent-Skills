"""
业务侧 Redis 缓存唯一入口（Cache-Aside + Envelope + 降级 + 指标）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Optional, Tuple

from .client import RedisClient
from .envelope import CacheEnvelope, utc_now_iso
from .key_builder import KeyBuilder
from .lock import NoOpLockHandle, create_lock
from .metrics import MetricsCollector, get_metrics_collector

logger = logging.getLogger(__name__)

# 本阶段固定 envelope schema 版本；不匹配则按 miss 处理
ENVELOPE_SCHEMA_VERSION = 1
DEFAULT_MAX_VALUE_BYTES = 256 * 1024

TraceMeta = dict[str, Any]


class CacheService:
    def __init__(
        self,
        redis_client: RedisClient,
        key_builder: KeyBuilder,
        metrics: MetricsCollector,
        *,
        redis_enabled: bool = False,
        max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
        unavailable_recheck_sec: int = 30,
        default_ttl_jitter_ratio: float = 0.1,
    ) -> None:
        self.redis_client = redis_client
        self.key_builder = key_builder
        self.metrics = metrics
        self.redis_enabled = redis_enabled
        self.max_value_bytes = max_value_bytes
        self.unavailable_recheck_sec = unavailable_recheck_sec
        self.default_ttl_jitter_ratio = default_ttl_jitter_ratio
        self._last_probe_at = 0.0

    @classmethod
    def from_settings(
        cls,
        redis_client: RedisClient,
        metrics: Optional[MetricsCollector] = None,
    ) -> "CacheService":
        from backend.config import settings

        return cls(
            redis_client,
            KeyBuilder(settings.redis_namespace_env),
            metrics or get_metrics_collector(),
            redis_enabled=settings.redis_enabled,
            max_value_bytes=DEFAULT_MAX_VALUE_BYTES,
            unavailable_recheck_sec=settings.redis_unavailable_recheck_sec,
            default_ttl_jitter_ratio=settings.redis_ttl_jitter_ratio,
        )

    @staticmethod
    def ttl_with_jitter(base_ttl: int, jitter_ratio: float) -> int:
        """TTL 加随机抖动，结果落在约 [base*0.9, base*1.1]（ratio=0.1）。"""
        if base_ttl <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        delta = max(1, int(base_ttl * jitter_ratio))
        jittered = base_ttl + random.randint(-delta, delta)
        return max(1, jittered)

    async def _maybe_probe_redis(self) -> bool:
        if not self.redis_enabled:
            return False
        if self.redis_client.is_available():
            return True
        now = time.monotonic()
        if now - self._last_probe_at < self.unavailable_recheck_sec:
            return False
        self._last_probe_at = now
        return await self.redis_client.ping()

    async def _redis_ready(self) -> bool:
        if not self.redis_enabled:
            return False
        if self.redis_client.is_available():
            return True
        return await self._maybe_probe_redis()

    def _fallback_meta(self, reason: str, latency_ms: Optional[float] = None) -> TraceMeta:
        self.metrics.inc("cache_fallback")
        meta: TraceMeta = {
            "cache_hit": False,
            "fallback": True,
            "reason": reason,
        }
        if latency_ms is not None:
            meta["latency_ms"] = round(latency_ms, 3)
        return meta

    def _success_meta(
        self,
        *,
        cache_hit: bool,
        latency_ms: float,
        version_match: Optional[bool] = None,
    ) -> TraceMeta:
        meta: TraceMeta = {
            "cache_hit": cache_hit,
            "fallback": False,
            "latency_ms": round(latency_ms, 3),
        }
        if version_match is not None:
            meta["version_match"] = version_match
        return meta

    def _parse_envelope(self, raw: str, key: str) -> Optional[CacheEnvelope]:
        try:
            payload = json.loads(raw)
            envelope = CacheEnvelope(**payload)
        except Exception as exc:
            logger.warning(
                "Redis 缓存反序列化失败 key_prefix=%s size=%s err=%s",
                key[:48],
                len(raw),
                type(exc).__name__,
            )
            return None
        if envelope.schema_version != ENVELOPE_SCHEMA_VERSION:
            return None
        return envelope

    def _is_timeout_error(self, exc: BaseException) -> bool:
        name = type(exc).__name__.lower()
        return "timeout" in name or isinstance(exc, (asyncio.TimeoutError, TimeoutError))

    async def get(self, key: str) -> Tuple[Optional[CacheEnvelope], TraceMeta]:
        started = time.perf_counter()
        if not self.redis_enabled:
            return None, self._fallback_meta("redis_disabled")

        if not await self._redis_ready():
            return None, self._fallback_meta("redis_unavailable")

        client = self.redis_client.get_client()
        if client is None:
            return None, self._fallback_meta("redis_unavailable")

        try:
            raw = await client.get(key)
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.record_get_latency(latency_ms)
            if raw is None:
                self.metrics.inc("cache_miss")
                return None, self._success_meta(cache_hit=False, latency_ms=latency_ms)
            envelope = self._parse_envelope(raw, key)
            if envelope is None:
                self.metrics.inc("cache_miss")
                return None, self._success_meta(cache_hit=False, latency_ms=latency_ms)
            self.metrics.inc("cache_hit")
            return envelope, self._success_meta(cache_hit=True, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.record_get_latency(latency_ms)
            if self._is_timeout_error(exc):
                self.metrics.inc("redis_timeout")
                reason = "redis_timeout"
            else:
                self.metrics.inc("redis_error")
                reason = "redis_error"
            logger.warning("Redis get 失败 key_prefix=%s reason=%s", key[:48], reason)
            return None, self._fallback_meta(reason, latency_ms=latency_ms)

    async def get_with_version(
        self,
        key: str,
        expected_payload_version: int,
    ) -> Tuple[Optional[CacheEnvelope], TraceMeta]:
        envelope, meta = await self.get(key)
        if meta.get("fallback"):
            meta["version_match"] = False
            return None, meta
        if envelope is None:
            meta["version_match"] = False
            return None, meta
        if envelope.payload_version != expected_payload_version:
            self.metrics.inc("cache_miss")
            meta = self._success_meta(
                cache_hit=False,
                latency_ms=meta.get("latency_ms", 0.0),
                version_match=False,
            )
            return None, meta
        meta["version_match"] = True
        return envelope, meta

    async def set(
        self,
        key: str,
        data: Any,
        ttl_seconds: int,
        source: str,
        payload_version: Optional[int] = None,
        ttl_jitter_ratio: Optional[float] = None,
    ) -> TraceMeta:
        started = time.perf_counter()
        ratio = (
            self.default_ttl_jitter_ratio
            if ttl_jitter_ratio is None
            else ttl_jitter_ratio
        )
        try:
            effective_ttl = self.ttl_with_jitter(ttl_seconds, ratio)
        except ValueError:
            raise

        if not self.redis_enabled:
            return {
                **self._fallback_meta("redis_disabled"),
                "success": False,
            }

        if not await self._redis_ready():
            return {
                **self._fallback_meta("redis_unavailable"),
                "success": False,
            }

        client = self.redis_client.get_client()
        if client is None:
            return {
                **self._fallback_meta("redis_unavailable"),
                "success": False,
            }

        envelope = CacheEnvelope(
            data=data,
            schema_version=ENVELOPE_SCHEMA_VERSION,
            payload_version=payload_version,
            updated_at=utc_now_iso(),
            source=source,
        )
        if hasattr(envelope, "model_dump"):
            payload = envelope.model_dump()
        else:
            payload = envelope.dict()
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode("utf-8")) > self.max_value_bytes:
            self.metrics.inc("oversize_count")
            raise ValueError(
                f"缓存 value 超过上限 {self.max_value_bytes} 字节，拒绝写入"
            )

        try:
            await client.set(key, raw, ex=effective_ttl)
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.record_set_latency(latency_ms)
            self.metrics.inc("cache_set")
            return {
                **self._success_meta(cache_hit=False, latency_ms=latency_ms),
                "success": True,
                "ttl_seconds": effective_ttl,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.record_set_latency(latency_ms)
            if self._is_timeout_error(exc):
                self.metrics.inc("redis_timeout")
                reason = "redis_timeout"
            else:
                self.metrics.inc("redis_error")
                reason = "redis_error"
            logger.warning("Redis set 失败 key_prefix=%s reason=%s", key[:48], reason)
            return {
                **self._fallback_meta(reason, latency_ms=latency_ms),
                "success": False,
            }

    async def set_if_absent(
        self,
        key: str,
        data: Any,
        ttl_seconds: int,
        source: str,
        payload_version: Optional[int] = None,
    ) -> Tuple[bool, TraceMeta]:
        """原子 SET NX + EX，仅在 key 不存在时写入。"""
        started = time.perf_counter()
        try:
            effective_ttl = self.ttl_with_jitter(
                ttl_seconds,
                self.default_ttl_jitter_ratio,
            )
        except ValueError:
            raise

        if not self.redis_enabled:
            return False, {**self._fallback_meta("redis_disabled"), "success": False}

        if not await self._redis_ready():
            return False, {**self._fallback_meta("redis_unavailable"), "success": False}

        client = self.redis_client.get_client()
        if client is None:
            return False, {**self._fallback_meta("redis_unavailable"), "success": False}

        envelope = CacheEnvelope(
            data=data,
            schema_version=ENVELOPE_SCHEMA_VERSION,
            payload_version=payload_version,
            updated_at=utc_now_iso(),
            source=source,
        )
        if hasattr(envelope, "model_dump"):
            payload = envelope.model_dump()
        else:
            payload = envelope.dict()
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode("utf-8")) > self.max_value_bytes:
            self.metrics.inc("oversize_count")
            raise ValueError(
                f"缓存 value 超过上限 {self.max_value_bytes} 字节，拒绝写入"
            )

        try:
            created = await client.set(key, raw, ex=effective_ttl, nx=True)
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.record_set_latency(latency_ms)
            success = created is True
            if success:
                self.metrics.inc("cache_set")
            return success, {
                **self._success_meta(cache_hit=not success, latency_ms=latency_ms),
                "success": success,
                "exists": not success,
                "ttl_seconds": effective_ttl,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.record_set_latency(latency_ms)
            if self._is_timeout_error(exc):
                self.metrics.inc("redis_timeout")
                reason = "redis_timeout"
            else:
                self.metrics.inc("redis_error")
                reason = "redis_error"
            logger.warning("Redis set_if_absent 失败 key_prefix=%s reason=%s", key[:48], reason)
            return False, {
                **self._fallback_meta(reason, latency_ms=latency_ms),
                "success": False,
            }

    async def delete(self, key: str) -> TraceMeta:
        started = time.perf_counter()
        if not self.redis_enabled:
            return {
                **self._fallback_meta("redis_disabled"),
                "deleted": False,
            }

        if not await self._redis_ready():
            return {
                **self._fallback_meta("redis_unavailable"),
                "deleted": False,
            }

        client = self.redis_client.get_client()
        if client is None:
            return {
                **self._fallback_meta("redis_unavailable"),
                "deleted": False,
            }

        try:
            removed = await client.delete(key)
            latency_ms = (time.perf_counter() - started) * 1000
            if removed:
                self.metrics.inc("cache_delete")
            return {
                **self._success_meta(cache_hit=False, latency_ms=latency_ms),
                "deleted": bool(removed),
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            if self._is_timeout_error(exc):
                self.metrics.inc("redis_timeout")
                reason = "redis_timeout"
            else:
                self.metrics.inc("redis_error")
                reason = "redis_error"
            return {
                **self._fallback_meta(reason, latency_ms=latency_ms),
                "deleted": False,
            }

    async def ping(self) -> bool:
        if not self.redis_enabled:
            return False
        return await self.redis_client.ping()

    def lock(self, name: str, ttl_ms: int):
        client = self.redis_client.get_client()
        lock_key = self.key_builder.lock(name)
        if not self.redis_enabled or client is None:
            return NoOpLockHandle()
        return create_lock(client, lock_key, ttl_ms)
