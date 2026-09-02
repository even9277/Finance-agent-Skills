"""定义聊天 Application 层的命令、输出与持久化快照。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from src.conversation.contracts import (
    ControllerDecision,
    ConversationResult,
    ConversationRunContext,
    Entity,
    ErrorCode,
    RouteDecision,
    SkillConfirmation,
    TerminalStatus,
    VerificationResult,
)
from src.memory.contracts import WorkingState
from backend.application.memory.commands import MemoryCommandResult


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
    memory_command: MemoryCommandResult | None = None
    skill_confirmation: SkillConfirmation | None = None

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


class ChatStreamEventKind(StrEnum):
    """Application 流式输出的有限生命周期类型。"""

    STARTED = "STARTED"
    CONTENT_DELTA = "CONTENT_DELTA"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ChatStreamFailureCode(StrEnum):
    """Application 流式技术失败的稳定机器码。"""

    STREAM_FAILED = "CHAT_STREAM_FAILED"


@dataclass(frozen=True, slots=True)
class ChatStreamStarted:
    """表示会话已在同一事务中完成准备，可以开始发送公开事件。"""

    session_id: str
    request_id: str
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.STARTED, init=False)


@dataclass(frozen=True, slots=True)
class ChatContentDelta:
    """表示模型或显式降级分支产生的一段非空回答文本。"""

    session_id: str
    request_id: str
    content: str
    chunk_index: int
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.CONTENT_DELTA, init=False)

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("chat content delta must not be empty")
        if self.chunk_index < 1:
            raise ValueError("chat content delta index must start from one")


@dataclass(frozen=True, slots=True)
class ChatStreamCompleted:
    """表示唯一聊天终态已提交，可安全发送公开完成帧。"""

    session_id: str
    request_id: str
    outcome: ChatOutcome
    chunk_count: int
    content_sha256: str
    ttft_ms: float | None
    elapsed_ms: float
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.COMPLETED, init=False)


@dataclass(frozen=True, slots=True)
class ChatStreamFailed:
    """表示技术失败已回滚，只携带稳定错误码和安全统计。"""

    session_id: str
    request_id: str
    error_code: ChatStreamFailureCode
    chunk_count: int
    ttft_ms: float | None
    elapsed_ms: float
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.FAILED, init=False)


type ChatStreamEvent = ChatStreamStarted | ChatContentDelta | ChatStreamCompleted | ChatStreamFailed


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
