"""验证报告后台服务把真实 LangGraph 事件提交为单调、安全的进度。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from backend.application.report_progress.contracts import (
    ReportProgressMessage,
    ReportProgressNotification,
    ReportStageStatus,
    ReportTaskStatus,
    ReportTerminalNotification,
)
from backend.application.report_progress.snapshot import REPORT_GENERATION_FAILED_MESSAGE
from backend.config import settings
from backend.db import database as database_module
from backend.services import agent_service


class _ScalarResult:
    """返回共享测试报告的最小查询结果。"""

    def __init__(self, report: SimpleNamespace) -> None:
        self._report = report

    def scalar_one_or_none(self) -> SimpleNamespace:
        """返回共享报告对象。"""
        return self._report


class _Session:
    """记录每次短事务提交后的安全任务字段。"""

    def __init__(self, report: SimpleNamespace, commits: list[dict[str, object]]) -> None:
        self._report = report
        self._commits = commits

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, *_args: object, **_kwargs: object) -> _ScalarResult:
        """返回当前共享报告。"""
        return _ScalarResult(self._report)

    async def commit(self) -> None:
        """保存提交时状态，不复制报告正文。"""
        self._commits.append(
            {
                "status": self._report.status,
                "progress": self._report.progress,
                "error_msg": self._report.error_msg,
            }
        )


class _SessionFactory:
    """为每次更新创建共享状态的短会话替身。"""

    def __init__(self, report: SimpleNamespace, commits: list[dict[str, object]]) -> None:
        self._report = report
        self._commits = commits

    def __call__(self) -> _Session:
        return _Session(self._report, self._commits)


class _Recorder:
    """记录通知到达时数据库已经提交的状态。"""

    def __init__(self, report: SimpleNamespace) -> None:
        self._report = report
        self.items: list[tuple[ReportProgressMessage, str, int]] = []

    def publish(self, message: ReportProgressMessage) -> None:
        """保存通知和同一时刻的权威任务字段。"""
        self.items.append((message, self._report.status, self._report.progress))


class _Workflow:
    """按固定顺序产出正常或失败的 LangGraph 生命周期。"""

    def __init__(self, events: list[dict[str, object]], failure: Exception | None = None) -> None:
        self._events = events
        self._failure = failure

    async def astream_events(
        self,
        _state: object,
        *,
        version: str,
    ) -> Any:
        assert version == "v2"
        for event in self._events:
            yield event
        if self._failure is not None:
            raise self._failure


def _event(kind: str, node: str) -> dict[str, object]:
    """构造 LangGraph 顶层节点事件。"""
    return {
        "event": kind,
        "name": node,
        "metadata": {"langgraph_node": node},
        "data": {},
    }


def _report() -> SimpleNamespace:
    """构造一条初始 pending 报告记录。"""
    return SimpleNamespace(
        id="report-service-d05",
        task_id="task-service-d05",
        user_id="user-service-d05",
        status="pending",
        progress=0,
        stock_code=None,
        company_name=None,
        content=None,
        error_msg=None,
    )


def _run_with(
    workflow: _Workflow,
    *,
    report: SimpleNamespace,
    commits: list[dict[str, object]],
    recorder: _Recorder,
    initial_state: dict[str, object] | None = None,
    command: str = "离线固定指令",
) -> Mock:
    """在隔离端口中运行报告服务并返回 finalize mock。"""
    execution = SimpleNamespace(
        execution_id="execution-d05",
        execution_dir=Path("artifacts/test/report-d05"),
    )
    final_logger = SimpleNamespace(log_final_report=Mock())
    finalize = Mock()
    effective_initial_state = initial_state or {
        "data": {"company_name": "贵州茅台", "stock_code": "sh.600519"}
    }
    with (
        patch.object(
            database_module,
            "AsyncSessionFactory",
            new=_SessionFactory(report, commits),
        ),
        patch.object(
            agent_service,
            "_build_initial_state",
            new=AsyncMock(return_value=effective_initial_state),
        ),
        patch.object(agent_service, "_get_workflow", return_value=workflow),
        patch.object(agent_service, "initialize_execution_logger", return_value=execution),
        patch.object(agent_service, "get_execution_logger", return_value=final_logger),
        patch.object(agent_service, "finalize_execution_logger", new=finalize),
        patch.object(settings, "enable_stm", False),
        patch.object(settings, "enable_memory", False),
    ):
        asyncio.run(
            agent_service.run_report_task(
                task_id=report.task_id,
                report_id=report.id,
                command=command,
                user_id=report.user_id,
                publisher=recorder,
            )
        )
    return finalize


@pytest.mark.unit
def test_report_service_commits_monotonic_progress_before_notifications() -> None:
    """D05-T02：乱序 analyst 事件必须真实贯通数据库、通知和终态。"""
    analyst_order = (
        "technical_analyst",
        "news_analyst",
        "fundamental_analyst",
        "value_analyst",
    )
    events = [_event("on_chain_start", node) for node in analyst_order]
    events.extend(_event("on_chain_end", node) for node in analyst_order)
    events.extend(
        [
            _event("on_chain_start", "summarizer"),
            _event("on_chain_end", "summarizer"),
            {
                "event": "on_chain_end",
                "name": "LangGraph",
                "metadata": {},
                "data": {"output": {"data": {"final_report": "# 离线最终报告"}}},
            },
        ]
    )
    report = _report()
    commits: list[dict[str, object]] = []
    recorder = _Recorder(report)

    with patch.object(agent_service.logger, "info") as info:
        finalize = _run_with(
            _Workflow(events),
            report=report,
            commits=commits,
            recorder=recorder,
        )

    committed_progress: list[int] = []
    for item in commits:
        value = item["progress"]
        assert isinstance(value, int)
        committed_progress.append(value)
    assert committed_progress == sorted(committed_progress)
    assert {35, 50, 65, 80, 90, 95, 100}.issubset(committed_progress)
    completed_analysts = [
        item.progress
        for item, _, _ in recorder.items
        if isinstance(item, ReportProgressNotification)
        and item.stage_status is ReportStageStatus.SUCCEEDED
        and item.progress in {35, 50, 65, 80}
    ]
    assert completed_analysts == [35, 50, 65, 80]
    terminal, status_at_publish, progress_at_publish = recorder.items[-1]
    assert isinstance(terminal, ReportTerminalNotification)
    assert terminal.status is ReportTaskStatus.COMPLETED
    assert (status_at_publish, progress_at_publish) == ("completed", 100)
    assert report.content == "# 离线最终报告"
    assert "贵州茅台" not in repr(info.call_args_list)
    assert "sh.600519" not in repr(info.call_args_list)
    finalize.assert_called_once_with(success=True)


@pytest.mark.unit
def test_report_service_keeps_last_progress_and_redacts_failure_before_terminal() -> None:
    """D05-T02/T07：原始异常不得进入数据库、通知或 ExecutionLogger。"""
    report = _report()
    commits: list[dict[str, object]] = []
    recorder = _Recorder(report)
    raw_error = RuntimeError("Authorization=Bearer SUPER_SECRET provider failure")

    finalize = _run_with(
        _Workflow(
            [_event("on_chain_start", "fundamental_analyst")],
            failure=raw_error,
        ),
        report=report,
        commits=commits,
        recorder=recorder,
    )

    assert report.status == "failed"
    assert report.progress == 20
    assert report.error_msg == REPORT_GENERATION_FAILED_MESSAGE
    failed_stage = recorder.items[-2][0]
    terminal, status_at_publish, progress_at_publish = recorder.items[-1]
    assert isinstance(failed_stage, ReportProgressNotification)
    assert failed_stage.stage_status is ReportStageStatus.FAILED
    assert isinstance(terminal, ReportTerminalNotification)
    assert terminal.status is ReportTaskStatus.FAILED
    assert (status_at_publish, progress_at_publish) == ("failed", 20)
    assert "SUPER_SECRET" not in repr(recorder.items)
    assert "SUPER_SECRET" not in repr(commits)
    finalize.assert_called_once_with(
        success=False,
        error=REPORT_GENERATION_FAILED_MESSAGE,
    )


@pytest.mark.unit
def test_report_service_does_not_log_raw_command_when_stock_resolution_degrades(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D05-T07：解析降级日志不得包含原始用户指令或识别文本。"""
    raw_command = "请分析我的私密持仓 PRIVATE_COMMAND_600519"
    report = _report()
    commits: list[dict[str, object]] = []
    recorder = _Recorder(report)
    events = [
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "metadata": {},
            "data": {"output": {"data": {"final_report": "# 安全离线报告"}}},
        }
    ]

    with patch.object(agent_service.logger, "warning") as warning:
        _run_with(
            _Workflow(events),
            report=report,
            commits=commits,
            recorder=recorder,
            initial_state={"data": {"company_name": "PRIVATE_COMPANY", "stock_code": None}},
            command=raw_command,
        )

    rendered_calls = repr(warning.call_args_list)
    terminal_output = capsys.readouterr().out
    assert raw_command not in rendered_calls
    assert "PRIVATE_COMMAND" not in rendered_calls
    assert "PRIVATE_COMPANY" not in rendered_calls
    assert "PRIVATE_COMMAND" not in terminal_output
    assert "PRIVATE_COMPANY" not in terminal_output


