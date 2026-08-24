"""验证受控 WorkflowEvent 到本地 JSONL/exporter 的观测合同。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for path in (ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryConversationRepository,
)
from backend.infrastructure.chat.trace import SkillTraceSink  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    EventAttribute,
    StageName,
    StageStatus,
    TerminalStatus,
    WorkflowEvent,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from src.tools import skill_trace  # noqa: E402


def _records(path: Path) -> list[dict[str, Any]]:
    """读取测试 JSONL 中的全部结构化记录。"""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.unit
def test_workflow_events_form_one_trace_with_stable_stage_spans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认一轮主链生成一个 root、完整阶段 Span 和一个终止记录。"""

    async def run_case() -> None:
        trace_path = tmp_path / "controlled-trace.jsonl"
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
        skill_trace.clear_trace_exporters()
        outcome = await ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(
                model=FakeModelProvider(),
                tool=FakeToolProvider(),
                trace=SkillTraceSink(),
            ),
            repository=InMemoryConversationRepository(),
        ).execute(
            ChatCommand(
                user_id="user-trace",
                session_id="session-trace",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            )
        )

        assert outcome.status is TerminalStatus.SUCCEEDED
        assert outcome.workflow_result is not None
        records = _records(trace_path)
        roots = [item for item in records if item["record_type"] == "trace"]
        spans = [item for item in records if item["record_type"] == "span"]

        assert [item["status"] for item in roots] == ["started", "ok"]
        assert len(spans) == len(outcome.workflow_result.events)
        assert [item["stage"] for item in spans] == [
            event.stage.value for event in outcome.workflow_result.events
        ]
        assert spans[-1]["stage"] == "termination"
        assert all(item["name"].startswith("controlled_chat.") for item in spans)
        assert {item["trace_id"] for item in records} == {outcome.context.trace_id}
        assert {item["run_id"] for item in records} == {outcome.context.run_id}
        assert {item["session_id"] for item in records} == {"session-trace"}
        assert "查询贵州茅台" not in trace_path.read_text(encoding="utf-8")

    asyncio.run(run_case())


@pytest.mark.unit
def test_workflow_trace_redacts_attributes_before_local_and_exporter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认阶段属性无法用敏感 key 绕过统一脱敏。"""
    trace_path = tmp_path / "redacted.jsonl"
    monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
    captured: list[dict[str, Any]] = []
    skill_trace.clear_trace_exporters()
    skill_trace.register_trace_exporter(captured.append)
    try:
        SkillTraceSink().emit(
            WorkflowEvent(
                sequence=1,
                trace_id="tr_sensitive",
                run_id="run_sensitive",
                session_id="session-sensitive",
                stage=StageName.ROUTE,
                status=StageStatus.SUCCEEDED,
                elapsed_ms=1.0,
                attributes=(
                    EventAttribute(key="api_key", value="must-not-appear"),
                    EventAttribute(key="route_family", value="tushare-data"),
                ),
            )
        )
    finally:
        skill_trace.clear_trace_exporters()

    local_text = trace_path.read_text(encoding="utf-8")
    assert "must-not-appear" not in local_text
    assert "[REDACTED]" in local_text
    span = next(item for item in captured if item["record_type"] == "span")
    assert span["data"]["attributes"]["api_key"] == "[REDACTED]"


@pytest.mark.unit
def test_exporter_failure_does_not_change_controlled_business_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认 Langfuse 类可选出口故障时本地 Trace 和业务结果仍成功。"""

    def failing_exporter(record: dict[str, Any]) -> None:
        del record
        raise RuntimeError("exporter unavailable")

    async def run_case() -> None:
        trace_path = tmp_path / "exporter-failure.jsonl"
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
        skill_trace.clear_trace_exporters()
        skill_trace.register_trace_exporter(failing_exporter)
        try:
            outcome = await ControlledChatUseCase(
                workflow=ControlledConversationWorkflow(
                    model=FakeModelProvider(),
                    tool=FakeToolProvider(),
                    trace=SkillTraceSink(),
                ),
                repository=InMemoryConversationRepository(),
            ).execute(
                ChatCommand(
                    user_id="user-exporter",
                    session_id="session-exporter",
                    message="查询贵州茅台 600519.SH 的基础信息和近期行情",
                )
            )
        finally:
            skill_trace.clear_trace_exporters()

        assert outcome.status is TerminalStatus.SUCCEEDED
        assert _records(trace_path)[-1]["status"] == "ok"

    asyncio.run(run_case())
