"""集中装配公开聊天入口的生产依赖。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.chat.providers import (
    OpenAICompatibleModelProvider,
    build_read_only_tool_provider,
)
from backend.infrastructure.chat.repository import SqlAlchemyConversationRepository
from backend.infrastructure.chat.trace import SkillTraceSink
from backend.infrastructure.chat.skill_rerank import build_skill_reranker
from backend.infrastructure.memory.runtime import get_memory_cache
from backend.infrastructure.memory.retrieval_repository import SqlAlchemyMemoryRetrievalRepository
from backend.infrastructure.memory.semantic_provider import get_semantic_provider
from backend.infrastructure.memory.observability import MemoryTraceSink
from backend.application.memory.observability import memory_metrics
from backend.application.memory.retrieval import MemoryRetrievalUseCase
from backend.application.memory.commands import MemoryCommandUseCase
from backend.config import settings
from src.conversation.workflow import ControlledConversationWorkflow
from src.skills.skill_registry import get_skill_registry

from .session_use_case import ChatSessionUseCase
from .use_case import ControlledChatUseCase


def build_chat_use_case(db: AsyncSession) -> ControlledChatUseCase:
    """为一个请求数据库 Session 装配唯一受控聊天用例。"""
    repository = SqlAlchemyConversationRepository(db, cache=get_memory_cache())
    # 进程级 Registry 保留最近一次合法快照；每个请求仍固定读取同一不可变 snapshot。
    registry = get_skill_registry()
    registry_snapshot = registry.runtime_snapshot()
    workflow = ControlledConversationWorkflow(
        model=OpenAICompatibleModelProvider(),
        tool=build_read_only_tool_provider(),
        trace=SkillTraceSink(),
        skill_catalog=registry.conversation_snapshot(registry_snapshot),
        skill_loader=registry.get_loader(registry_snapshot),
        skill_reranker=build_skill_reranker(),
        skill_rerank_top_k=settings.skill_rerank_top_k,
    )
    retrieval = None
    if settings.enable_memory:
        retrieval = MemoryRetrievalUseCase(
            SqlAlchemyMemoryRetrievalRepository(
                db,
                semantic_timeout_sec=settings.memory_semantic_timeout_sec,
                semantic_top_k=settings.memory_semantic_top_k,
                semantic_min_score=settings.memory_semantic_min_score,
            ),
            get_semantic_provider(),
        )
    return ControlledChatUseCase(
        workflow=workflow,
        repository=repository,
        retrieval=retrieval,
        retrieval_top_k=settings.memory_retrieval_top_k,
        retrieval_token_budget=settings.memory_retrieval_token_budget,
        memory_commands=MemoryCommandUseCase(db) if settings.enable_memory else None,
        memory_observer=MemoryTraceSink(metrics=memory_metrics),
    )


def build_chat_session_use_case(db: AsyncSession) -> ChatSessionUseCase:
    """为一个请求数据库 Session 装配会话管理用例。"""
    return ChatSessionUseCase(SqlAlchemyConversationRepository(db, cache=get_memory_cache()))
