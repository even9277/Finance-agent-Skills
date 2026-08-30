"""定义受控对话领域向外依赖的 Ports。"""

from __future__ import annotations

from typing import Protocol

from .contracts import (
    ConversationRequest,
    ConversationResult,
    ModelSynthesisRequest,
    SkillRerankRequest,
    SkillRerankResult,
    ToolCall,
    ToolObservation,
    WorkflowEvent,
)


class ModelPort(Protocol):
    """隔离具体 LLM 供应商的结构化总结边界。"""

    async def synthesize(self, request: ModelSynthesisRequest) -> str:
        """仅使用已验收 AnswerContextPack 生成回答。"""
        ...


class ToolPort(Protocol):
    """执行经过权限和计划校验的只读金融工具。"""

    async def execute(self, call: ToolCall) -> ToolObservation:
        """执行一个只读调用；瞬时超时应抛出 `ToolTimeoutError`。"""
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