@pytest.mark.unit
def test_report_service_commits_persistent_versions_before_redis_failure(
    tmp_path: Path,
) -> None:
    """D06-T04：Redis 镜像异常不能回滚 Report/治理终态或污染日志。"""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.db.database import Base
    from backend.db.models import Report, ReportTaskGovernanceRow, User
    from backend.infrastructure.report_tasks import runtime as runtime_module

    class _BrokenRuntime:
        async def store_and_publish(self, **_kwargs: object) -> None:
            raise RuntimeError("Authorization=Bearer REDIS_MUST_NOT_LEAK")

    async def scenario() -> tuple[Report, ReportTaskGovernanceRow, _Recorder, str]:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'runner-snapshot.db').as_posix()}"
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        report = _report()
        governance = ReportTaskGovernanceRow(
            id="governance-service-d06",
            user_id=report.user_id,
            key_digest="a" * 64,
            request_fingerprint="b" * 64,
            task_id=report.task_id,
            report_id=report.id,
            generation=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            snapshot_version=1,
            stage_states=[],
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                session.add(User(id=report.user_id))
                session.add(
                    Report(
                        id=report.id,
                        task_id=report.task_id,
                        user_id=report.user_id,
                        status=report.status,
                        progress=report.progress,
                    )
                )
                session.add(governance)
                await session.commit()

            workflow = _Workflow(
                [
                    {
                        "event": "on_chain_end",
                        "name": "LangGraph",
                        "metadata": {},
                        "data": {"output": {"data": {"final_report": "# 持久化报告"}}},
                    }
                ]
            )
            recorder = _Recorder(report)
            execution = SimpleNamespace(
                execution_id="execution-d06",
                execution_dir=Path("artifacts/test/report-d06"),
            )
            with (
                patch.object(database_module, "AsyncSessionFactory", new=sessions),
                patch.object(
                    agent_service,
                    "_build_initial_state",
                    new=AsyncMock(
                        return_value={
                            "data": {"company_name": "贵州茅台", "stock_code": "sh.600519"}
                        }
                    ),
                ),
                patch.object(agent_service, "_get_workflow", return_value=workflow),
                patch.object(
                    agent_service,
                    "initialize_execution_logger",
                    return_value=execution,
                ),
                patch.object(
                    agent_service,
                    "get_execution_logger",
                    return_value=SimpleNamespace(log_final_report=Mock()),
                ),
                patch.object(agent_service, "finalize_execution_logger"),
                patch.object(settings, "enable_stm", False),
                patch.object(settings, "enable_memory", False),
                patch.object(
                    runtime_module,
                    "get_report_task_runtime",
                    return_value=_BrokenRuntime(),
                ),
                patch.object(agent_service.logger, "warning") as warning,
            ):
                await agent_service.run_report_task(
                    task_id=report.task_id,
                    report_id=report.id,
                    command="不会进入日志的命令",
                    user_id=report.user_id,
                    publisher=recorder,
                )

            async with sessions() as session:
                stored_report = (
                    await session.execute(select(Report).where(Report.id == report.id))
                ).scalar_one()
                stored_governance = (
                    await session.execute(
                        select(ReportTaskGovernanceRow).where(
                            ReportTaskGovernanceRow.id == governance.id
                        )
                    )
                ).scalar_one()
                return stored_report, stored_governance, recorder, repr(warning.call_args_list)
        finally:
            await engine.dispose()

    stored_report, stored_governance, recorder, warning_calls = asyncio.run(scenario())
    assert (stored_report.status, stored_report.progress, stored_report.content) == (
        "completed",
        100,
        "# 持久化报告",
    )
    versions = [item.snapshot_version for item, _, _ in recorder.items]
    assert all(version is not None for version in versions)
    persisted_versions = [version for version in versions if version is not None]
    assert len(persisted_versions) == len(versions)
    assert persisted_versions == sorted(persisted_versions)
    assert stored_governance.snapshot_version == persisted_versions[-1]
    assert stored_governance.stage_states == [
        {"stage": "PREPARING", "status": "SUCCEEDED"}
    ]
    assert "REDIS_MUST_NOT_LEAK" not in warning_calls
