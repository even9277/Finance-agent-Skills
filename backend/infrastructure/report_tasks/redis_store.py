"""用 Redis 镜像报告最新快照并发送可丢弃的版本唤醒通知。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from backend.application.report_tasks.contracts import ReportTaskSnapshot

logger = logging.getLogger(__name__)

REPORT_TASK_CACHE_SCHEMA_VERSION = "report-task-cache-v1"
REPORT_TASK_REDIS_UNAVAILABLE = "REPORT_TASK_REDIS_UNAVAILABLE"
REPORT_TASK_REDIS_INVALID_PAYLOAD = "REPORT_TASK_REDIS_INVALID_PAYLOAD"


class AsyncRedisPubSub(Protocol):
    """收窄 redis-py PubSub 到报告运行时实际使用的命令。"""

    async def subscribe(self, *channels: str) -> object: ...

    async def unsubscribe(self, *channels: str) -> object: ...

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float | None,
    ) -> Mapping[str, object] | None: ...

    async def aclose(self) -> None: ...


class AsyncRedisClient(Protocol):
    """收窄 redis-py 客户端到报告快照所需的异步命令。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> object: ...

    async def delete(self, *keys: str) -> int: ...

    async def publish(self, channel: str, message: str) -> int: ...

    async def ping(self) -> object: ...

    async def aclose(self) -> None: ...

    def pubsub(self) -> AsyncRedisPubSub: ...


@dataclass(frozen=True, slots=True)
class ReportTaskRedisConfig:
    """定义报告 Redis 派生数据的命名空间与过期时间。"""

    namespace: str
    ttl_sec: int

    def __post_init__(self) -> None:
        normalized = self.namespace.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("report Redis namespace 不能为空或包含空白")
        if self.ttl_sec < 1:
            raise ValueError("report Redis ttl_sec 必须为正整数")
        object.__setattr__(self, "namespace", normalized)


@dataclass(frozen=True, slots=True)
class ReportTaskVersionNotification:
    """表示某任务有更高持久化版本可从数据库或 Redis 读取。"""

    task_id: str
    snapshot_version: int


class ReportTaskRedisSubscription:
    """管理一个任务摘要频道的订阅及确定性资源释放。"""

    def __init__(
        self,
        *,
        task_id: str,
        task_ref: str,
        channel: str,
        pubsub: AsyncRedisPubSub,
        owner: RedisReportTaskSnapshotStore,
    ) -> None:
        self._task_id = task_id
        self._task_ref = task_ref
        self._channel = channel
        self._pubsub = pubsub
        self._owner = owner
        self._degraded = False

    async def receive(self) -> ReportTaskVersionNotification:
        """等待下一条合法版本通知；连接失败后保持可取消等待供 DB 对账。"""
        while True:
            if self._degraded:
                await asyncio.Future()
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=None,
                )
            except Exception as exc:
                self._owner.mark_error(exc, stage="report.redis.pubsub.receive")
                self._degraded = True
                continue
            if message is None:
                continue
            try:
                data = message.get("data")
                if not isinstance(data, str):
                    raise ValueError("PubSub payload 必须是文本")
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    raise ValueError("PubSub payload 必须是对象")
                if payload.get("schema_version") != REPORT_TASK_CACHE_SCHEMA_VERSION:
                    raise ValueError("PubSub schema 不匹配")
                if payload.get("task_ref") != self._task_ref:
                    raise ValueError("PubSub task_ref 不匹配")
                version = _strict_positive_int(payload.get("snapshot_version"))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self._owner.mark_malformed()
                continue
            self._owner.mark_notification_received()
            return ReportTaskVersionNotification(
                task_id=self._task_id,
                snapshot_version=version,
            )

    async def close(self) -> None:
        """退订并关闭专用 PubSub 连接，不影响共享 Redis client。"""
        try:
            await self._pubsub.unsubscribe(self._channel)
        except Exception as exc:
            self._owner.mark_error(exc, stage="report.redis.pubsub.unsubscribe")
        try:
            await self._pubsub.aclose()
        except Exception as exc:
            self._owner.mark_error(exc, stage="report.redis.pubsub.close")

    def mark_degraded(self) -> None:
        """让订阅停止重连并等待调用方的周期数据库对账。"""
        self._degraded = True


