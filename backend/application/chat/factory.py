"""集中装配公开聊天入口的生产依赖。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.chat.providers import (
    OpenAICompatibleModelProvider,
    TushareToolProvider,
)
from backend.infrastructure.chat.repository import SqlAlchemyConversationRepository
from backend.infrastructure.chat.trace import SkillTraceSink
from backend.infrastructure.memory.runtime import get_memory_cache
from backend.infrastructure.memory.retrieval_repository import SqlAlchemyMemoryRetrievalRepository
from backend.infrastructure.memory.semantic_provider import get_semantic_provider
from backend.application.memory.retrieval import MemoryRetrievalUseCase
from backend.application.memory.commands import MemoryCommandUseCase
from backend.config import settings
from src.conversation.workflow import ControlledConversationWorkflow
from src.skills.skill_registry import SkillRegistry

from .session_use_case import ChatSessionUseCase
from .use_case import ControlledChatUseCase


def build_chat_use_case(db: AsyncSession) -> ControlledChatUseCase:
    """为一个请求数据库 Session 装配唯一受控聊天用例。"""
    repository = SqlAlchemyConversationRepository(db, cache=get_memory_cache())
    workflow = ControlledConversationWorkflow(
        model=OpenAICompatibleModelProvider(),
        tool=TushareToolProvider(),
        trace=SkillTraceSink(),
        skill_catalog=SkillRegistry().conversation_snapshot(),
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
    )


def build_chat_session_use_case(db: AsyncSession) -> ChatSessionUseCase:
    """为一个请求数据库 Session 装配会话管理用例。"""
    return ChatSessionUseCase(SqlAlchemyConversationRepository(db, cache=get_memory_cache()))
