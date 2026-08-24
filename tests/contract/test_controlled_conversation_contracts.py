"""验证新受控对话合同的版本、事件和依赖方向。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    EventAttribute,
    RunPhase,
    StageName,
    StageStatus,
    WorkflowEvent,
)


@pytest.mark.contract
def test_workflow_event_has_stable_correlation_and_version_fields() -> None:
    """确认阶段事件具备跨入口复用所需的稳定关联字段。"""
    event = WorkflowEvent(
        sequence=1,
        trace_id="trace-1",
        run_id="run-1",
        session_id="session-1",
        stage=StageName.ROUTE,
        status=StageStatus.SUCCEEDED,
        elapsed_ms=1.5,
        attributes=(EventAttribute(key="route_family", value="tushare-data"),),
    )

    assert event.version == CONTRACT_VERSION
    assert event.sequence == 1
    assert event.trace_id == "trace-1"
    assert event.run_id == "run-1"
    assert event.session_id == "session-1"
    assert event.stage is StageName.ROUTE
    assert event.status is StageStatus.SUCCEEDED
    assert event.attributes[0].value == "tushare-data"


@pytest.mark.contract
def test_terminal_phases_match_public_terminal_statuses() -> None:
    """确认状态机终态集合完整且不会退化为布尔成功标志。"""
    assert {phase.value for phase in RunPhase if phase.is_terminal} == {
        "SUCCEEDED",
        "PARTIAL",
        "NEEDS_CLARIFICATION",
        "REJECTED",
        "FAILED",
        "CANCELLED",
        "UNSUPPORTED",
    }


@pytest.mark.contract
def test_conversation_domain_does_not_import_backend_or_frameworks() -> None:
    """确认领域工作流不反向依赖 backend、FastAPI 或 SQLAlchemy。"""
    conversation_root = AGENT_ROOT / "src" / "conversation"
    forbidden_roots = {"backend", "fastapi", "sqlalchemy"}
    violations: list[str] = []

    for path in sorted(conversation_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name.split(".", maxsplit=1)[0].lower() in forbidden_roots:
                    violations.append(f"{path.name}:{name}")

    assert violations == []
