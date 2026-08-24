"""实现 Redis 记忆热缓存；任何故障都安全降级到权威数据库。"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Protocol, TypeVar, cast

from backend.application.memory.cache import (
    CACHE_SCHEMA_VERSION,
    CacheErrorCode,
    CacheLookup,
    CacheLookupStatus,
    CachedCompactProfile,
    CachedConversationContext,
    MemoryCacheConfig,
)
from src.memory.contracts import (
    MEMORY_SCHEMA_VERSION,
    MemoryScope,
    WorkingEntity,
    WorkingState,
)

logger = logging.getLogger(__name__)

_RELEASE_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class AsyncRedisClient(Protocol):
    """收窄 redis-py 到本适配器实际使用的异步命令。"""

    async def get(self, key: str) -> str | None: ...

    async def set(
        self, key: str, value: str, *, ex: int, nx: bool = False
    ) -> object: ...

    async def delete(self, key: str) -> int: ...

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> object: ...

    async def ping(self) -> object: ...

    async def aclose(self) -> None: ...


T = TypeVar("T")


class RedisMemoryHotCache:
    """用版本化 JSON Envelope 加速记忆读取，并对 Redis 失败 fail-open。"""

    def __init__(self, client: AsyncRedisClient, config: MemoryCacheConfig) -> None:
        self._client = client
        self._config = config
        self._metrics = {
            "hits": 0,
            "misses": 0,
            "stale": 0,
            "malformed": 0,
            "errors": 0,
            "sets": 0,
            "invalidations": 0,
            "lease_acquired": 0,
            "lease_contended": 0,
        }
        self._last_error_code: CacheErrorCode | None = None

    @property
    def config(self) -> MemoryCacheConfig:
        """返回已校验的缓存运行参数。"""
        return self._config

    async def get_context(
        self,
        user_id: str,
        session_id: str,
        *,
        expected_turn_count: int,
        expected_summary_version: int,
    ) -> CacheLookup[CachedConversationContext]:
        """读取与权威会话版本一致的摘要和原始尾窗。"""
        expected = f"{expected_turn_count}:{expected_summary_version}"
        return await self._get(
            "context",
            user_id,
            session_id,
            expected,
            self._decode_context,
        )

    async def set_context(
        self,
        user_id: str,
        session_id: str,
        value: CachedConversationContext,
    ) -> None:
        """写入仅包含已提交消息的会话上下文。"""
        await self._set(
            "context",
            user_id,
            session_id,
            f"{value.turn_count}:{value.summary_version}",
            {
                "turn_count": value.turn_count,
                "summary_version": value.summary_version,
                "running_summary": value.running_summary,
                "recent_messages": list(value.recent_messages),
            },
        )

    async def invalidate_context(self, user_id: str, session_id: str) -> None:
        """删除会话上下文派生缓存。"""
        await self._delete("context", user_id, session_id)

    async def get_working_state(
        self,
        user_id: str,
        session_id: str,
        *,
        expected_state_version: int,
    ) -> CacheLookup[WorkingState]:
        """读取与权威 state_version 一致的 Working State。"""
        return await self._get(
            "working",
            user_id,
            session_id,
            str(expected_state_version),
            self._decode_working_state,
        )

    async def set_working_state(
        self,
        user_id: str,
        session_id: str,
        value: WorkingState,
    ) -> None:
        """写入已提交的 Working State 快照。"""
        active = asdict(value.active_entity) if value.active_entity else None
        await self._set(
            "working",
            user_id,
            session_id,
            str(value.state_version),
            {
                "active_entity": active,
                "candidate_entities": [asdict(item) for item in value.candidate_entities],
                "constraints": list(value.constraints),
                "reply_preference_hint": value.reply_preference_hint,
                "scope": value.scope.value,
                "state_version": value.state_version,
                "schema_version": value.schema_version,
                "source_message_id": value.source_message_id,
                "updated_at": value.updated_at.isoformat() if value.updated_at else None,
            },
        )

    async def invalidate_working_state(self, user_id: str, session_id: str) -> None:
        """删除 Working State 派生缓存。"""
        await self._delete("working", user_id, session_id)

    async def get_profile(
        self,
        user_id: str,
        *,
        expected_profile_version: str,
    ) -> CacheLookup[CachedCompactProfile]:
        """读取与权威更新时间一致的紧凑画像。"""
        return await self._get(
            "profile",
            user_id,
            None,
            expected_profile_version,
            self._decode_profile,
        )

    async def set_profile(self, user_id: str, value: CachedCompactProfile) -> None:
        """写入聊天注入使用的紧凑画像字段。"""
        await self._set(
            "profile",
            user_id,
            None,
            value.profile_version,
            {
                "profile_version": value.profile_version,
                "risk_level": value.risk_level,
                "investment_horizon": value.investment_horizon,
                "expected_return_min": value.expected_return_min,
                "expected_return_max": value.expected_return_max,
                "sectors": list(value.sectors),
                "constraints": list(value.constraints),
                "response_pref": value.response_pref,
            },
        )

    async def invalidate_profile(self, user_id: str) -> None:
        """删除结构化画像的派生缓存。"""
        await self._delete("profile", user_id, None)

    async def acquire_fill_lease(
        self,
        kind: str,
        user_id: str,
        resource_id: str | None = None,
    ) -> str | None:
        """尝试获取短租约；Redis 故障时返回 None，由调用方直接回源。"""
        token = uuid.uuid4().hex
        try:
            acquired = await self._client.set(
                self._key(kind, user_id, resource_id, lease=True),
                token,
                ex=self._config.lease_sec,
                nx=True,
            )
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.lease.acquire")
            return None
        if acquired:
            self._metrics["lease_acquired"] += 1
            return token
        self._metrics["lease_contended"] += 1
        return None

    async def release_fill_lease(
        self,
        kind: str,
        user_id: str,
        resource_id: str | None,
        token: str,
    ) -> None:
        """通过 compare-and-delete 仅释放调用方持有的租约。"""
        try:
            await self._client.eval(
                _RELEASE_LEASE_SCRIPT,
                1,
                self._key(kind, user_id, resource_id, lease=True),
                token,
            )
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.lease.release")

    async def health(self) -> dict[str, object]:
        """返回不含地址、标识或缓存内容的安全健康摘要。"""
        try:
            await self._client.ping()
            status = "UP"
            error_code = None
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.health")
            status = "DEGRADED"
            error_code = CacheErrorCode.UNAVAILABLE.value
        return {
            "enabled": True,
            "status": status,
            "error_code": error_code,
            "metrics": dict(self._metrics),
        }

    async def close(self) -> None:
        """关闭 redis-py 连接池；失败不影响应用关停。"""
        try:
            await self._client.aclose()
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.close")

    async def _get(
        self,
        kind: str,
        user_id: str,
        resource_id: str | None,
        expected_version: str,
        decoder: Callable[[Mapping[str, object]], T],
    ) -> CacheLookup[T]:
        key = self._key(kind, user_id, resource_id)
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.read")
            return CacheLookup(
                CacheLookupStatus.DEGRADED,
                error_code=CacheErrorCode.UNAVAILABLE,
            )
        if raw is None:
            self._metrics["misses"] += 1
            return CacheLookup(CacheLookupStatus.MISS)
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("cache envelope must be an object")
            self._validate_envelope(envelope, kind, user_id, resource_id)
            if envelope.get("version") != expected_version:
                await self._safe_delete(key)
                self._metrics["stale"] += 1
                return CacheLookup(
                    CacheLookupStatus.STALE,
                    error_code=CacheErrorCode.VERSION_MISMATCH,
                )
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("cache payload must be an object")
            value = decoder(cast(Mapping[str, object], payload))
            # 外层版本和负载版本必须相互印证，防止损坏值伪装成当前快照。
            if self._value_version(kind, value) != expected_version:
                await self._safe_delete(key)
                self._metrics["stale"] += 1
                return CacheLookup(
                    CacheLookupStatus.STALE,
                    error_code=CacheErrorCode.VERSION_MISMATCH,
                )
        except Exception:
            await self._safe_delete(key)
            self._metrics["malformed"] += 1
            return CacheLookup(
                CacheLookupStatus.MALFORMED,
                error_code=CacheErrorCode.INVALID_PAYLOAD,
            )
        self._metrics["hits"] += 1
        self._last_error_code = None
        return CacheLookup(CacheLookupStatus.HIT, value=value)

    async def _set(
        self,
        kind: str,
        user_id: str,
        resource_id: str | None,
        version: str,
        payload: Mapping[str, object],
    ) -> None:
        envelope = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "kind": kind,
            "owner_ref": self._ref(user_id),
            "resource_ref": self._ref(resource_id) if resource_id else None,
            "version": version,
            "payload": payload,
        }
        try:
            await self._client.set(
                self._key(kind, user_id, resource_id),
                json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                ex=self._config.ttl_sec,
            )
            self._metrics["sets"] += 1
            self._last_error_code = None
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.write")

    async def _delete(
        self, kind: str, user_id: str, resource_id: str | None
    ) -> None:
        try:
            await self._client.delete(self._key(kind, user_id, resource_id))
            self._metrics["invalidations"] += 1
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.invalidate")

    async def _safe_delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:
            self._mark_error(exc, stage="memory.cache.reject")

    def _validate_envelope(
        self,
        envelope: Mapping[str, object],
        kind: str,
        user_id: str,
        resource_id: str | None,
    ) -> None:
        if envelope.get("schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("cache schema mismatch")
        if envelope.get("kind") != kind:
            raise ValueError("cache kind mismatch")
        if envelope.get("owner_ref") != self._ref(user_id):
            raise ValueError("cache owner mismatch")
        expected_resource = self._ref(resource_id) if resource_id else None
        if envelope.get("resource_ref") != expected_resource:
            raise ValueError("cache resource mismatch")

    @staticmethod
    def _value_version(kind: str, value: object) -> str:
        """从强类型负载重建版本，验证 Envelope 与内部内容一致。"""
        if kind == "context" and isinstance(value, CachedConversationContext):
            return f"{value.turn_count}:{value.summary_version}"
        if kind == "working" and isinstance(value, WorkingState):
            return str(value.state_version)
        if kind == "profile" and isinstance(value, CachedCompactProfile):
            return value.profile_version
        raise ValueError("cache value kind is invalid")

    def _key(
        self,
        kind: str,
        user_id: str,
        resource_id: str | None,
        *,
        lease: bool = False,
    ) -> str:
        resource = self._ref(resource_id) if resource_id else "global"
        suffix = ":lease" if lease else ""
        return (
            f"{self._config.namespace}:memory:v1:{kind}:"
            f"u:{self._ref(user_id)}:r:{resource}{suffix}"
        )

    @staticmethod
    def _ref(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _decode_context(payload: Mapping[str, object]) -> CachedConversationContext:
        messages = payload["recent_messages"]
        if not isinstance(messages, list) or not all(isinstance(item, str) for item in messages):
            raise ValueError("recent messages are invalid")
        summary = payload.get("running_summary")
        if summary is not None and not isinstance(summary, str):
            raise ValueError("running summary is invalid")
        return CachedConversationContext(
            turn_count=_strict_int(payload["turn_count"]),
            summary_version=_strict_int(payload["summary_version"]),
            running_summary=summary,
            recent_messages=tuple(messages),
        )

    @staticmethod
    def _decode_profile(payload: Mapping[str, object]) -> CachedCompactProfile:
        sectors = _text_list(payload.get("sectors"))
        constraints = _text_list(payload.get("constraints"))
        response_pref = payload.get("response_pref", "balanced")
        profile_version = payload.get("profile_version")
        if not isinstance(response_pref, str) or not isinstance(profile_version, str):
            raise ValueError("profile strings are invalid")
        return CachedCompactProfile(
            profile_version=profile_version,
            risk_level=_optional_text(payload.get("risk_level")),
            investment_horizon=_optional_text(payload.get("investment_horizon")),
            expected_return_min=_optional_float(payload.get("expected_return_min")),
            expected_return_max=_optional_float(payload.get("expected_return_max")),
            sectors=sectors,
            constraints=constraints,
            response_pref=response_pref,
        )

    @staticmethod
    def _decode_working_state(payload: Mapping[str, object]) -> WorkingState:
        active_payload = payload.get("active_entity")
        active = _working_entity(active_payload) if active_payload is not None else None
        candidates_payload = payload.get("candidate_entities")
        if not isinstance(candidates_payload, list):
            raise ValueError("candidate entities are invalid")
        updated_at_value = payload.get("updated_at")
        if updated_at_value is not None and not isinstance(updated_at_value, str):
            raise ValueError("working-state timestamp is invalid")
        schema_version = _required_text(payload.get("schema_version"))
        if schema_version != MEMORY_SCHEMA_VERSION:
            raise ValueError("working-state schema version is invalid")
        return WorkingState(
            active_entity=active,
            candidate_entities=tuple(_working_entity(item) for item in candidates_payload),
            constraints=_text_list(payload.get("constraints")),
            reply_preference_hint=_strict_text(payload.get("reply_preference_hint")),
            scope=MemoryScope(_required_text(payload.get("scope"))),
            state_version=_strict_int(payload["state_version"]),
            schema_version=schema_version,
            source_message_id=_optional_int(payload.get("source_message_id")),
            updated_at=datetime.fromisoformat(updated_at_value) if updated_at_value else None,
        )

    def _mark_error(self, exc: Exception, *, stage: str) -> None:
        self._metrics["errors"] += 1
        self._last_error_code = CacheErrorCode.UNAVAILABLE
        logger.warning(
            "memory_cache_failed stage=%s status=%s error_code=%s error_type=%s",
            stage,
            "DEGRADED",
            CacheErrorCode.UNAVAILABLE.value,
            type(exc).__name__,
        )


def _strict_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("integer field is invalid")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _strict_int(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("text field is invalid")
    return value


def _required_text(value: object) -> str:
    """读取必填非空字符串，禁止用 ``str`` 掩盖坏 JSON 类型。"""
    if not isinstance(value, str) or not value:
        raise ValueError("required text field is invalid")
    return value


def _strict_text(value: object) -> str:
    """读取允许为空但不允许隐式类型转换的字符串字段。"""
    if not isinstance(value, str):
        raise ValueError("text field is invalid")
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric field is invalid")
    return float(value)


def _text_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("text list is invalid")
    return tuple(value)


def _working_entity(value: object) -> WorkingEntity:
    if not isinstance(value, dict):
        raise ValueError("working entity is invalid")
    symbol = value.get("symbol")
    name = value.get("name")
    entity_type = value.get("entity_type")
    if not all(isinstance(item, str) for item in (symbol, name, entity_type)):
        raise ValueError("working entity fields are invalid")
    return WorkingEntity(
        symbol=cast(str, symbol),
        name=cast(str, name),
        entity_type=cast(str, entity_type),
    )
