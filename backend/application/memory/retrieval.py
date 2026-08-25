"""定义受权威过滤约束的长期记忆混合召回应用合同。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.memory.contracts import MemoryErrorCode, RetrievalResult


@dataclass(frozen=True, slots=True)
class SemanticSearchHit:
    """Provider 返回的最小安全命中，正文不被视为权威内容。"""

    provider_record_id: str
    record_id: str
    user_id: str
    memory_version: int
    score: float
    provider: str


@dataclass(frozen=True, slots=True)
class MemoryRetrievalRequest:
    """描述一次跨会话记忆召回的用户、查询和预算边界。"""

    user_id: str
    query: str
    top_k: int = 8
    token_budget: int = 600
    now: datetime | None = None

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.query.strip():
            raise ValueError("memory retrieval user_id and query must not be blank")
        if self.top_k < 1 or self.token_budget < 1:
            raise ValueError("memory retrieval top_k and token_budget must be positive")


class SemanticMemoryProvider(Protocol):
    """声明可替换的派生语义 Provider，不能直接改变权威记录。"""

    name: str

    async def upsert(
        self,
        *,
        user_id: str,
        record_id: str,
        memory_version: int,
        category: str,
        content: str,
        metadata: dict[str, object],
    ) -> str:
        """写入或更新一条派生索引并返回 Provider ID。"""
        ...

    async def delete(self, *, user_id: str, provider_record_id: str) -> None:
        """删除一条派生索引记录。"""
        ...

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int,
        min_score: float,
    ) -> tuple[SemanticSearchHit, ...]:
        """按用户作用域查询派生索引。"""
        ...


class MemoryRetrievalUseCase:
    """融合 PostgreSQL 词法召回和 Provider 语义召回并执行权威后过滤。"""

    def __init__(self, repository, provider: SemanticMemoryProvider | None) -> None:
        self._repository = repository
        self._provider = provider

    async def execute(self, request: MemoryRetrievalRequest) -> RetrievalResult:
        """执行可降级、限预算、按用户及版本后过滤的混合召回。"""
        return await self._repository.retrieve(request, self._provider)


def retrieval_failure(code: MemoryErrorCode) -> RetrievalResult:
    """构造不泄露底层异常文本的失败结果。"""
    from src.memory.contracts import RetrievalStatus

    return RetrievalResult(status=RetrievalStatus.FAILED, error_code=code)
