"""离线 Compose 验收专用 FastAPI 应用装配。"""

import asyncio
import os
from itertools import pairwise
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
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
from backend.services import agent_service
from src.conversation.workflow import ControlledConversationWorkflow
from src.skills.skill_registry import SkillRegistry

__all__ = ["app"]


class OfflineReportState(TypedDict):
    """约束确定性报告工作流在节点之间传递的最小状态。"""

    messages: list[object]
    data: dict[str, Any]
    metadata: dict[str, Any]


def _model_chunk_delay_seconds() -> float:
    """读取浏览器停止语义验收专用的确定性模型延迟。"""
    raw_value = os.getenv("OFFLINE_E2E_MODEL_CHUNK_DELAY_SECONDS", "0")
    try:
        return max(0.0, float(raw_value))
    except ValueError as exc:
        raise RuntimeError("OFFLINE_E2E_MODEL_CHUNK_DELAY_SECONDS 必须为非负数") from exc


def _report_stage_delay_seconds() -> float:
    """读取报告 SSE 订阅建立前后的确定性节点延迟。"""
    raw_value = os.getenv("OFFLINE_E2E_REPORT_STAGE_DELAY_SECONDS", "0.08")
    try:
        return max(0.0, float(raw_value))
    except ValueError as exc:
        raise RuntimeError("OFFLINE_E2E_REPORT_STAGE_DELAY_SECONDS 必须为非负数") from exc


def build_offline_chat_use_case(db: AsyncSession) -> ControlledChatUseCase:
    """只替换外部 Model/Tool/Trace Ports，保留真实工作流与数据库 Repository。"""
    registry = SkillRegistry()
    runtime = registry.runtime_snapshot()
    return ControlledChatUseCase(
        workflow=ControlledConversationWorkflow(
            model=FakeModelProvider(chunk_delay_seconds=_model_chunk_delay_seconds()),
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


async def _build_offline_report_initial_state(
    command: str,
    user_id: str = "",
) -> OfflineReportState:
    """构造不访问股票或模型 Provider 的确定性报告输入。"""
    # 留出订阅建立窗口，同时保留生产后台任务与 SSE Hub 的真实竞态边界。
    await asyncio.sleep(_report_stage_delay_seconds())
    return {
        "messages": [],
        "data": {
            "query": command,
            "company_name": "贵州茅台",
            "stock_code": "sh.600519",
        },
        "metadata": {"offline_fixture": True, "memory_user_id": user_id},
    }


async def _run_offline_report_stage(state: OfflineReportState) -> OfflineReportState:
    """执行单个确定性节点并原样传递状态。"""
    await asyncio.sleep(_report_stage_delay_seconds())
    return state


async def _summarize_offline_report(state: OfflineReportState) -> OfflineReportState:
    """生成不含密钥或外部响应的固定 Markdown 报告。"""
    await asyncio.sleep(_report_stage_delay_seconds())
    data = dict(state.get("data") or {})
    data.update(
        {
            "final_report": (
                "# 离线报告\n\n"
                "该内容由确定性 LangGraph 测试节点生成，仅用于验证报告进度链路。"
            ),
            "report_path": "offline-e2e-report",
        }
    )
    return {**state, "data": data}


def build_offline_report_workflow() -> Any:
    """编译与生产阶段同名的确定性 LangGraph 报告工作流。

    Returns:
        支持 ``astream_events``/``ainvoke`` 的已编译 LangGraph；节点事件由
        LangGraph 真实产生，外部模型、行情和新闻 Provider 均不会被调用。
    """
    workflow = StateGraph(OfflineReportState)
    analyst_nodes = (
        "fundamental_analyst",
        "technical_analyst",
        "value_analyst",
        "news_analyst",
    )
    for node_name in analyst_nodes:
        workflow.add_node(node_name, _run_offline_report_stage)
    workflow.add_node("summarizer", _summarize_offline_report)
    workflow.set_entry_point(analyst_nodes[0])
    for current_node, next_node in pairwise(analyst_nodes):
        workflow.add_edge(current_node, next_node)
    workflow.add_edge(analyst_nodes[-1], "summarizer")
    workflow.add_edge("summarizer", END)
    return workflow.compile()


# 仅测试镜像导入此模块；生产始终使用 factory 中的真实 Ports。
chat_router.build_chat_use_case = build_offline_chat_use_case
agent_service._build_initial_state = _build_offline_report_initial_state
agent_service._get_workflow = build_offline_report_workflow
