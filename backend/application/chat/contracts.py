"""定义聊天 Application 层的命令、输出与持久化快照。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.conversation.contracts import (
    ControllerDecision,
    ConversationResult,
    ConversationRunContext,
    Entity,
    ErrorCode,
    RouteDecision,
    TerminalStatus,
    VerificationResult,
)
from src.memory.contracts import WorkingState


@dataclass(frozen=True, slots=True)
class ChatCommand:
    """公开 REST/WS 进入单一聊天用例的协议无关命令。"""

    user_id: str
    message: str
    session_id: str | None = None
    request_id: str | None = None
    explicit_skill: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.message.strip():
            raise ValueError("user_id and message must not be blank")


@dataclass(frozen=True, slots=True)
class ChatContextWindowData:
    """与 Web 框架解耦的会话上下文预算快照。"""

    used_tokens: int = 0
    budget_tokens: int = 0
    usage_percent: int = 0
    counting_mode: str = "estimated"
    compression_status: str = "idle"
    strategy: str = "dynamic_budget"
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PreparedChatTurn:
    """Repository 在同一事务内准备好的会话输入。"""

    session_id: str
    recent_messages: tuple[str, ...] = ()
    running_summary: str | None = None
    memory_profile: dict[str, object] | None = None
    working_state: WorkingState = field(default_factory=WorkingState)


@dataclass(frozen=True, slots=True)
class ChatOutcome:
    """REST 和 WebSocket 必须共同消费的唯一应用输出。"""

    reply: str
    session_id: str
    status: TerminalStatus
    error_code: ErrorCode | None = None
    memory_profile: dict[str, object] | None = None
    working_state: WorkingState = field(default_factory=WorkingState)
    context_window: ChatContextWindowData | None = None
    workflow_result: ConversationResult | None = None

    @property
    def context(self) -> ConversationRunContext:
        """返回内部工作流关联上下文，供 Trace 和验收使用。"""
        if self.workflow_result is None:
            raise RuntimeError("workflow result is unavailable")
        return self.workflow_result.context

    @property
    def entity(self) -> Entity | None:
        """返回本轮权威实体。"""
        return self.workflow_result.entity if self.workflow_result is not None else None

    @property
    def route(self) -> RouteDecision | None:
        """返回本轮路由决策。"""
        return self.workflow_result.route if self.workflow_result is not None else None

    @property
    def verification(self) -> VerificationResult | None:
        """返回本轮证据验收结果。"""
        return self.workflow_result.verification if self.workflow_result is not None else None

    @property
    def controller(self) -> ControllerDecision | None:
        """返回本轮 Controller 决策。"""
        return self.workflow_result.controller if self.workflow_result is not None else None

    @property
    def missing_dimensions(self) -> tuple[str, ...]:
        """返回本轮缺失证据维度。"""
        return self.workflow_result.missing_dimensions if self.workflow_result is not None else ()

    @property
    def tool_call_count(self) -> int:
        """返回本轮真实工具调用次数。"""
        return self.workflow_result.tool_call_count if self.workflow_result is not None else 0


@dataclass(frozen=True, slots=True)
class ChatSessionRecord:
    """会话列表读取模型。"""

    session_id: str
    mode: str
    title: str | None
    running_summary: str | None
    context_window: ChatContextWindowData
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    """会话消息读取模型。"""

    id: int
    session_id: str
    role: str
    content: str
    is_compressed: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatSummaryRecord:
    """会话压缩摘要读取模型。"""

    id: int
    session_id: str
    summary: str
    compressed_message_count: int
    total_message_count: int
    created_at: datetime
    compressed_user_count: int | None = None
    compressed_assistant_count: int | None = None
    start_message_id: int | None = None
    end_message_id: int | None = None
    start_created_at: datetime | None = None
    end_created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChatMessagesPage:
    """消息历史与对应上下文快照。"""

    session_id: str
    messages: tuple[ChatMessageRecord, ...] = field(default_factory=tuple)
    context_window: ChatContextWindowData | None = None
