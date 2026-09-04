"""D05 受保护真实模型与只读 Tushare 报告 SSE 验收入口。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.application.report_progress.contracts import (  # noqa: E402
    ReportProgressMessage,
    ReportProgressNotification,
    ReportStage,
    ReportStageStatus,
    ReportTerminalNotification,
)
from backend.application.report_progress.hub import report_progress_hub  # noqa: E402
from backend.application.report_progress.snapshot import (  # noqa: E402
    project_report_snapshot,
)
from backend.config import settings  # noqa: E402
from backend.db.database import Base  # noqa: E402
from backend.db.models import Report, User  # noqa: E402
from backend.routers import report as report_router  # noqa: E402
from backend.services import agent_service  # noqa: E402
from src.tools.chat_tushare_tools import get_tushare_toolkit  # noqa: E402
from src.tools.tushare_client import (  # noqa: E402
    TushareClient,
    configure_tushare_client_factory,
)
from src.utils.execution_logger import (  # noqa: E402
    initialize_execution_logger as initialize_real_execution_logger,
)

_LIVE_SWITCH = "RUN_PROTECTED_LIVE_REPORT_E2E"
_CASE_ID = "d05-live-report-01"
_USER_ID = "d05-protected-live-user"
_COMMAND = "请分析贵州茅台（600519），基于可核对数据生成一份审慎的完整投研报告。"
_ALLOWED_TUSHARE_METHODS = frozenset(
    {
        "stock_basic",
        "daily",
        "fina_indicator",
        "income",
        "balancesheet",
        "cashflow",
        "fund_basic",
        "fund_nav",
        "fund_daily",
        "fund_share",
        "etf_basic",
        "index_classify",
        "sw_daily",
        "index_member",
        "pro_bar",
    }
)


def _require_protected_live_configuration() -> None:
    """拒绝误触发或缺少凭证的伪 Live 成功。"""
    if os.getenv(_LIVE_SWITCH, "").strip().lower() != "true":
        pytest.skip(f"需要显式设置 {_LIVE_SWITCH}=true")

    required = {
        "OPENAI_COMPATIBLE_API_KEY": settings.openai_compatible_api_key,
        "OPENAI_COMPATIBLE_BASE_URL": settings.openai_compatible_base_url,
        "OPENAI_COMPATIBLE_MODEL": settings.openai_compatible_model,
        "TUSHARE_TOKEN": settings.tushare_token,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        pytest.fail("保护性 Live 报告测试缺少必需配置：" + ", ".join(missing))


class _LowSensitivityModelAudit(BaseCallbackHandler):
    """只统计真实模型 run，不保存 Prompt、回答或鉴权配置。"""

    def __init__(self) -> None:
        self._run_ids: set[str] = set()

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """记录一次文本模型启动，忽略实际输入。"""
        del serialized, prompts, kwargs
        self._run_ids.add(str(run_id))

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """记录一次聊天模型启动，忽略实际消息。"""
        del serialized, messages, kwargs
        self._run_ids.add(str(run_id))

    @property
    def call_count(self) -> int:
        """返回去重后的真实模型 run 数。"""
        return len(self._run_ids)


class _AuditedWorkflow:
    """审计整图执行次数，防止根输出缺失触发整报告重跑。"""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.stream_call_count = 0
        self.fallback_invoke_count = 0

    async def astream_events(
        self,
        input_state: Any,
        *,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """转发真实 LangGraph 事件流并统计唯一整图调用。"""
        self.stream_call_count += 1
        async for event in self._delegate.astream_events(input_state, version=version):
            yield event

    async def ainvoke(self, input_state: Any) -> Any:
        """记录不应发生的整图回退调用。"""
        self.fallback_invoke_count += 1
        return await self._delegate.ainvoke(input_state)


async def _prepare_database(
    engine: Any,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    report_id: str,
) -> None:
    """创建一次性 SQLite 数据库及报告所有者。"""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(User(id=_USER_ID, display_name="D05 protected live report"))
        session.add(
            Report(
                id=report_id,
                task_id=task_id,
                user_id=_USER_ID,
                status="pending",
                progress=0,
            )
        )
        await session.commit()


async def _load_report(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
) -> Report:
    """读取隔离数据库中的权威报告终态。"""
    async with session_factory() as session:
        result = await session.execute(select(Report).where(Report.task_id == task_id))
        report = result.scalar_one()
        session.expunge(report)
        return report


async def _run_and_observe_report(
    *,
    task_id: str,
    report_id: str,
) -> list[ReportProgressMessage]:
    """订阅 Hub 后仅执行一次真实报告，并读取至唯一终态。"""
    received: list[ReportProgressMessage] = []
    async with report_progress_hub.subscribe(task_id) as subscription:
        report_task = asyncio.create_task(
            agent_service.run_report_task(
                task_id=task_id,
                report_id=report_id,
                command=_COMMAND,
                user_id=_USER_ID,
            )
        )
        while True:
            message = await asyncio.wait_for(subscription.receive(), timeout=720)
            received.append(message)
            if isinstance(message, ReportTerminalNotification):
                break
        await asyncio.wait_for(report_task, timeout=30)
    return received


async def _read_terminal_sse_frames(report: Report) -> list[Any]:
    """从生产 SSE producer 读取已完成报告的首帧和终态帧。"""
    snapshot = project_report_snapshot(
        task_id=report.task_id,
        report_id=report.id,
        user_id=report.user_id,
        status=report.status,
        progress=report.progress,
    )
    frames: list[Any] = []
    async for event in report_router._report_event_stream(snapshot):
        frames.append(event.data)
    return frames


def _model_factory(audit: _LowSensitivityModelAudit) -> Any:
    """构造附带低敏 callback 的真实 OpenAI-compatible 客户端工厂。"""

    def create_model(*args: Any, **kwargs: Any) -> ChatOpenAI:
        callbacks = list(kwargs.pop("callbacks", []) or [])
        callbacks.append(audit)
        return ChatOpenAI(*args, callbacks=callbacks, **kwargs)

    return create_model


async def _tushare_tools() -> list[Any]:
    """向旧报告 Agent 暴露仓库现有的只读 Tushare toolkit。"""
    return get_tushare_toolkit()


async def _resolve_live_stock(query: str) -> tuple[str, str]:
    """固定 Live 标的，避免把 D05 进度验收扩展为实体解析验收。"""
    del query
    return "贵州茅台", "sh.600519"


def _scan_text_artifacts(paths: Sequence[Path], forbidden: Sequence[str]) -> None:
    """确认测试文本产物没有写入真实凭证。"""
    for path in paths:
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md", ".log", ".txt"}:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for secret in forbidden:
                assert secret.lower() not in text, f"敏感配置出现在临时产物：{path.name}"


@pytest.mark.live
@pytest.mark.e2e
def test_live_report_streams_real_model_and_read_only_tushare_once(
    tmp_path: Path,
) -> None:
    """D05-T09：一条真实报告必须在预算内产生真实阶段、终态和脱敏证据。"""
    _require_protected_live_configuration()

    task_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())
    database_path = tmp_path / "d05-live-report.db"
    execution_root = tmp_path / "runtime"
    acceptance_path = tmp_path / "d05-live-report-acceptance.json"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    asyncio.run(
        _prepare_database(
            engine,
            session_factory,
            task_id=task_id,
            report_id=report_id,
        )
    )

    model_audit = _LowSensitivityModelAudit()
    tushare_calls: list[str] = []
    real_call_api_once = TushareClient._call_api_once
    real_call_pro_bar_once = TushareClient._call_pro_bar_once

    async def audited_call_api_once(
        client: TushareClient,
        method_name: str,
        **kwargs: Any,
    ) -> Any:
        """只允许并记录冻结白名单中的 Tushare 查询 API。"""
        assert method_name in _ALLOWED_TUSHARE_METHODS
        tushare_calls.append(method_name)
        return await real_call_api_once(client, method_name, **kwargs)

    async def audited_call_pro_bar_once(client: TushareClient, **kwargs: Any) -> Any:
        """记录只读复权行情查询，不保留参数或返回值。"""
        tushare_calls.append("pro_bar")
        return await real_call_pro_bar_once(client, **kwargs)

    fundamental_module = importlib.import_module("src.agents.fundamental_agent")
    technical_module = importlib.import_module("src.agents.technical_agent")
    value_module = importlib.import_module("src.agents.value_agent")
    news_module = importlib.import_module("src.agents.news_agent")
    summary_module = importlib.import_module("src.agents.summary_agent")

    previous_tushare_token = os.environ.get("TUSHARE_TOKEN")
    os.environ["TUSHARE_TOKEN"] = settings.tushare_token
    configure_tushare_client_factory(None)
    agent_service._COMPILED_WORKFLOW = None
    started_at = time.perf_counter()
    try:
        with (
            patch.object(settings, "enable_stm", False),
            patch.object(settings, "enable_memory", False),
            patch.object(agent_service, "resolve_stock", new=_resolve_live_stock),
            patch.object(
                importlib.import_module("backend.db.database"),
                "AsyncSessionFactory",
                session_factory,
            ),
            patch.object(
                agent_service,
                "initialize_execution_logger",
                side_effect=lambda **_: initialize_real_execution_logger(
                    base_log_dir=str(execution_root / "logs")
                ),
            ),
            patch.object(
                summary_module,
                "__file__",
                str(execution_root / "src/agents/summary_agent.py"),
            ),
            patch.object(TushareClient, "_call_api_once", new=audited_call_api_once),
            patch.object(TushareClient, "_call_pro_bar_once", new=audited_call_pro_bar_once),
            patch.object(fundamental_module, "get_mcp_tools", new=_tushare_tools),
            patch.object(technical_module, "get_mcp_tools", new=_tushare_tools),
            patch.object(value_module, "get_mcp_tools", new=_tushare_tools),
            patch.object(news_module, "get_mcp_tools", new=_tushare_tools),
            patch.object(fundamental_module, "ChatOpenAI", new=_model_factory(model_audit)),
            patch.object(technical_module, "ChatOpenAI", new=_model_factory(model_audit)),
            patch.object(value_module, "ChatOpenAI", new=_model_factory(model_audit)),
            patch.object(news_module, "ChatOpenAI", new=_model_factory(model_audit)),
            patch.object(summary_module, "ChatOpenAI", new=_model_factory(model_audit)),
        ):
            compiled = agent_service._get_workflow()
            audited_workflow = _AuditedWorkflow(compiled)
            with patch.object(agent_service, "_get_workflow", return_value=audited_workflow):
                messages = asyncio.run(
                    _run_and_observe_report(task_id=task_id, report_id=report_id)
                )
            report = asyncio.run(_load_report(session_factory, task_id=task_id))
            sse_frames = asyncio.run(_read_terminal_sse_frames(report))
    finally:
        agent_service._COMPILED_WORKFLOW = None
        configure_tushare_client_factory(None)
        if previous_tushare_token is None:
            os.environ.pop("TUSHARE_TOKEN", None)
        else:
            os.environ["TUSHARE_TOKEN"] = previous_tushare_token
        asyncio.run(engine.dispose())

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    assert elapsed_ms < 720_000
    assert audited_workflow.stream_call_count == 1
    assert audited_workflow.fallback_invoke_count == 0
    assert model_audit.call_count >= 5
    assert tushare_calls
    assert set(tushare_calls).issubset(_ALLOWED_TUSHARE_METHODS)

    assert isinstance(messages[-1], ReportTerminalNotification)
    assert messages[-1].status.value == "completed"
    progress = [message.progress for message in messages]
    assert progress == sorted(progress)
    completed_stages = {
        message.stage
        for message in messages
        if isinstance(message, ReportProgressNotification)
        and message.stage_status is ReportStageStatus.SUCCEEDED
    }
    assert {
        ReportStage.PREPARING,
        ReportStage.FUNDAMENTAL_ANALYSIS,
        ReportStage.TECHNICAL_ANALYSIS,
        ReportStage.VALUATION_ANALYSIS,
        ReportStage.NEWS_ANALYSIS,
        ReportStage.SYNTHESIZING,
    }.issubset(completed_stages)

    assert report.status == "completed"
    assert report.progress == 100
    assert report.content
    content_sha256 = hashlib.sha256(report.content.encode("utf-8")).hexdigest()
    assert [frame.type for frame in sse_frames] == ["stream_ready", "task_terminal"]
    assert [frame.sequence for frame in sse_frames] == [1, 2]
    assert sse_frames[-1].status.value == "completed"
    assert all(frame.protocol_version == "report-progress-v1" for frame in sse_frames)

    artifact = {
        "test_id": _CASE_ID,
        "protocol_version": "report-progress-v1",
        "provider": "openai-compatible",
        "model": settings.openai_compatible_model,
        "tool_provider": "tushare-read-only",
        "tushare_methods": sorted(set(tushare_calls)),
        "tushare_call_count": len(tushare_calls),
        "model_call_count": model_audit.call_count,
        "workflow_stream_call_count": audited_workflow.stream_call_count,
        "workflow_fallback_invoke_count": audited_workflow.fallback_invoke_count,
        "stage_events": [
            {
                "stage": message.stage.value,
                "status": message.stage_status.value,
                "progress": message.progress,
            }
            for message in messages
            if isinstance(message, ReportProgressNotification)
        ],
        "progress": progress,
        "terminal": report.status,
        "elapsed_ms": round(elapsed_ms, 2),
        "content_sha256": content_sha256,
        "redaction_check": "passed",
    }
    acceptance_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    serialized_acceptance = acceptance_path.read_text(encoding="utf-8").lower()
    assert _COMMAND.lower() not in serialized_acceptance
    forbidden = (settings.openai_compatible_api_key, settings.tushare_token)
    assert all(secret.lower() not in serialized_acceptance for secret in forbidden)
    _scan_text_artifacts(tuple(tmp_path.rglob("*")), forbidden)
    artifact_sha256 = hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
    print(f"d05_live_artifact={acceptance_path}")
    print(f"d05_live_artifact_sha256={artifact_sha256}")
