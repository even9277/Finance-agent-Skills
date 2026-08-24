"""锁定当前受控对话可复用的短期记忆与上下文行为。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.chat.contracts import ChatCommand, PreparedChatTurn  # noqa: E402
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import (  # noqa: E402
    FakeModelProvider,
    FakeToolProvider,
    InMemoryConversationRepository,
    InMemoryTraceSink,
)
from backend.db.models import Session  # noqa: E402
from backend.services.stm_context_service import (  # noqa: E402
    build_context_window_payload,
    calculate_live_prompt_usage,
)
from src.conversation.context import ContextBuilder  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ConversationRequest,
    ConversationResult,
)
from src.conversation.workflow import ControlledConversationWorkflow  # noqa: E402


@dataclass(slots=True)
class _PreparedMemoryRepository(InMemoryConversationRepository):
    """为测试注入旧摘要和既有画像，不增加生产侧记忆行为。"""

    running_summary: str = ""
    memory_profile: dict[str, object] | None = None

    async def prepare_turn(self, command: ChatCommand) -> PreparedChatTurn:
        """返回带有历史摘要和画像的固定会话输入。"""
        return PreparedChatTurn(
            session_id=command.session_id or "session-memory-characterization",
            recent_messages=("上一轮讨论过宁德时代",),
            running_summary=self.running_summary,
            memory_profile=self.memory_profile,
        )


class _RecordingWorkflow(ControlledConversationWorkflow):
    """记录 Application 传入 Workflow 的历史边界，同时执行真实受控链。"""

    received_recent_messages: tuple[str, ...] = ()
    received_running_summary: str | None = None

    async def run(
        self,
        request: ConversationRequest,
        *,
        recent_messages: tuple[str, ...] = (),
        running_summary: str | None = None,
    ) -> ConversationResult:
        """记录历史参数并复用真实工作流实现。"""
        self.received_recent_messages = recent_messages
        self.received_running_summary = running_summary
        return await super().run(
            request,
            recent_messages=recent_messages,
            running_summary=running_summary,
        )


@pytest.mark.unit
def test_context_window_payload_clamps_usage_and_preserves_status() -> None:
    """确认历史 token 超预算时只封顶展示，不产生负数或异常百分比。"""
    session = Session(
        user_id="fixture-user-memory",
        context_token_count=160,
        context_budget_tokens=100,
        compression_status="queued",
        context_updated_at=None,
    )

    payload = build_context_window_payload(session, counting_mode="estimated")

    assert payload.used_tokens == 160
    assert payload.budget_tokens == 100
    assert payload.usage_percent == 100
    assert payload.compression_status == "queued"
    assert payload.counting_mode == "estimated"


@pytest.mark.unit
def test_live_prompt_usage_includes_response_and_memory_reserves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认预算估算会计入回答和记忆预留，防止只按历史消息裁剪。"""
    session = Session(user_id="fixture-user-memory", context_token_count=25)
    monkeypatch.setattr(
        "backend.services.stm_context_service.settings.stm_response_reserve_tokens",
        7,
    )
    monkeypatch.setattr(
        "backend.services.stm_context_service.settings.stm_memory_reserve_tokens",
        3,
    )

    used_tokens, counting_mode = calculate_live_prompt_usage(
        session,
        system_prompt="",
        memory_system_prompt="",
        user_message="",
    )

    assert used_tokens == 35
    assert counting_mode in {"exact", "estimated"}


@pytest.mark.unit
def test_current_message_wins_over_conflicting_summary_and_profile_is_not_evidence() -> None:
    """确认上下文读取历史输入，但当前实体优先且画像不冒充金融证据。"""

    async def run_case() -> None:
        packet = ContextBuilder().build(
            ConversationRequest(
                user_id="fixture-user-memory",
                session_id="fixture-session-memory",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            ),
            recent_messages=("上一轮讨论过宁德时代",),
            running_summary="此前主要讨论宁德时代 300750.SZ。",
        )
        assert packet.current_message == "查询贵州茅台 600519.SH 的基础信息和近期行情"
        assert packet.recent_messages == ("上一轮讨论过宁德时代",)
        assert packet.running_summary == "此前主要讨论宁德时代 300750.SZ。"

        model = FakeModelProvider()
        tool = FakeToolProvider()
        repository = _PreparedMemoryRepository(
            running_summary="此前主要讨论宁德时代 300750.SZ。",
            memory_profile={
                "risk_level": "conservative",
                "sectors": ["半导体"],
            },
        )
        workflow = _RecordingWorkflow(
            model=model,
            tool=tool,
            trace=InMemoryTraceSink(),
        )
        outcome = await ControlledChatUseCase(
            workflow=workflow,
            repository=repository,
        ).execute(
            ChatCommand(
                user_id="fixture-user-memory",
                session_id="fixture-session-memory",
                message="查询贵州茅台 600519.SH 的基础信息和近期行情",
            )
        )

        assert outcome.entity is not None
        assert outcome.entity.symbol == "600519.SH"
        assert workflow.received_recent_messages == ("上一轮讨论过宁德时代",)
        assert workflow.received_running_summary == "此前主要讨论宁德时代 300750.SZ。"
        assert outcome.memory_profile == {
            "risk_level": "conservative",
            "sectors": ["半导体"],
        }
        assert outcome.tool_call_count == 2
        assert len(model.calls) == 1
        assert {
            fact.source for fact in model.calls[0].context.accepted_evidence
        } == {
            "fixture:get_stock_basic_info:v1",
            "fixture:get_market_bars:v1",
        }

    asyncio.run(run_case())
