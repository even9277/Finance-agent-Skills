"""离线 Compose 验收专用 FastAPI 应用装配。"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.chat.use_case import ControlledChatUseCase
from backend.infrastructure.chat.repository import SqlAlchemyConversationRepository
from backend.infrastructure.chat.testing import FakeModelProvider, FakeToolProvider
from backend.infrastructure.chat.trace import SkillTraceSink
from backend.infrastructure.memory.runtime import get_memory_cache
from backend.infrastructure.memory.retrieval_repository import SqlAlchemyMemoryRetrievalRepository
from backend.infrastructure.memory.semantic_provider import PgVectorSemanticProvider
from backend.application.memory.retrieval import MemoryRetrievalUseCase
from backend.application.memory.commands import MemoryCommandUseCase
from backend.application.memory.observability import memory_metrics
from backend.infrastructure.memory.observability import MemoryTraceSink
from backend.db.database import AsyncSessionFactory
from backend.main import app
from backend.routers import chat as chat_router
from src.conversation.workflow import ControlledConversationWorkflow
from src.skills.skill_registry import SkillRegistry

__all__ = ["app"]


def build_offline_chat_use_case(db: AsyncSession) -> ControlledChatUseCase:
    """只替换外部 Model/Tool/Trace Ports，保留真实工作流与数据库 Repository。"""
    registry = SkillRegistry()
    runtime = registry.runtime_snapshot()
    return ControlledChatUseCase(
        workflow=ControlledConversationWorkflow(
            model=FakeModelProvider(),
            tool=FakeToolProvider(),
            trace=SkillTraceSink(),
            skill_catalog=registry.conversation_snapshot(runtime),
            skill_loader=registry.get_loader(runtime),
        ),
        repository=SqlAlchemyConversationRepository(db, cache=get_memory_cache()),
        retrieval=MemoryRetrievalUseCase(
            SqlAlchemyMemoryRetrievalRepository(db),
            PgVectorSemanticProvider(AsyncSessionFactory),
        ),
        memory_commands=MemoryCommandUseCase(db),
        memory_observer=MemoryTraceSink(metrics=memory_metrics),
    )


# 仅测试镜像导入此模块；生产始终使用 factory 中的真实 Ports。
chat_router.build_chat_use_case = build_offline_chat_use_case
