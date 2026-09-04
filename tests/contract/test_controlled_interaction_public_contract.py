"""锁定 D04 Application 事件到 chat-stream-v2 控制帧的公开合同。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import sys
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.application.chat.contracts import (  # noqa: E402
    ChatContentDelta,
    ChatOutcome,
    ChatStreamCompleted,
    ChatStreamStarted,
)
from backend.routers import chat as chat_router  # noqa: E402
from src.conversation.contracts import TerminalStatus  # noqa: E402


class _CollectingWebSocket:
    """保存 Presenter 发出的公开 JSON 帧。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        """按发送顺序保存一帧。"""
        self.frames.append(payload)


def _contracts() -> Any:
    """延迟读取新增 Application 事件合同。"""
    return importlib.import_module("backend.application.chat.contracts")


async def _controlled_stream() -> AsyncGenerator[Any, None]:
    """产生包含五类控制事件和 D03 文本终态的确定性事件流。"""
    contracts = _contracts()
    common = {"request_id": "request-d04", "session_id": "session-d04"}
    yield ChatStreamStarted(**common)
    yield contracts.ChatTraceSummary(
        **common,
        stage="validate",
        status="SUCCEEDED",
        elapsed_ms=1.5,
        summary="执行计划已通过校验",
    )
    yield contracts.ChatPlanPreview(
        **common,
        plan_id="plan-d04",
        revision=1,
        validated=True,
        steps=(
            contracts.ChatPlanStepPreview(
                step_id="market-step",
                title="获取行情数据",
                purpose="补充行情证据",
                required=True,
                status=contracts.ChatStepLifecycleStatus.PLANNED,
                depends_on=(),
                subject_summary="贵州茅台（600519.SH）",
            ),
        ),
    )
    yield contracts.ChatStepStatus(
        **common,
        plan_id="plan-d04",
        revision=1,
        step_id="market-step",
        status=contracts.ChatStepLifecycleStatus.RUNNING,
    )
    yield contracts.ChatToolStatus(
        **common,
        plan_id="plan-d04",
        revision=1,
        tool_call_id="call-d04",
        step_id="market-step",
        display_name="行情数据工具",
        status=contracts.ChatToolLifecycleStatus.STARTED,
        attempt=1,
        parameter_summary=("标的：600519.SH",),
    )
    yield contracts.ChatToolStatus(
        **common,
        plan_id="plan-d04",
        revision=1,
        tool_call_id="call-d04",
        step_id="market-step",
        display_name="行情数据工具",
        status=contracts.ChatToolLifecycleStatus.SUCCEEDED,
        attempt=1,
        elapsed_ms=12.5,
        parameter_summary=("标的：600519.SH",),
        result_summary="已返回 1 条可校验证据",
    )
    yield contracts.ChatStepStatus(
        **common,
        plan_id="plan-d04",
        revision=1,
        step_id="market-step",
        status=contracts.ChatStepLifecycleStatus.SUCCEEDED,
        elapsed_ms=13.0,
    )
    yield contracts.ChatVerificationSummary(
        **common,
        plan_id="plan-d04",
        revision=1,
        sufficiency=contracts.ChatEvidenceSufficiency.SUFFICIENT,
        claim_level="ANALYTICAL",
        accepted_count=1,
        rejected_count=0,
        covered_dimensions=("market_snapshot",),
        missing_dimensions=(),
        limitation="证据满足当前分析要求。",
    )
    yield ChatContentDelta(
        **common,
        content="最终回答",
        chunk_index=1,
    )
    outcome = ChatOutcome(
        reply="最终回答",
        session_id="session-d04",
        status=TerminalStatus.SUCCEEDED,
    )
    yield ChatStreamCompleted(
        **common,
        outcome=outcome,
        chunk_count=1,
        content_sha256=hashlib.sha256(outcome.reply.encode()).hexdigest(),
        ttft_ms=20.0,
        elapsed_ms=30.0,
    )


@pytest.mark.contract
def test_presenter_maps_all_control_events_to_ordered_v2_frames() -> None:
    """D04-C01/C08：五类控制帧必须复用 v2 信封与全局 sequence。"""

    async def run_case() -> list[dict[str, object]]:
        websocket = _CollectingWebSocket()
        state = chat_router._WebSocketStreamState(
            request_id="request-d04",
            session_id="session-d04",
            started_at=time.perf_counter(),
        )
        await chat_router._present_chat_stream(
            websocket,  # type: ignore[arg-type]
            _controlled_stream(),
            state,
        )
        return websocket.frames

    frames = asyncio.run(run_case())

    assert [frame["type"] for frame in frames] == [
        "stream_start",
        "trace_summary",
        "plan_preview",
        "step_status",
        "tool_status",
        "tool_status",
        "step_status",
        "verification_summary",
        "content_delta",
        "stream_end",
    ]
    assert [frame["sequence"] for frame in frames] == list(range(1, 11))
    assert all(frame["protocol_version"] == "chat-stream-v2" for frame in frames)
    assert frames[2]["validated"] is True
    assert frames[4]["status"] == "STARTED"
    assert frames[5]["elapsed_ms"] == 12.5
    assert frames[7]["sufficiency"] == "SUFFICIENT"


@pytest.mark.contract
def test_control_frames_never_serialize_forbidden_internal_fields() -> None:
    """D04-C01/C03：公开帧集合不能出现领域私有载荷键。"""
    frames = asyncio.run(_collect_control_frames())
    serialized = repr(frames)

    for forbidden_key in (
        "arguments",
        "idempotency_key",
        "permission_hash",
        "facts",
        "error_message",
        "prompt",
    ):
        assert forbidden_key not in serialized


async def _collect_control_frames() -> list[dict[str, object]]:
    """运行公开 Presenter 并只返回控制帧。"""
    websocket = _CollectingWebSocket()
    state = chat_router._WebSocketStreamState(
        request_id="request-d04",
        session_id="session-d04",
        started_at=time.perf_counter(),
    )
    await chat_router._present_chat_stream(
        websocket,  # type: ignore[arg-type]
        _controlled_stream(),
        state,
    )
    return [
        frame
        for frame in websocket.frames
        if frame["type"]
        in {
            "trace_summary",
            "plan_preview",
            "step_status",
            "tool_status",
            "verification_summary",
        }
    ]
