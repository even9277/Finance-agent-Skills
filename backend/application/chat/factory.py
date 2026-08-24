"""集中装配公开聊天入口的生产依赖。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.chat.providers import (
    OpenAICompatibleModelProvider,
    StructuredLoggingTraceSink,
    TushareToolProvider,
)
from backend.infrastructure.chat.repository import SqlAlchemyConversationRepository
from src.conversation.workflow import ControlledConversationWorkflow
from src.skills.skill_registry import SkillRegistry

from .session_use_case import ChatSessionUseCase
from .use_case import ControlledChatUseCase


def build_chat_use_case(db: AsyncSession) -> ControlledChatUseCase:
    """为一个请求数据库 Session 装配唯一受控聊天用例。"""
    repository = SqlAlchemyConversationRepository(db)
    workflow = ControlledConversationWorkflow(
        model=OpenAICompatibleModelProvider(),
        tool=TushareToolProvider(),
        trace=StructuredLoggingTraceSink(),
        skill_catalog=SkillRegistry().conversation_snapshot(),
    )
    return ControlledChatUseCase(workflow=workflow, repository=repository)


def build_chat_session_use_case(db: AsyncSession) -> ChatSessionUseCase:
    """为一个请求数据库 Session 装配会话管理用例。"""
    return ChatSessionUseCase(SqlAlchemyConversationRepository(db))
