"""定义聊天 Application 层的命令、输出与持久化快照。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeAlias

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
    TRACE_SUMMARY = "TRACE_SUMMARY"
    PLAN_PREVIEW = "PLAN_PREVIEW"
    STEP_STATUS = "STEP_STATUS"
    TOOL_STATUS = "TOOL_STATUS"
    VERIFICATION_SUMMARY = "VERIFICATION_SUMMARY"
    CONTENT_DELTA = "CONTENT_DELTA"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ChatStreamFailureCode(StrEnum):
    """Application 流式技术失败的稳定机器码。"""

    STREAM_FAILED = "CHAT_STREAM_FAILED"


class ChatStepLifecycleStatus(StrEnum):
    """客户端可消费的步骤有限生命周期。"""

    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    REPLANNED = "REPLANNED"
    CANCELLED = "CANCELLED"


class ChatToolLifecycleStatus(StrEnum):
    """客户端可消费的单次工具调用有限生命周期。"""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class ChatEvidenceSufficiency(StrEnum):
    """Verifier 权威结果对应的公开证据充分性。"""

    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class ChatStreamStarted:
    """表示会话已在同一事务中完成准备，可以开始发送公开事件。"""

    session_id: str
    request_id: str
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.STARTED, init=False)


@dataclass(frozen=True, slots=True)
class ChatTraceSummary:
    """表示不含内部 attributes 的阶段执行摘要。"""

    session_id: str
    request_id: str
    stage: str
    status: str
    elapsed_ms: float
    summary: str
    error_code: str | None = None
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.TRACE_SUMMARY, init=False)


@dataclass(frozen=True, slots=True)
class ChatPlanStepPreview:
    """表示已校验计划中的一个用户安全步骤摘要。"""

    step_id: str
    title: str
    purpose: str
    required: bool
    status: Literal[ChatStepLifecycleStatus.PLANNED]
    depends_on: tuple[str, ...]
    subject_summary: str


@dataclass(frozen=True, slots=True)
class ChatPlanPreview:
    """表示 Validator 已接受的一个计划版本。"""

    session_id: str
    request_id: str
    plan_id: str
    revision: int
    validated: Literal[True]
    steps: tuple[ChatPlanStepPreview, ...]
    replan_reason: str | None = None
    replaced_step_ids: tuple[str, ...] = ()
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.PLAN_PREVIEW, init=False)


@dataclass(frozen=True, slots=True)
class ChatStepStatus:
    """表示一个稳定步骤 ID 的公开状态变化。"""

    session_id: str
    request_id: str
    plan_id: str
    revision: int
    step_id: str
    status: ChatStepLifecycleStatus
    elapsed_ms: float | None = None
    error_code: str | None = None
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.STEP_STATUS, init=False)


@dataclass(frozen=True, slots=True)
class ChatToolStatus:
    """表示一次工具尝试经过白名单裁剪后的公开状态。"""

    session_id: str
    request_id: str
    plan_id: str
    revision: int
    tool_call_id: str
    step_id: str
    display_name: str
    status: ChatToolLifecycleStatus
    attempt: int
    parameter_summary: tuple[str, ...]
    elapsed_ms: float | None = None
    result_summary: str | None = None
    error_code: str | None = None
    kind: ChatStreamEventKind = field(default=ChatStreamEventKind.TOOL_STATUS, init=False)


@dataclass(frozen=True, slots=True)
class ChatVerificationSummary:
    """表示 Verifier 结论的用户安全摘要。"""

    session_id: str
    request_id: str
    plan_id: str
    revision: int
    sufficiency: ChatEvidenceSufficiency
    claim_level: Literal["ANALYTICAL", "DESCRIPTIVE", "REFUSE"]
    accepted_count: int
    rejected_count: int
    covered_dimensions: tuple[str, ...]
    missing_dimensions: tuple[str, ...]
    limitation: str
    kind: ChatStreamEventKind = field(
        default=ChatStreamEventKind.VERIFICATION_SUMMARY,
        init=False,
    )


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


ChatStreamEvent: TypeAlias = (
    ChatStreamStarted
    | ChatTraceSummary
    | ChatPlanPreview
    | ChatStepStatus
    | ChatToolStatus
    | ChatVerificationSummary
    | ChatContentDelta
    | ChatStreamCompleted
    | ChatStreamFailed
)


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
