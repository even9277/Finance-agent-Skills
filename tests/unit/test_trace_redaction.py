"""验证 Trace/日志产物的关联字段、故障隔离和脱敏契约。"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[2] / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.tools import skill_trace  # noqa: E402


@pytest.mark.unit
def test_redacts_credential_keys_recursively() -> None:
    payload = {
        "authorization": "Bearer do-not-log",
        "nested": {
            "api_key": "secret-value",
            "safe": "visible",
        },
        "items": [{"password": "pw", "name": "fixture"}],
    }

    sanitized = skill_trace._sanitize_value(payload)

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["safe"] == "visible"
    assert sanitized["items"][0]["password"] == "[REDACTED]"


@pytest.mark.unit
def test_truncates_non_sensitive_long_values() -> None:
    sanitized = skill_trace._sanitize_value({"diagnostic": "x" * 100})

    assert sanitized["diagnostic"] == ("x" * 77) + "..."


@pytest.mark.unit
def test_trace_keeps_correlation_fields_when_exporter_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认可选 exporter 故障不会中断本地 Trace 主链。"""
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(skill_trace, "_JSONL_PATH", trace_path)
    skill_trace.clear_trace_exporters()

    def failing_exporter(record: dict[str, object]) -> None:
        """模拟 Langfuse 等外部 exporter 的瞬时故障。"""
        raise RuntimeError("offline exporter unavailable")

    skill_trace.register_trace_exporter(failing_exporter)
    try:
        with skill_trace.skill_trace_context(trace_id="tr_offline", run_id="run_offline"):
            skill_trace.log_trace_started(request_kind="contract")
    finally:
        skill_trace.clear_trace_exporters()

    record = json.loads(trace_path.read_text(encoding="utf-8"))
    assert record["trace_id"] == "tr_offline"
    assert record["run_id"] == "run_offline"
    assert record["stage"] == "workflow"
    assert record["status"] == "started"


@pytest.mark.unit
def test_exporter_receives_redacted_trace_payload() -> None:
    """确认可选 exporter 也不能收到凭证或原始敏感载荷。"""
    captured: list[dict[str, Any]] = []
    skill_trace.clear_trace_exporters()

    def capture_exporter(record: dict[str, Any]) -> None:
        """保存 exporter 输入以断言其已经过脱敏。"""
        captured.append(record)

    skill_trace.register_trace_exporter(capture_exporter)
    try:
        with skill_trace.skill_trace_context(trace_id="tr_exporter"):
            skill_trace.log_model_stage(
                stage="model",
                data={"api_key": "do-not-export", "prompt": "safe summary"},
            )
    finally:
        skill_trace.clear_trace_exporters()

    assert captured
    payload = captured[0]
    assert payload["trace_id"] == "tr_exporter"
    assert payload["data"]["data"]["api_key"] == "[REDACTED]"
    assert payload["data"]["data"]["prompt"] == "safe summary"
