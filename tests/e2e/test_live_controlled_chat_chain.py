"""使用真实模型与可选真实 Tushare 验收 WebSocket 流式受控主链。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.config import settings  # noqa: E402
from backend.db.database import Base  # noqa: E402
from backend.db.models import Message, User  # noqa: E402
from backend.infrastructure.chat.providers import (  # noqa: E402
    OpenAICompatibleModelProvider,
    TushareToolProvider,
)
from backend.infrastructure.chat.testing import FakeToolProvider  # noqa: E402
from backend.routers import chat as chat_router  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ModelSynthesisChunk,
    ModelSynthesisRequest,
    ToolCall,
    ToolObservation,
)
from src.tools import skill_trace  # noqa: E402
from src.tools.tushare_client import configure_tushare_client_factory  # noqa: E402

_LIVE_SWITCH = "RUN_PROTECTED_LIVE_E2E"
_USER_ID = "live-ws-user"


@dataclass(frozen=True, slots=True)
class _LiveCase:
    """描述一条受保护 Live 主路径及其外部依赖边界。"""

    test_id: str
    question: str
    use_real_tushare: bool


_LIVE_CASES = (
    _LiveCase(
        test_id="d03-live-01",
        question="查询贵州茅台 600519.SH 的基础信息和近期行情，并说明估值分析应关注什么。",
        use_real_tushare=False,
    ),
    _LiveCase(
        test_id="d03-live-02",
        question="查询贵州茅台 600519.SH 的基础信息、近期行情和核心财务指标，给出审慎结论。",
        use_real_tushare=True,
    ),
)


def _require_protected_live_configuration() -> None:
    """拒绝误触发或缺少凭证的伪 Live 成功。"""
    if os.getenv(_LIVE_SWITCH, "").strip().lower() != "true":
        pytest.skip(f"需要显式设置 {_LIVE_SWITCH}=true")

    required = {
        "OPENAI_COMPATIBLE_API_KEY": settings.openai_compatible_api_key,
        "OPENAI_COMPATIBLE_BASE_URL": settings.openai_compatible_base_url,
        "OPENAI_COMPATIBLE_MODEL": (
            settings.chat_skill_synthesis_model or settings.openai_compatible_model
        ),
        "TUSHARE_TOKEN": settings.tushare_token,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        pytest.fail("保护性 Live 测试缺少必需配置：" + ", ".join(missing))


def _read_trace_records(path: Path) -> list[dict[str, Any]]:
    """读取隔离目录中的脱敏 JSONL Trace。"""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _receive_terminal_frames(
    client: TestClient,
    case: _LiveCase,
) -> tuple[list[dict[str, Any]], list[float]]:
    """从真实 WebSocket 入口读取到唯一公开终态。"""
    frames: list[dict[str, Any]] = []
    received_at: list[float] = []
    with client.websocket_connect("/api/chat/stream") as websocket:
        websocket.send_json(
            {
                "user_id": _USER_ID,
                "message": case.question,
                "request_id": case.test_id,
                "explicit_skill": "stock-first-pass",
            }
        )
        while True:
            frame = websocket.receive_json()
            frames.append(frame)
            received_at.append(time.perf_counter())
            if frame["type"] in {"stream_end", "stream_error"}:
                return frames, received_at


async def _prepare_database(
    engine: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """创建临时数据库及外键所需的隔离用户。"""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(User(id=_USER_ID, display_name="protected live websocket e2e"))
        await session.commit()


async def _read_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Message]:
    """读取隔离数据库中的完整消息序列。"""
    async with session_factory() as session:
        result = await session.execute(select(Message).order_by(Message.id))
        return list(result.scalars().all())


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.parametrize("case", _LIVE_CASES, ids=lambda item: item.test_id)
def test_live_websocket_streams_real_model_and_controlled_evidence(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    case: _LiveCase,
) -> None:
    """验证真实模型流、受控工具证据、协议顺序、落库与脱敏 Trace。"""
    _require_protected_live_configuration()

    database_path = tmp_path / f"{case.test_id}.db"
    trace_path = tmp_path / f"{case.test_id}-trace.jsonl"
    artifact_path = tmp_path / f"{case.test_id}-acceptance.json"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    request.addfinalizer(lambda: asyncio.run(engine.dispose()))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    asyncio.run(_prepare_database(engine, session_factory))

    real_tool_execute = TushareToolProvider.execute
    real_model_stream = OpenAICompatibleModelProvider.stream_synthesize
    fake_tool = FakeToolProvider()
    observations: list[ToolObservation] = []
    model_chunk_times: list[float] = []
    model_call_count = 0

    async def audited_tool_execute(
        provider: TushareToolProvider,
        call: ToolCall,
    ) -> ToolObservation:
        """按案例调用真实或确定性只读工具，并仅记录低敏合同。"""
        observation = (
            await real_tool_execute(provider, call)
            if case.use_real_tushare
            else await fake_tool.execute(call)
        )
        observations.append(observation)
        return observation

    async def audited_model_stream(
        provider: OpenAICompatibleModelProvider,
        synthesis_request: ModelSynthesisRequest,
    ) -> AsyncIterator[ModelSynthesisChunk]:
        """调用真实模型流，仅累计次数和时刻，不记录 Prompt 或回答。"""
        nonlocal model_call_count
        model_call_count += 1
        async for chunk in real_model_stream(provider, synthesis_request):
            model_chunk_times.append(time.perf_counter())
            yield chunk

    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/chat")
    previous_tushare_token = os.environ.get("TUSHARE_TOKEN")
    os.environ["TUSHARE_TOKEN"] = settings.tushare_token
    configure_tushare_client_factory(None)
    started_at = time.perf_counter()
    try:
        with (
            patch.object(settings, "auth_enabled", False),
            patch.object(settings, "enable_memory", False),
            patch.object(settings, "enable_stm", False),
            patch.object(settings, "enable_langfuse", False),
            patch.object(skill_trace, "_JSONL_PATH", trace_path),
            patch.object(chat_router, "AsyncSessionFactory", new=session_factory),
            patch.object(TushareToolProvider, "execute", new=audited_tool_execute),
            patch.object(
                OpenAICompatibleModelProvider,
                "stream_synthesize",
                new=audited_model_stream,
            ),
        ):
            frames, received_at = _receive_terminal_frames(TestClient(app), case)
    finally:
        configure_tushare_client_factory(None)
        if previous_tushare_token is None:
            os.environ.pop("TUSHARE_TOKEN", None)
        else:
            os.environ["TUSHARE_TOKEN"] = previous_tushare_token

    assert frames[-1]["type"] == "stream_end", frames[-1]
    assert [item["sequence"] for item in frames] == list(range(1, len(frames) + 1))
    assert all(item["protocol_version"] == "chat-stream-v2" for item in frames)
    deltas = [item for item in frames if item["type"] == "content_delta"]
    assert len(deltas) >= 2
    assert [item["chunk_index"] for item in deltas] == list(range(1, len(deltas) + 1))
    assert model_call_count == 1
    assert len(model_chunk_times) >= 2
    assert model_chunk_times[0] < model_chunk_times[-1]
    assert received_at[0] < received_at[-1]

    reply = "".join(str(item["content"]) for item in deltas)
    terminal = frames[-1]
    assert terminal["chunk_count"] == len(deltas)
    assert terminal["content_sha256"] == hashlib.sha256(reply.encode()).hexdigest()
    persisted = asyncio.run(_read_messages(session_factory))
    assert [item.role for item in persisted] == ["user", "assistant"]
    assert persisted[0].content == case.question
    assert persisted[1].content == reply

    assert observations
    assert {item.symbol for item in observations} == {"600519.SH"}
    expected_source_prefix = "tushare:" if case.use_real_tushare else "fixture:"
    assert all(item.source.startswith(expected_source_prefix) for item in observations)

    # 先保存低敏验收事实；即使后续 Trace 合同回归失败，也不丢失已付费调用证据。
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    ttft_ms = (received_at[1] - started_at) * 1000
    artifact = {
        "test_id": case.test_id,
        "request_id": case.test_id,
        "protocol_version": "chat-stream-v2",
        "provider": "openai-compatible",
        "model": settings.chat_skill_synthesis_model or settings.openai_compatible_model,
        "tool_mode": "real-tushare" if case.use_real_tushare else "deterministic-fixture",
        "chunk_count": len(deltas),
        "tool_observation_count": len(observations),
        "ttft_ms": round(ttft_ms, 2),
        "elapsed_ms": round(elapsed_ms, 2),
        "status": terminal["status"],
        "content_sha256": terminal["content_sha256"],
    }
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    records = _read_trace_records(trace_path)
    workflow_records = [
        item
        for item in records
        if item.get("workflow_name") == "controlled-conversation-mainline"
    ]
    span_stages = [
        item.get("stage") for item in workflow_records if item.get("record_type") == "span"
    ]
    assert span_stages[:10] == [
        "context",
        "entity_resolution",
        "route",
        "rewrite",
        "permission",
        "plan",
        "validate",
        "execute",
        "verify",
        "controller",
    ]
    assert span_stages[10:] in (
        ["synthesis", "termination"],
        ["replan", "controller", "synthesis", "termination"],
    )
    roots = [item for item in workflow_records if item.get("record_type") == "trace"]
    expected_trace_terminal = "ok" if terminal["status"] == "SUCCEEDED" else "partial"
    assert [item["status"] for item in roots] == ["started", expected_trace_terminal]
    assert roots[-1]["data"]["final_status"] in {"SUCCEEDED", "PARTIAL"}

    serialized = (
        json.dumps(records, ensure_ascii=False)
        + artifact_path.read_text(encoding="utf-8")
    ).lower()
    assert case.question not in serialized
    assert settings.openai_compatible_api_key.lower() not in serialized
    assert settings.tushare_token.lower() not in serialized
