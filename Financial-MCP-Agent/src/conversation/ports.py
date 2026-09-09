"""定义受控对话领域向外依赖的 Ports。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .contracts import (
    ConversationRequest,
    ConversationResult,
    Entity,
    EntityModelRequest,
    EntityModelResolution,
    ModelSynthesisChunk,
    ModelSynthesisRequest,
    SkillRerankRequest,
    SkillRerankResult,
    ToolCall,
    ToolObservation,
    ToolPolicy,
    ToolRuntimeLease,
    ToolRuntimeOutcome,
    WorkflowEvent,
)


class EntityResolutionModelPort(Protocol):
    """隔离用于长尾候选提出的受控模型 Adapter。"""

    async def resolve(self, request: EntityModelRequest) -> EntityModelResolution:
        """返回已通过严格结构校验的候选与模型调用预算。"""
        ...


class EntityCatalogPort(Protocol):
    """按 canonical symbol 回查权威金融实体目录。"""

    async def lookup(self, symbol: str) -> Entity | None:
        """返回目录确认实体；不存在时返回 `None`，不可用时抛稳定异常。"""
        ...


class ModelPort(Protocol):
    """隔离具体 LLM 供应商的结构化总结边界。"""

    def stream_synthesize(
        self,
        request: ModelSynthesisRequest,
    ) -> AsyncIterator[ModelSynthesisChunk]:
        """仅使用已验收 AnswerContextPack 生成有序文本增量。"""
        ...


class ToolPort(Protocol):
    """执行经过权限和计划校验的只读金融工具。"""

    async def execute(self, call: ToolCall) -> ToolObservation:
        """执行一个只读调用；瞬时超时应抛出 `ToolTimeoutError`。"""
        ...


class ToolRuntimePort(Protocol):
    """隔离 Executor 与进程内/Redis 工具治理实现。"""

    async def acquire(
        self,
        policy: ToolPolicy,
        *,
        trace_id: str,
    ) -> ToolRuntimeLease:
        """在真实 Provider 调用前取得接口族与熔断许可。"""
        ...

    async def release(
        self,
        lease: ToolRuntimeLease,
        outcome: ToolRuntimeOutcome,
    ) -> None:
        """释放许可并按稳定结果类别更新熔断状态。"""
        ...

    async def wait_before_retry(
        self,
        *,
        attempt: int,
        retry_after_ms: int | None = None,
    ) -> int:
        """执行有界退避并返回实际计划等待毫秒数。"""
        ...

    async def health(self) -> dict[str, object]:
        """返回不含请求载荷或外部地址的低敏运行状态。"""
        ...

    async def close(self) -> None:
        """关闭可选共享资源；本地实现应为空操作。"""
        ...


class TraceSink(Protocol):
    """接收已经结构化且不含原始敏感载荷的阶段事件。"""

    def emit(self, event: WorkflowEvent) -> None:
        """尽力写入事件；Sink 失败不得改变业务结果。"""


class SkillRerankerPort(Protocol):
    """隔离可选在线 Skill rerank，实现不得接收完整 Skill 或历史。"""

    def rerank(self, request: SkillRerankRequest) -> SkillRerankResult:
        """仅重排 Retriever 已裁剪出的 top-K typed 候选。"""
        ...


class ConversationRepositoryPort(Protocol):
    """由 Application 层持有的最终结果持久化边界。"""

    async def save_result(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> None:
        """原子保存一轮请求与唯一终态结果。"""