class RedisReportTaskSnapshotStore:
    """保存严格版本化低敏快照，并把所有 Redis 故障收敛为降级。"""

    def __init__(self, client: AsyncRedisClient, config: ReportTaskRedisConfig) -> None:
        self._client = client
        self._config = config
        self._metrics = {
            "hits": 0,
            "misses": 0,
            "malformed": 0,
            "errors": 0,
            "sets": 0,
            "publishes": 0,
            "notifications_received": 0,
            "subscriptions_opened": 0,
            "subscriptions_closed": 0,
            "reconciles": 0,
            "rebuilds": 0,
        }
        self._last_error_code: str | None = None

    async def set_snapshot(
        self,
        *,
        user_id: str,
        key_digest: str,
        request_fingerprint: str,
        snapshot: ReportTaskSnapshot,
    ) -> bool:
        """写入不含用户、幂等键、请求正文和报告正文的快照镜像。"""
        envelope = {
            "schema_version": REPORT_TASK_CACHE_SCHEMA_VERSION,
            "owner_ref": self._ref(user_id),
            "key_ref": self._ref(key_digest),
            "fingerprint_ref": self._ref(request_fingerprint),
            "task_ref": self._ref(snapshot.task_id),
            "snapshot_version": snapshot.snapshot_version,
            "payload": snapshot.model_dump(mode="json"),
        }
        try:
            await self._client.set(
                self._snapshot_key(user_id, key_digest, request_fingerprint),
                json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                ex=self._config.ttl_sec,
            )
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.snapshot.write")
            return False
        self._metrics["sets"] += 1
        self._last_error_code = None
        return True

    async def get_snapshot(
        self,
        *,
        user_id: str,
        key_digest: str,
        request_fingerprint: str,
    ) -> ReportTaskSnapshot | None:
        """按所有权材料读取镜像；未命中、损坏或 Redis 故障均要求回源数据库。"""
        key = self._snapshot_key(user_id, key_digest, request_fingerprint)
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.snapshot.read")
            return None
        if raw is None:
            self._metrics["misses"] += 1
            return None
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("snapshot envelope 必须是对象")
            if envelope.get("schema_version") != REPORT_TASK_CACHE_SCHEMA_VERSION:
                raise ValueError("snapshot schema 不匹配")
            if envelope.get("owner_ref") != self._ref(user_id):
                raise ValueError("snapshot owner 不匹配")
            if envelope.get("key_ref") != self._ref(key_digest):
                raise ValueError("snapshot key 不匹配")
            if envelope.get("fingerprint_ref") != self._ref(request_fingerprint):
                raise ValueError("snapshot fingerprint 不匹配")
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("snapshot payload 必须是对象")
            snapshot = ReportTaskSnapshot.model_validate(payload)
            if envelope.get("task_ref") != self._ref(snapshot.task_id):
                raise ValueError("snapshot task 不匹配")
            if envelope.get("snapshot_version") != snapshot.snapshot_version:
                raise ValueError("snapshot version 不一致")
        except (TypeError, ValueError, json.JSONDecodeError):
            await self._safe_delete(key)
            self._metrics["malformed"] += 1
            self._last_error_code = REPORT_TASK_REDIS_INVALID_PAYLOAD
            return None
        self._metrics["hits"] += 1
        self._last_error_code = None
        return snapshot

    async def publish_version(self, task_id: str, snapshot_version: int) -> bool:
        """只发布任务摘要和版本，不发布报告内容或用户/幂等材料。"""
        task_ref = self._ref(task_id)
        payload = json.dumps(
            {
                "schema_version": REPORT_TASK_CACHE_SCHEMA_VERSION,
                "task_ref": task_ref,
                "snapshot_version": snapshot_version,
            },
            separators=(",", ":"),
        )
        try:
            await self._client.publish(self._channel(task_id), payload)
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.pubsub.publish")
            return False
        self._metrics["publishes"] += 1
        self._last_error_code = None
        return True

    @asynccontextmanager
    async def subscribe(
        self,
        task_id: str,
    ) -> AsyncIterator[ReportTaskRedisSubscription]:
        """先完成频道订阅再交还控制权，并在退出时释放 PubSub。"""
        pubsub = self._client.pubsub()
        subscription = ReportTaskRedisSubscription(
            task_id=task_id,
            task_ref=self._ref(task_id),
            channel=self._channel(task_id),
            pubsub=pubsub,
            owner=self,
        )
        try:
            await pubsub.subscribe(self._channel(task_id))
            self._metrics["subscriptions_opened"] += 1
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.pubsub.subscribe")
            subscription.mark_degraded()
        try:
            yield subscription
        finally:
            await subscription.close()
            self._metrics["subscriptions_closed"] += 1

    async def health(self) -> dict[str, object]:
        """返回不含 Redis URL、键、频道和业务标识的健康摘要。"""
        try:
            await self._client.ping()
            status = "READY"
            error_code = self._last_error_code
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.health")
            status = "DEGRADED"
            error_code = REPORT_TASK_REDIS_UNAVAILABLE
        return {
            "enabled": True,
            "status": status,
            "error_code": error_code,
            "metrics": dict(self._metrics),
        }

    async def close(self) -> None:
        """关闭 Redis 连接池；关闭异常只影响派生观察层。"""
        try:
            await self._client.aclose()
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.close")

    def mark_error(self, exc: Exception, *, stage: str) -> None:
        """记录稳定降级指标，禁止把地址或业务载荷写入日志。"""
        self._metrics["errors"] += 1
        self._last_error_code = REPORT_TASK_REDIS_UNAVAILABLE
        logger.warning(
            "report_task_redis_failed stage=%s status=%s error_code=%s error_type=%s",
            stage,
            "DEGRADED",
            REPORT_TASK_REDIS_UNAVAILABLE,
            type(exc).__name__,
        )

    def mark_malformed(self) -> None:
        """记录被拒绝的低敏通知，不保留原始 payload。"""
        self._metrics["malformed"] += 1
        self._last_error_code = REPORT_TASK_REDIS_INVALID_PAYLOAD

    def mark_notification_received(self) -> None:
        """记录通过 schema 与任务摘要校验的唤醒通知。"""
        self._metrics["notifications_received"] += 1

    def mark_reconcile(self) -> None:
        """记录一次由 SSE 发起的 PostgreSQL 权威快照对账。"""
        self._metrics["reconciles"] += 1

    def mark_rebuild(self) -> None:
        """记录一次成功把 PostgreSQL 快照重建到 Redis 的操作。"""
        self._metrics["rebuilds"] += 1

    async def _safe_delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:
            self.mark_error(exc, stage="report.redis.snapshot.reject")

    def _snapshot_key(self, user_id: str, key_digest: str, fingerprint: str) -> str:
        material = f"{user_id}:{key_digest}:{fingerprint}"
        return f"{self._config.namespace}:report:v1:snapshot:{self._ref(material)}"

    def _channel(self, task_id: str) -> str:
        return f"{self._config.namespace}:report:v1:notify:{self._ref(task_id)}"

    @staticmethod
    def _ref(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("snapshot_version 必须为正整数")
    return value
