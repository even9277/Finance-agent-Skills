"""锁定迁移前 Trace 根事件、工具错误和关联字段合同。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.tools import skill_trace  # noqa: E402


def _read_records(path: Path) -> list[dict[str, object]]:
    """读取测试产生的 JSONL Trace 记录。"""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.unit
def test_legacy_trace_has_one_started_and_one_terminal_root_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认同一轮对话的根 Trace 共享关联字段并具有唯一终态。"""
    trace_path = tmp_path / "root-trace.jsonl"
    monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
    skill_trace.clear_trace_exporters()

    with skill_trace.skill_trace_context(
        trace_id="tr_characterization",
        run_id="run_characterization",
        session_id="session-characterization",
        user_id="user-characterization",
        turn_index=2,
    ):
        skill_trace.log_trace_started(request_kind="chat")
        skill_trace.log_trace_finished(
            status="error",
            duration_ms=12.5,
            final_status="error",
            error_code="LEGACY_FAILURE",
        )

    records = _read_records(trace_path)
    roots = [record for record in records if record["record_type"] == "trace"]
    assert [record["status"] for record in roots] == ["started", "error"]
    assert {record["trace_id"] for record in roots} == {"tr_characterization"}
    assert {record["run_id"] for record in roots} == {"run_characterization"}
    assert {record["session_id"] for record in roots} == {"session-characterization"}
    assert {record["turn_index"] for record in roots} == {2}
    assert roots[-1]["duration_ms"] == 12.5
    assert roots[-1]["data"] == {
        "final_status": "error",
        "error_code": "LEGACY_FAILURE",
    }


@pytest.mark.unit
def test_legacy_tool_trace_records_sanitized_failure_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认工具失败会写脱敏错误事件，并把异常继续交给上层控制器。"""
    trace_path = tmp_path / "tool-trace.jsonl"
    monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
    skill_trace.clear_trace_exporters()

    with skill_trace.skill_trace_context(trace_id="tr_tool_failure"):
        with pytest.raises(RuntimeError, match="fixture tool failed"):
            with skill_trace.log_tool_call(
                "stock_basic",
                symbol="600519.SH",
                token="must-not-appear",
                payload={"authorization": "Bearer must-not-appear"},
            ):
                raise RuntimeError("fixture tool failed")

    records = _read_records(trace_path)
    event_records = [record for record in records if record["record_type"] == "event"]
    names = [record["name"] for record in event_records]
    assert names == ["chat.tool.start", "chat.tool.error"]
    assert event_records[-1]["status"] == "error"
    serialized = json.dumps(records, ensure_ascii=False)
    assert "must-not-appear" not in serialized
    assert "fixture tool failed" in serialized
