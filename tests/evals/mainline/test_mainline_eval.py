"""执行整条受控对话主链的版本化离线评测。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import ChatCommand  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryConversationRepository,
    InMemoryTraceSink,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402
from tests.evals.metrics import required_stage_coverage, terminal_status_accuracy  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402

DATA_PATH = Path("tests/evals/mainline/data/smoke.jsonl")


@pytest.mark.eval_smoke
def test_mainline_smoke_executes_real_orchestrator() -> None:
    """确认三个终态案例经过真实 Orchestrator 且整链指标为 1。"""

    async def run_case() -> list[dict[str, Any]]:
        predictions: list[dict[str, Any]] = []
        for row in load_jsonl(DATA_PATH):
            started = time.perf_counter()
            trace = InMemoryTraceSink()
            outcome = await ControlledChatUseCase(
                workflow=ControlledConversationWorkflow(
                    model=FakeModelProvider(),
                    tool=FakeToolProvider(behavior=row["tool_behavior"]),
                    trace=trace,
                ),
                repository=InMemoryConversationRepository(),
            ).execute(
                ChatCommand(
                    user_id="eval-user",
                    session_id=f"session-{row['case_id']}",
                    message=row["message"],
                )
            )
            predictions.append(
                {
                    **row,
                    "prediction": {
                        "terminal_status": outcome.status.value,
                        "stages": [event.stage.value for event in trace.events],
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    },
                }
            )
        return predictions

    records = asyncio.run(run_case())
    assert terminal_status_accuracy(records) == 1.0
    assert required_stage_coverage(records) == 1.0
