"""验证受控 WorkflowEvent 到本地 JSONL/exporter 的观测合同。"""

from __future__ import annotations

import asyncio
import hashlib
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
from src.skills.skill_registry import SkillRegistry  # noqa: E402
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


@pytest.mark.unit
def test_skill_trace_links_route_assets_references_and_synthesis_without_raw_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一次 Skill trace 必须只用版本、hash 和路径串起 route 到 synthesis。"""

    async def run_case() -> None:
        trace_path = tmp_path / "skill-version-chain.jsonl"
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
        skill_trace.clear_trace_exporters()
        registry = SkillRegistry()
        catalog = registry.conversation_snapshot()
        loader = registry.get_loader()
        expected_planner = loader.load_for_planner(
            "stock-first-pass",
            query="帮我快速看一下贵州茅台基本面，值不值得继续跟踪",
        )
        expected_synthesis = loader.load_for_synthesis(
            "stock-first-pass",
            query="帮我快速看一下贵州茅台基本面，值不值得继续跟踪",
        )
        outcome = await ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(
                model=FakeModelProvider(),
                tool=FakeToolProvider(),
                trace=SkillTraceSink(),
                skill_catalog=catalog,
                skill_loader=loader,
            ),
            repository=InMemoryConversationRepository(),
        ).execute(
            ChatCommand(
                user_id="user-skill-trace",
                session_id="session-skill-trace",
                message="帮我快速看一下贵州茅台基本面，值不值得继续跟踪",
                explicit_skill="stock-first-pass",
            )
        )

        assert outcome.status is TerminalStatus.SUCCEEDED
        spans = [item for item in _records(trace_path) if item["record_type"] == "span"]
        by_stage = {item["stage"]: item for item in spans}
        route = by_stage["route"]["data"]["attributes"]
        permission = by_stage["permission"]["data"]["attributes"]
        synthesis = by_stage["synthesis"]["data"]["attributes"]

        assert route["selected_skill"] == "stock-first-pass"
        assert route["skill_version"] == expected_planner.skill_version
        assert route["registry_snapshot_hash"] == expected_planner.registry_snapshot_hash
        assert route["confidence_band"] == "high"
        assert route["candidate_names"] == "stock-first-pass"
        assert permission["skill_spec_hash"] == expected_planner.spec_hash
        assert permission["registry_snapshot_hash"] == expected_planner.registry_snapshot_hash
        assert permission["planner_reference_count"] == len(expected_planner.references)
        assert synthesis["selected_skill"] == "stock-first-pass"
        assert synthesis["skill_spec_hash"] == expected_synthesis.spec_hash
        assert synthesis["registry_snapshot_hash"] == expected_synthesis.registry_snapshot_hash
        assert synthesis["claim_level"] == "ANALYTICAL"
        for index, reference in enumerate(expected_planner.references, start=1):
            assert permission[f"planner_reference_{index}_path"] == reference.path
            assert permission[f"planner_reference_{index}_hash"] == reference.content_hash
        for index, reference in enumerate(expected_synthesis.references, start=1):
            assert synthesis[f"synthesis_reference_{index}_path"] == reference.path
            assert synthesis[f"synthesis_reference_{index}_hash"] == reference.content_hash

        trace_text = trace_path.read_text(encoding="utf-8")
        assert "帮我快速看一下贵州茅台" not in trace_text
        assert all(reference.content not in trace_text for reference in expected_planner.references)
        assert all(reference.content not in trace_text for reference in expected_synthesis.references)

    asyncio.run(run_case())


@pytest.mark.unit
def test_web_news_trace_records_query_hash_and_source_counts_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web News 观测只能记录最小查询 hash 和来源计数，不得记录查询正文。"""

    async def run_case() -> None:
        trace_path = tmp_path / "web-search-summary.jsonl"
        monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
        skill_trace.clear_trace_exporters()
        registry = SkillRegistry()
        outcome = await ControlledChatUseCase(
            workflow=ControlledConversationWorkflow(
                model=FakeModelProvider(),
                tool=FakeToolProvider(),
                trace=SkillTraceSink(),
                skill_catalog=registry.conversation_snapshot(),
                skill_loader=registry.get_loader(),
            ),
            repository=InMemoryConversationRepository(),
        ).execute(
            ChatCommand(
                user_id="user-web-trace",
                session_id="session-web-trace",
                message="贵州茅台今天为什么跌，有什么消息",
                explicit_skill="market-move-explain",
            )
        )

        assert outcome.status is TerminalStatus.SUCCEEDED
        assert outcome.workflow_result is not None
        assert outcome.workflow_result.plan is not None
        web_step = next(
            item
            for item in outcome.workflow_result.plan.steps
            if item.tool_name == "search_web_news"
        )
        raw_query = str(next(item.value for item in web_step.arguments if item.name == "query"))
        expected_hash = hashlib.sha256(raw_query.encode("utf-8")).hexdigest()
        spans = [item for item in _records(trace_path) if item["record_type"] == "span"]
        by_stage = {item["stage"]: item for item in spans}
        plan = by_stage["plan"]["data"]["attributes"]
        verify = by_stage["verify"]["data"]["attributes"]

        assert plan["web_search_triggered"] is True
        assert plan["web_query_hash"] == expected_hash
        assert verify["web_source_count"] == 1
        assert verify["web_accepted_count"] == 1
        assert verify["web_rejected_count"] == 0
        trace_text = trace_path.read_text(encoding="utf-8")
        assert raw_query not in trace_text
        assert "离线新闻线索" not in trace_text

    asyncio.run(run_case())
