"""装配 D06 单次真实报告、双 ASGI 应用与并发幂等验收。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.config import settings  # noqa: E402
from backend.db.database import Base, get_db  # noqa: E402
from backend.db.models import Report, ReportTaskGovernanceRow, User  # noqa: E402
from backend.middleware.auth import AuthContext, require_auth  # noqa: E402
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

_CASE_ID = "d06-live-report-governance-01"
_DATABASE_ENV = "D06_LIVE_DATABASE_URL"
_INFRA_ACK_ENV = "D06_LIVE_INFRA_ACK"
_USER_ID = "d06-protected-live-user"
_COMMAND = "请分析贵州茅台（600519），基于可核对数据生成一份审慎的完整投研报告。"
_ALLOWED_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost"})
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


@dataclass(frozen=True, slots=True)
class ProtectedLiveReportGovernanceEvidence:
    """保存不含请求正文、用户、凭据或报告正文的 Live 证据。"""

    test_id: str
    request_count: int
    app_instance_count: int
    request_distribution: tuple[int, int]
    unique_task_count: int
    unique_report_count: int
    created_count: int
    replayed_count: int
    workflow_execution_count: int
    workflow_fallback_count: int
    model_call_count: int
    tushare_call_count: int
    tushare_methods: tuple[str, ...]
    snapshot_version: int
    sse_sequences: tuple[int, ...]
    terminal_status: str
    rest_status: str
    content_sha256: str
    idempotency_key_sha256: str
    elapsed_ms: float
    redaction_check: str


class _LowSensitivityModelAudit(BaseCallbackHandler):
    """只统计真实模型 run，不保留 Prompt 或模型响应。"""

    def __init__(self) -> None:
        self._run_ids: set[str] = set()
        self._lock = threading.Lock()

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """记录一次文本模型调用标识并丢弃输入。"""
        del serialized, prompts, kwargs
        with self._lock:
            self._run_ids.add(str(run_id))

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """记录一次聊天模型调用标识并丢弃消息。"""
        del serialized, messages, kwargs
        with self._lock:
            self._run_ids.add(str(run_id))

    @property
    def call_count(self) -> int:
        """返回去重后的真实模型 run 数。"""
        with self._lock:
            return len(self._run_ids)


class _AuditedWorkflow:
    """统计整图入口，拒绝把内部模型调用误算为多次报告执行。"""

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
        """转发真实 LangGraph 事件流并统计一次入口。"""
        self.stream_call_count += 1
        async for event in self._delegate.astream_events(input_state, version=version):
            yield event

    async def ainvoke(self, input_state: Any) -> Any:
        """记录不应出现的整图回退执行。"""
        self.fallback_invoke_count += 1
        return await self._delegate.ainvoke(input_state)


class _DispatchAudit:
    """统计由数据库获胜请求进入真实 BackgroundTask 的次数。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0

    async def run(
        self,
        *,
        task_id: str,
        report_id: str,
        command: str,
        user_id: str,
    ) -> None:
        """计数后原样委托真实报告服务；不记录业务入参。"""
        with self._lock:
            self._count += 1
        await agent_service.run_report_task(
            task_id=task_id,
            report_id=report_id,
            command=command,
            user_id=user_id,
        )

    @property
    def count(self) -> int:
        """返回真实后台派发计数。"""
        with self._lock:
            return self._count


def _require_disposable_database_url() -> str:
    """只接受显式确认的本机一次性 PostgreSQL 数据库。"""
    if os.getenv(_INFRA_ACK_ENV, "").strip().lower() != "disposable":
        raise RuntimeError(f"必须设置 {_INFRA_ACK_ENV}=disposable")
    value = os.getenv(_DATABASE_ENV, "").strip()
    if not value:
        raise RuntimeError(f"缺少 {_DATABASE_ENV}")
    parsed = make_url(value)
    safe = (
        parsed.drivername == "postgresql+asyncpg"
        and parsed.host in _ALLOWED_DATABASE_HOSTS
        and parsed.database == "d06_live"
        and parsed.username == "d06_live"
    )
    if not safe:
        raise RuntimeError("D06 Live 拒绝非本机 d06_live 隔离 PostgreSQL")
    return value


