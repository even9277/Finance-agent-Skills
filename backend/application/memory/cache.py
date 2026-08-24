"""定义可丢弃记忆热缓存的强类型应用合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Protocol, TypeVar

from src.memory.contracts import WorkingState

CACHE_SCHEMA_VERSION = "memory-cache-v1"


class CacheLookupStatus(StrEnum):
    """描述一次缓存读取的稳定、低基数结果。"""

    HIT = "HIT"
    MISS = "MISS"
    STALE = "STALE"
    MALFORMED = "MALFORMED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class CacheErrorCode(StrEnum):
    """描述不会向前台抛出的缓存失败类别。"""

    UNAVAILABLE = "UNAVAILABLE"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"


@dataclass(frozen=True, slots=True)
class MemoryCacheConfig:
    """保存 Redis 缓存的非敏感运行参数。"""

    namespace: str = "finance-agent"
    ttl_sec: int = 300
    lease_sec: int = 5
    singleflight_wait_ms: int = 40

    def __post_init__(self) -> None:
        if not self.namespace.strip():
            raise ValueError("cache namespace must not be blank")
        if min(self.ttl_sec, self.lease_sec, self.singleflight_wait_ms) < 1:
            raise ValueError("cache TTL, lease and wait settings must be positive")


@dataclass(frozen=True, slots=True)
class CachedConversationContext:
    """缓存一段已提交会话的摘要和未压缩原始尾窗。"""

    turn_count: int
    summary_version: int
    running_summary: str | None
    recent_messages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CachedCompactProfile:
    """缓存聊天注入所需的最小结构化画像。"""

    profile_version: str
    risk_level: str | None = None
    investment_horizon: str | None = None
    expected_return_min: float | None = None
    expected_return_max: float | None = None
    sectors: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    response_pref: str = "balanced"

    def as_chat_mapping(self) -> dict[str, object]:
        """转换为现有聊天工作流消费的只读字段映射。"""
        return {
            "risk_level": self.risk_level,
            "investment_horizon": self.investment_horizon,
            "expected_return_min": self.expected_return_min,
            "expected_return_max": self.expected_return_max,
            "sectors": list(self.sectors),
            "constraints": list(self.constraints),
            "response_pref": self.response_pref,
        }


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CacheLookup(Generic[T]):
    """返回缓存值及其可观测读取状态，不用异常表达可降级故障。"""

    status: CacheLookupStatus
    value: T | None = None
    error_code: CacheErrorCode | None = None


class MemoryHotCache(Protocol):
    """声明聊天和记忆基础设施可选使用的热缓存端口。

    所有方法都以 PostgreSQL 已提交数据为权威来源。读取失败、租约争用或
    缓存内容损坏不得中断前台链路；实现应返回可观测状态或静默降级。
    """

    @property
    def config(self) -> MemoryCacheConfig:
        """返回已经过边界校验的缓存运行参数。

        Returns:
            不含凭证或连接串的缓存行为配置。
        """
        ...

    async def get_context(
        self,
        user_id: str,
        session_id: str,
        *,
        expected_turn_count: int,
        expected_summary_version: int,
    ) -> CacheLookup[CachedConversationContext]:
        """按权威版本读取会话摘要与原始尾窗。

        Args:
            user_id: 租户隔离使用的用户标识，只能经散列进入缓存键。
            session_id: 用户拥有的会话标识，只能经散列进入缓存键。
            expected_turn_count: PostgreSQL 当前已提交轮次数。
            expected_summary_version: PostgreSQL 当前摘要版本。

        Returns:
            带 HIT/MISS/STALE/MALFORMED/DEGRADED 状态的类型化读取结果；
            只有 HIT 才携带可消费快照。
        """
        ...

    async def set_context(
        self, user_id: str, session_id: str, value: CachedConversationContext
    ) -> None:
        """缓存已成功提交的会话上下文快照。

        Args:
            user_id: 快照所属用户。
            session_id: 快照所属会话。
            value: 含权威版本的不可变上下文快照。

        Returns:
            无返回值；缓存写失败不得反转已经成功的权威事务。
        """
        ...

    async def invalidate_context(self, user_id: str, session_id: str) -> None:
        """使会话上下文派生缓存失效。

        Args:
            user_id: 快照所属用户。
            session_id: 快照所属会话。

        Returns:
            无返回值；缓存不可用时必须安全降级。
        """
        ...

    async def get_working_state(
        self,
        user_id: str,
        session_id: str,
        *,
        expected_state_version: int,
    ) -> CacheLookup[WorkingState]:
        """按权威状态版本读取 Working State。

        Args:
            user_id: 状态所属用户。
            session_id: 状态所属会话。
            expected_state_version: PostgreSQL 当前状态版本。

        Returns:
            带稳定状态码的读取结果；版本或 schema 不一致时不返回负载。
        """
        ...

    async def set_working_state(
        self, user_id: str, session_id: str, value: WorkingState
    ) -> None:
        """缓存已成功提交的 Working State。

        Args:
            user_id: 状态所属用户。
            session_id: 状态所属会话。
            value: 已通过领域校验且带版本的状态快照。

        Returns:
            无返回值；缓存写入不参与权威事务成败。
        """
        ...

    async def invalidate_working_state(self, user_id: str, session_id: str) -> None:
        """使指定会话的 Working State 派生缓存失效。

        Args:
            user_id: 状态所属用户。
            session_id: 状态所属会话。

        Returns:
            无返回值；失败时由调用链回源 PostgreSQL。
        """
        ...

    async def get_profile(
        self, user_id: str, *, expected_profile_version: str
    ) -> CacheLookup[CachedCompactProfile]:
        """按权威更新时间版本读取聊天所需紧凑画像。

        Args:
            user_id: 画像所属用户。
            expected_profile_version: PostgreSQL 权威画像版本。

        Returns:
            带稳定状态码的紧凑画像读取结果。
        """
        ...

    async def set_profile(self, user_id: str, value: CachedCompactProfile) -> None:
        """缓存聊天注入所需的最小画像字段。

        Args:
            user_id: 画像所属用户。
            value: 不含完整记忆正文的紧凑画像。

        Returns:
            无返回值；只允许在权威读取或提交成功后调用。
        """
        ...

    async def invalidate_profile(self, user_id: str) -> None:
        """使指定用户的紧凑画像缓存失效。

        Args:
            user_id: 画像所属用户。

        Returns:
            无返回值；失效失败不得反转权威写操作。
        """
        ...

    async def acquire_fill_lease(
        self, kind: str, user_id: str, resource_id: str | None = None
    ) -> str | None:
        """尝试获取防击穿短租约。

        Args:
            kind: 低基数缓存类型，如 context。
            user_id: 资源所属用户。
            resource_id: 可选的会话等资源标识。

        Returns:
            成功时返回本次领取唯一 token；争用或缓存不可用时返回 None，
            调用方必须继续走权威回源而不能把它解释为业务失败。
        """
        ...

    async def release_fill_lease(
        self,
        kind: str,
        user_id: str,
        resource_id: str | None,
        token: str,
    ) -> None:
        """以 compare-and-delete 释放调用方持有的短租约。

        Args:
            kind: 领取时使用的缓存类型。
            user_id: 资源所属用户。
            resource_id: 领取时使用的可选资源标识。
            token: acquire_fill_lease 返回的唯一所有权 token。

        Returns:
            无返回值；错误 token 或已过期 token 不能删除新持有者的租约。
        """
        ...

    async def health(self) -> dict[str, object]:
        """返回不含连接串、租户标识或缓存内容的健康摘要。

        Returns:
            包含 enabled、status、error_code 和低基数 metrics 的映射。
        """
        ...

    async def close(self) -> None:
        """释放缓存客户端连接资源。

        Returns:
            无返回值；关闭失败不得阻止应用其余资源清理。
        """
        ...
