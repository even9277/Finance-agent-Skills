"""使用真实 LLM 与 Tushare 验收公开 HTTP 受控对话主链。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from backend.config import settings  # noqa: E402
from backend.db.database import Base, get_db  # noqa: E402
from backend.db.models import Message, User  # noqa: E402
from backend.infrastructure.chat.providers import (  # noqa: E402
    OpenAICompatibleModelProvider,
    TushareToolProvider,
)
from backend.routers.chat import router as chat_router  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ModelSynthesisRequest,
    ToolCall,
    ToolObservation,
)
from src.tools import skill_trace  # noqa: E402
from src.tools.tushare_client import configure_tushare_client_factory  # noqa: E402

_LIVE_SWITCH = "RUN_PROTECTED_LIVE_E2E"
_QUESTION = "查询贵州茅台 600519.SH 的基础信息和近期行情"
_USER_ID = "live-controlled-user"


def _require_protected_live_configuration() -> None:
    """拒绝误触发和缺少凭证的伪 live 成功。"""
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
        pytest.fail("保护性 live 测试缺少必需配置：" + ", ".join(missing))


def _read_trace_records(path: Path) -> list[dict[str, Any]]:
    """读取测试隔离目录中的 JSONL Trace。"""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.live
@pytest.mark.e2e
def test_live_http_chain_uses_real_llm_tushare_sqlite_and_trace(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """从公开 HTTP 入口真实调用只读数据源与模型，并核验完整受控链。"""
    _require_protected_live_configuration()

    database_path = tmp_path / "live-controlled-chat.db"
    trace_path = tmp_path / "live-controlled-chat-trace.jsonl"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    request.addfinalizer(lambda: asyncio.run(engine.dispose()))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare_database() -> None:
        """创建临时数据库及外键所需的隔离测试用户。"""
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(User(id=_USER_ID, display_name="protected-live-e2e"))
            await session.commit()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        """让公开 Router 只连接本测试的临时 SQLite。"""
        async with session_factory() as session:
            yield session

    async def read_persisted_messages() -> list[Message]:
        """读取本轮原子落库的消息，验证没有写入生产数据库。"""
        async with session_factory() as session:
            result = await session.execute(select(Message).order_by(Message.id))
            return list(result.scalars().all())

    real_tool_execute = TushareToolProvider.execute
    real_model_synthesize = OpenAICompatibleModelProvider.synthesize
    observations: list[ToolObservation] = []
    model_call_count = 0

    async def audited_tool_execute(
        provider: TushareToolProvider,
        call: ToolCall,
    ) -> ToolObservation:
        """调用真实 Tushare 实现，仅在内存记录低风险返回合同。"""
        observation = await real_tool_execute(provider, call)
        observations.append(observation)
        return observation

    async def audited_model_synthesize(
        provider: OpenAICompatibleModelProvider,
        request: ModelSynthesisRequest,
    ) -> str:
        """调用真实模型实现，仅累计调用次数，不记录 Prompt 或回答。"""
        nonlocal model_call_count
        model_call_count += 1
        return await real_model_synthesize(provider, request)

    app = FastAPI()
    app.include_router(chat_router, prefix="/api/chat")
    app.dependency_overrides[get_db] = override_get_db

    asyncio.run(prepare_database())
    # Tushare 底层客户端读取环境变量；这里复用已加载的本地忽略配置且绝不打印值。
    previous_tushare_token = os.environ.get("TUSHARE_TOKEN")
    os.environ["TUSHARE_TOKEN"] = settings.tushare_token
    configure_tushare_client_factory(None)
    try:
        with (
            patch.object(settings, "auth_enabled", False),
            patch.object(settings, "enable_memory", False),
            patch.object(settings, "enable_stm", False),
            patch.object(settings, "enable_langfuse", False),
            patch.object(skill_trace, "_JSONL_PATH", trace_path),
            patch.object(TushareToolProvider, "execute", new=audited_tool_execute),
            patch.object(
                OpenAICompatibleModelProvider,
                "synthesize",
                new=audited_model_synthesize,
            ),
        ):
            response = TestClient(app, raise_server_exceptions=False).post(
                "/api/chat/message",
                json={"user_id": _USER_ID, "message": _QUESTION},
            )
    finally:
        configure_tushare_client_factory(None)
        if previous_tushare_token is None:
            os.environ.pop("TUSHARE_TOKEN", None)
        else:
            os.environ["TUSHARE_TOKEN"] = previous_tushare_token

    assert response.status_code == 200, response.text[:300]
    payload = response.json()
    assert payload["session_id"]
    assert isinstance(payload["reply"], str) and payload["reply"].strip()
    assert model_call_count == 1
    assert observations
    assert {item.symbol for item in observations} == {"600519.SH"}
    assert all(item.source.startswith("tushare:") for item in observations)
    assert all(item.facts for item in observations)

    persisted = asyncio.run(read_persisted_messages())
    assert [item.role for item in persisted] == ["user", "assistant"]
    assert persisted[0].content == _QUESTION
    assert persisted[1].content == payload["reply"]

    records = _read_trace_records(trace_path)
    workflow_records = [
        item
        for item in records
        if item.get("workflow_name") == "controlled-conversation-mainline"
    ]
    trace_ids = {str(item["trace_id"]) for item in workflow_records}
    run_ids = {str(item["run_id"]) for item in workflow_records}
    stages = [item.get("stage") for item in workflow_records if item["record_type"] == "span"]
    assert len(trace_ids) == 1
    assert len(run_ids) == 1
    assert stages == [
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
        "synthesis",
        "termination",
    ]
    roots = [item for item in workflow_records if item["record_type"] == "trace"]
    assert [item["status"] for item in roots] == ["started", "ok"]
    assert roots[-1]["data"]["final_status"] == "SUCCEEDED"

    serialized_trace = json.dumps(records, ensure_ascii=False).lower()
    assert _QUESTION not in serialized_trace
    assert settings.openai_compatible_api_key.lower() not in serialized_trace
    assert settings.tushare_token.lower() not in serialized_trace