def _require_external_configuration() -> None:
    """确认真实模型和只读 Tushare 所需配置存在但不输出值。"""
    required = {
        "OPENAI_COMPATIBLE_API_KEY": settings.openai_compatible_api_key,
        "OPENAI_COMPATIBLE_BASE_URL": settings.openai_compatible_base_url,
        "OPENAI_COMPATIBLE_MODEL": settings.openai_compatible_model,
        "TUSHARE_TOKEN": settings.tushare_token,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        raise RuntimeError("D06 Live 缺少配置：" + ", ".join(missing))


async def _prepare_database(
    engine: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """在已确认的一次性库创建扩展/表和唯一测试用户。"""
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(User(id=_USER_ID, display_name="D06 protected live report"))
        await session.commit()


def _build_app(
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    """创建一个共享 PostgreSQL、独立依赖表的报告 ASGI 应用。"""
    app = FastAPI()
    app.include_router(report_router.router, prefix="/api/report")

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def override_auth(request: Request) -> AuthContext:
        del request
        return AuthContext(
            account_id="d06-live-account",
            username="d06-live",
            user_id=_USER_ID,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_auth] = override_auth
    return app


def _model_factory(audit: _LowSensitivityModelAudit) -> Any:
    """构造附带低敏 callback 的真实 OpenAI-compatible 客户端。"""

    def create_model(*args: Any, **kwargs: Any) -> ChatOpenAI:
        callbacks = list(kwargs.pop("callbacks", []) or [])
        callbacks.append(audit)
        return ChatOpenAI(*args, callbacks=callbacks, **kwargs)

    return create_model


async def _tushare_tools() -> list[Any]:
    """向真实报告 Agent 暴露仓库现有只读 Tushare toolkit。"""
    return get_tushare_toolkit()


async def _resolve_live_stock(query: str) -> tuple[str, str]:
    """固定已授权标的，避免把 D06 验收扩展为实体解析评测。"""
    del query
    return "贵州茅台", "sh.600519"


def _create_report(
    client: TestClient,
    *,
    idempotency_key: str,
) -> Any:
    """通过真实 FastAPI 路由提交一个相同业务请求。"""
    return client.post(
        "/api/report/generate",
        json={"command": _COMMAND, "user_id": _USER_ID},
        headers={"Idempotency-Key": idempotency_key},
        timeout=720,
    )


def _send_concurrent_requests(
    clients: tuple[TestClient, TestClient],
    *,
    idempotency_key: str,
    request_count: int,
) -> list[tuple[int, Any]]:
    """把同键请求均匀分给两个应用，并在同一屏障后并发提交。"""
    barrier = threading.Barrier(request_count)

    def submit(index: int) -> tuple[int, Any]:
        app_index = index % len(clients)
        barrier.wait(timeout=30)
        return app_index, _create_report(
            clients[app_index],
            idempotency_key=idempotency_key,
        )

    with ThreadPoolExecutor(max_workers=request_count) as executor:
        futures = [executor.submit(submit, index) for index in range(request_count)]
        return [future.result(timeout=750) for future in futures]


def _parse_sse_frames(payload: str) -> list[dict[str, Any]]:
    """解析测试客户端缓冲的有限 SSE 响应。"""
    frames: list[dict[str, Any]] = []
    normalized = payload.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        )
        if data:
            frames.append(json.loads(data))
    return frames


async def _load_database_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    report_id: str,
) -> tuple[Report, ReportTaskGovernanceRow, int, int]:
    """读取唯一报告、治理快照和表级计数。"""
    async with session_factory() as session:
        report = (
            await session.execute(select(Report).where(Report.task_id == task_id))
        ).scalar_one()
        governance = (
            await session.execute(
                select(ReportTaskGovernanceRow).where(ReportTaskGovernanceRow.task_id == task_id)
            )
        ).scalar_one()
        report_count = int(await session.scalar(select(func.count(Report.id))) or 0)
        governance_count = int(
            await session.scalar(select(func.count(ReportTaskGovernanceRow.id))) or 0
        )
        assert report.id == report_id
        session.expunge(report)
        session.expunge(governance)
        return report, governance, report_count, governance_count


def _scan_text_artifacts(paths: Sequence[Path], forbidden: Sequence[str]) -> None:
    """确认临时文本产物不包含真实凭据。"""
    for path in paths:
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md", ".log", ".txt"}:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            for secret in forbidden:
                assert secret.lower() not in content, f"敏感配置出现在临时产物：{path.name}"


def run_protected_live_report_governance_case(
    *,
    request_count: int,
) -> ProtectedLiveReportGovernanceEvidence:
    """执行一次真实报告并证明 20 路双应用重放只派发一次。

    Args:
        request_count: 固定并发请求数，D06 验收只允许 20。

    Returns:
        仅含计数、版本、耗时和哈希的脱敏验收证据。

    Raises:
        ValueError: 请求数不是冻结值 20。
        RuntimeError: 外部凭据或一次性数据库确认缺失。
        AssertionError: 幂等、真实调用、终态、一致性或脱敏断言失败。
    """
    if request_count != 20:
        raise ValueError("D06 protected Live 固定且只允许 20 个创建请求")
    _require_external_configuration()
    database_url = _require_disposable_database_url()

    started_at = time.perf_counter()
    idempotency_key = str(uuid.uuid4())
    model_audit = _LowSensitivityModelAudit()
    dispatch_audit = _DispatchAudit()
    tushare_calls: list[str] = []
    tushare_lock = threading.Lock()
    real_call_api_once = TushareClient._call_api_once
    real_call_pro_bar_once = TushareClient._call_pro_bar_once

    async def audited_call_api_once(
        client: TushareClient,
        method_name: str,
        **kwargs: Any,
    ) -> Any:
        """只允许并统计冻结白名单中的 Tushare 查询。"""
        assert method_name in _ALLOWED_TUSHARE_METHODS
        with tushare_lock:
            tushare_calls.append(method_name)
        return await real_call_api_once(client, method_name, **kwargs)

    async def audited_call_pro_bar_once(client: TushareClient, **kwargs: Any) -> Any:
        """统计只读复权行情查询，不保留参数和返回值。"""
        with tushare_lock:
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

    with tempfile.TemporaryDirectory(prefix="finance-d06-live-") as temporary:
        temporary_root = Path(temporary)
        execution_root = temporary_root / "runtime"
        acceptance_path = temporary_root / "d06-live-acceptance.json"
        engine = create_async_engine(database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        asyncio.run(_prepare_database(engine, session_factory))
        apps = (_build_app(session_factory), _build_app(session_factory))

        try:
            with ExitStack() as stack:
                patchers = (
                    patch.object(settings, "auth_enabled", True),
                    patch.object(settings, "enable_stm", False),
                    patch.object(settings, "enable_memory", False),
                    patch.object(settings, "enable_report_task_governance", True),
                    patch.object(settings, "enable_report_task_redis", False),
                    patch.object(agent_service, "resolve_stock", new=_resolve_live_stock),
                    patch.object(
                        importlib.import_module("backend.db.database"),
                        "AsyncSessionFactory",
                        session_factory,
                    ),
                    patch.object(report_router, "AsyncSessionFactory", session_factory),
                    patch.object(report_router, "run_report_task", new=dispatch_audit.run),
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
                    patch.object(
                        TushareClient,
                        "_call_api_once",
                        new=audited_call_api_once,
                    ),
                    patch.object(
                        TushareClient,
                        "_call_pro_bar_once",
                        new=audited_call_pro_bar_once,
                    ),
                    patch.object(
                        fundamental_module,
                        "get_mcp_tools",
                        new=_tushare_tools,
                    ),
                    patch.object(
                        technical_module,
                        "get_mcp_tools",
                        new=_tushare_tools,
                    ),
                    patch.object(value_module, "get_mcp_tools", new=_tushare_tools),
                    patch.object(news_module, "get_mcp_tools", new=_tushare_tools),
                    patch.object(
                        fundamental_module,
                        "ChatOpenAI",
                        new=_model_factory(model_audit),
                    ),
                    patch.object(
                        technical_module,
                        "ChatOpenAI",
                        new=_model_factory(model_audit),
                    ),
                    patch.object(
                        value_module,
                        "ChatOpenAI",
                        new=_model_factory(model_audit),
                    ),
                    patch.object(
                        news_module,
                        "ChatOpenAI",
                        new=_model_factory(model_audit),
                    ),
                    patch.object(
                        summary_module,
                        "ChatOpenAI",
                        new=_model_factory(model_audit),
                    ),
                )
                for patcher in patchers:
                    stack.enter_context(patcher)

                compiled = agent_service._get_workflow()
                audited_workflow = _AuditedWorkflow(compiled)
                with (
                    patch.object(agent_service, "_get_workflow", return_value=audited_workflow),
                    TestClient(apps[0]) as first_client,
                    TestClient(apps[1]) as second_client,
                ):
                    clients = (first_client, second_client)
                    results = _send_concurrent_requests(
                        clients,
                        idempotency_key=idempotency_key,
                        request_count=request_count,
                    )
                    responses = [response for _, response in results]
                    assert {response.status_code for response in responses} == {200}
                    payloads = [response.json() for response in responses]
                    task_ids = {str(payload["task_id"]) for payload in payloads}
                    report_ids = {str(payload["report_id"]) for payload in payloads}
                    assert len(task_ids) == 1
                    assert len(report_ids) == 1
                    task_id = next(iter(task_ids))
                    report_id = next(iter(report_ids))
                    created_index = next(
                        index
                        for index, payload in enumerate(payloads)
                        if payload["idempotency_status"] == "CREATED"
                    )
                    creator_app = results[created_index][0]
                    observer = clients[1 - creator_app]

                    status_response = observer.get(f"/api/report/status/{task_id}")
                    detail_response = observer.get(f"/api/report/{report_id}")
                    sse_response = observer.get(
                        f"/api/report/events/{task_id}",
                        headers={"Accept": "text/event-stream"},
                    )
                    assert status_response.status_code == 200
                    assert detail_response.status_code == 200
                    assert sse_response.status_code == 200
                    frames = _parse_sse_frames(sse_response.text)

                report, governance, report_count, governance_count = asyncio.run(
                    _load_database_evidence(
                        session_factory,
                        task_id=task_id,
                        report_id=report_id,
                    )
                )
        finally:
            agent_service._COMPILED_WORKFLOW = None
            configure_tushare_client_factory(None)
            if previous_tushare_token is None:
                os.environ.pop("TUSHARE_TOKEN", None)
            else:
                os.environ["TUSHARE_TOKEN"] = previous_tushare_token
            asyncio.run(engine.dispose())

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        statuses = [str(payload["idempotency_status"]) for payload in payloads]
        assert elapsed_ms < 720_000
        assert dispatch_audit.count == 1
        assert audited_workflow.stream_call_count == 1
        assert audited_workflow.fallback_invoke_count == 0
        assert model_audit.call_count >= 5
        assert tushare_calls
        assert set(tushare_calls).issubset(_ALLOWED_TUSHARE_METHODS)
        assert report_count == governance_count == 1
        assert report.status == "completed"
        assert report.progress == 100
        assert report.content
        assert governance.snapshot_version >= 2

        status_payload = status_response.json()
        detail_payload = detail_response.json()
        assert status_payload["task_id"] == task_id
        assert status_payload["status"] == "completed"
        assert status_payload["report_id"] == report_id
        assert detail_payload["task_id"] == task_id
        assert detail_payload["report_id"] == report_id
        assert detail_payload["status"] == "completed"
        assert detail_payload["content"] == report.content

        assert [frame["type"] for frame in frames] == ["stream_ready", "task_terminal"]
        assert all(frame["task_id"] == task_id for frame in frames)
        assert all(frame["report_id"] == report_id for frame in frames)
        assert frames[-1]["status"] == "completed"
        sse_sequences = tuple(int(frame["sequence"]) for frame in frames)
        assert sse_sequences == tuple(sorted(set(sse_sequences)))
        assert sse_sequences[0] == governance.snapshot_version

        content_sha256 = hashlib.sha256(report.content.encode("utf-8")).hexdigest()
        evidence = ProtectedLiveReportGovernanceEvidence(
            test_id=_CASE_ID,
            request_count=request_count,
            app_instance_count=len(apps),
            request_distribution=(
                sum(1 for app_index, _ in results if app_index == 0),
                sum(1 for app_index, _ in results if app_index == 1),
            ),
            unique_task_count=len(task_ids),
            unique_report_count=len(report_ids),
            created_count=statuses.count("CREATED"),
            replayed_count=statuses.count("REPLAYED"),
            workflow_execution_count=audited_workflow.stream_call_count,
            workflow_fallback_count=audited_workflow.fallback_invoke_count,
            model_call_count=model_audit.call_count,
            tushare_call_count=len(tushare_calls),
            tushare_methods=tuple(sorted(set(tushare_calls))),
            snapshot_version=governance.snapshot_version,
            sse_sequences=sse_sequences,
            terminal_status=report.status,
            rest_status=str(status_payload["status"]),
            content_sha256=content_sha256,
            idempotency_key_sha256=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            elapsed_ms=round(elapsed_ms, 2),
            redaction_check="passed",
        )
        serialized = json.dumps(asdict(evidence), ensure_ascii=False, indent=2)
        forbidden = (
            _COMMAND,
            _USER_ID,
            idempotency_key,
            settings.openai_compatible_api_key,
            settings.tushare_token,
        )
        assert all(value.lower() not in serialized.lower() for value in forbidden)
        acceptance_path.write_text(serialized, encoding="utf-8")
        _scan_text_artifacts(
            (acceptance_path,),
            forbidden,
        )
        _scan_text_artifacts(
            tuple(execution_root.rglob("*")),
            (settings.openai_compatible_api_key, settings.tushare_token),
        )
        artifact_sha256 = hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
        print(f"d06_live_artifact_sha256={artifact_sha256}")
        print(
            "d06_live_summary="
            + json.dumps(
                {
                    "request_count": evidence.request_count,
                    "request_distribution": evidence.request_distribution,
                    "created_count": evidence.created_count,
                    "replayed_count": evidence.replayed_count,
                    "workflow_execution_count": evidence.workflow_execution_count,
                    "model_call_count": evidence.model_call_count,
                    "tushare_call_count": evidence.tushare_call_count,
                    "snapshot_version": evidence.snapshot_version,
                    "terminal_status": evidence.terminal_status,
                    "elapsed_ms": evidence.elapsed_ms,
                    "content_sha256": evidence.content_sha256,
                    "redaction_check": evidence.redaction_check,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return evidence
