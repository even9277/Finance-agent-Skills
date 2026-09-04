"""对话相关 Pydantic 模型"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator
from src.conversation.contracts import TerminalStatus


class SkillConfirmationCandidateResponse(BaseModel):
    """公开确认卡可展示的单个 Skill 候选。"""

    skill_name: str
    confidence: float
    version: str
    reason: str


class SkillConfirmationResponse(BaseModel):
    """REST/WS 共用且不包含工具权限的 Skill 确认载荷。"""

    candidates: list[SkillConfirmationCandidateResponse]
    reason: str
    registry_snapshot_hash: str


class ChatMessageRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="用户唯一标识")
    message: str = Field(..., min_length=1, max_length=10_000, description="用户消息内容")
    session_id: Optional[str] = Field(None, description="会话ID，为空则创建新会话")
    request_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        description="客户端可选请求关联标识；为空时服务端生成。",
    )
    explicit_skill: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="可选显式 Skill 标识；仍需服务端输入合同校验。",
    )

    @field_validator("user_id", "message", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        """在长度校验前去除边界空白，避免空白请求进入业务层。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("session_id", "request_id", mode="before")
    @classmethod
    def _normalize_optional_identifier(cls, value: object) -> object:
        """把空白可选标识视为未提供，保持旧客户端兼容。"""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("explicit_skill", mode="before")
    @classmethod
    def _normalize_optional_explicit_skill(cls, value: object) -> object:
        """把空白显式选择视为未选择，保持旧客户端兼容。"""
        if isinstance(value, str):
            return value.strip().lower() or None
        return value


class ChatContextWindow(BaseModel):
    used_tokens: int = 0
    budget_tokens: int = 0
    usage_percent: int = 0
    counting_mode: str = "estimated"
    compression_status: str = "idle"
    strategy: str = "dynamic_budget"
    updated_at: Optional[datetime] = None


class MemoryCommandResultResponse(BaseModel):
    """聊天接口返回的安全记忆命令结果；正文只允许出现在受限 preview 中。"""

    status: str
    command_kind: Optional[str] = None
    command_ref: Optional[str] = None
    affected_count: int = 0
    affected_record_ids: list[str] = Field(default_factory=list)
    consistency_status: str = "CONSISTENT"
    pending_confirmation_id: Optional[str] = None
    error_code: Optional[str] = None
    user_message: str = ""
    preview_items: list[dict[str, object]] = Field(default_factory=list)


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: str
    # Phase 3 新增：本次对话参考的用户画像（来自 user_invest_profiles，不调 Mem0）
    # 前端做 null 判断；ENABLE_MEMORY=false 时为 None
    memory_profile: Optional[dict] = None
    context_window: Optional[ChatContextWindow] = None
    memory_command: Optional[MemoryCommandResultResponse] = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="仅在本轮识别为记忆命令时返回；普通聊天保持旧响应形状。",
    )
    skill_confirmation: Optional[SkillConfirmationResponse] = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="仅在中置信 Skill 路由时返回；旧响应形状保持不变。",
    )


CHAT_STREAM_PROTOCOL_VERSION = "chat-stream-v2"


class ChatStreamEnvelope(BaseModel):
    """公开 WebSocket v2 帧的稳定关联与顺序字段。"""

    protocol_version: Literal["chat-stream-v2"] = CHAT_STREAM_PROTOCOL_VERSION
    request_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=128)
    sequence: int = Field(..., ge=1)


class ChatStreamStartFrame(ChatStreamEnvelope):
    """表示服务端已经准备好本轮事务会话。"""

    type: Literal["stream_start"] = "stream_start"


class ChatTraceSummaryFrame(ChatStreamEnvelope):
    """表示不含内部 Trace attributes 的阶段摘要。"""

    type: Literal["trace_summary"] = "trace_summary"
    stage: str = Field(..., min_length=1, max_length=64)
    status: str = Field(..., min_length=1, max_length=32)
    elapsed_ms: float = Field(..., ge=0)
    summary: str = Field(..., min_length=1, max_length=200)
    error_code: Optional[str] = Field(None, max_length=64)


class ChatPlanStepPreviewFrame(BaseModel):
    """表示已校验计划中的一个公开步骤摘要。"""

    step_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=100)
    purpose: str = Field(..., min_length=1, max_length=200)
    required: bool
    status: Literal["PLANNED"] = "PLANNED"
    depends_on: list[str] = Field(default_factory=list, max_length=64)
    subject_summary: str = Field(..., min_length=1, max_length=100)


class ChatPlanPreviewFrame(ChatStreamEnvelope):
    """表示 Validator 已接受的公开计划版本。"""

    type: Literal["plan_preview"] = "plan_preview"
    plan_id: str = Field(..., min_length=1, max_length=128)
    revision: int = Field(..., ge=1)
    validated: Literal[True] = True
    steps: list[ChatPlanStepPreviewFrame] = Field(default_factory=list, max_length=128)
    replan_reason: Optional[str] = Field(None, max_length=200)
    replaced_step_ids: list[str] = Field(default_factory=list, max_length=128)


class ChatStepStatusFrame(ChatStreamEnvelope):
    """表示一个稳定步骤 ID 的公开生命周期状态。"""

    type: Literal["step_status"] = "step_status"
    plan_id: str = Field(..., min_length=1, max_length=128)
    revision: int = Field(..., ge=1)
    step_id: str = Field(..., min_length=1, max_length=128)
    status: Literal[
        "PLANNED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
        "REPLANNED",
        "CANCELLED",
    ]
    elapsed_ms: Optional[float] = Field(None, ge=0)
    error_code: Optional[str] = Field(None, max_length=64)


class ChatToolStatusFrame(ChatStreamEnvelope):
    """表示一次工具尝试经过白名单投影后的公开状态。"""

    type: Literal["tool_status"] = "tool_status"
    plan_id: str = Field(..., min_length=1, max_length=128)
    revision: int = Field(..., ge=1)
    tool_call_id: str = Field(..., min_length=1, max_length=256)
    step_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    status: Literal["STARTED", "SUCCEEDED", "FAILED", "SKIPPED", "CANCELLED"]
    attempt: int = Field(..., ge=0)
    elapsed_ms: Optional[float] = Field(None, ge=0)
    parameter_summary: list[str] = Field(default_factory=list, max_length=5)
    result_summary: Optional[str] = Field(None, max_length=200)
    error_code: Optional[str] = Field(None, max_length=64)


class ChatVerificationSummaryFrame(ChatStreamEnvelope):
    """表示 Evidence Verifier 权威结论的公开摘要。"""

    type: Literal["verification_summary"] = "verification_summary"
    plan_id: str = Field(..., min_length=1, max_length=128)
    revision: int = Field(..., ge=1)
    sufficiency: Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]
    claim_level: Literal["ANALYTICAL", "DESCRIPTIVE", "REFUSE"]
    accepted_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    covered_dimensions: list[str] = Field(default_factory=list, max_length=32)
    missing_dimensions: list[str] = Field(default_factory=list, max_length=32)
    limitation: str = Field(..., min_length=1, max_length=200)


class ChatContentDeltaFrame(ChatStreamEnvelope):
    """表示可直接追加到同一助手消息的一段非空正文。"""

    type: Literal["content_delta"] = "content_delta"
    content: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=1)


class ChatContextUpdateFrame(ChatStreamEnvelope):
    """表示已提交终态对应的上下文窗口快照。"""

    type: Literal["context_update"] = "context_update"
    context_window: ChatContextWindow


class ChatMemoryCommandFrame(ChatStreamEnvelope):
    """表示已提交记忆命令的安全公开结果。"""

    type: Literal["memory_command"] = "memory_command"
    memory_command: MemoryCommandResultResponse


class ChatSkillConfirmationFrame(ChatStreamEnvelope):
    """表示需要用户确认的 Skill 候选，不包含工具权限。"""

    type: Literal["skill_confirm"] = "skill_confirm"
    confirmation: SkillConfirmationResponse


class ChatStreamEndFrame(ChatStreamEnvelope):
    """表示回答已经提交且本轮不会再产生正文增量。"""

    type: Literal["stream_end"] = "stream_end"
    status: TerminalStatus
    chunk_count: int = Field(..., ge=0)
    content_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class ChatStreamErrorFrame(ChatStreamEnvelope):
    """表示技术失败或边界拒绝的唯一安全终态。"""

    type: Literal["stream_error"] = "stream_error"
    code: Literal[
        "CHAT_STREAM_FAILED",
        "CHAT_INVALID_JSON",
        "CHAT_INVALID_REQUEST",
        "CHAT_INTERNAL_ERROR",
        "CHAT_STREAM_INCOMPLETE",
    ]
    message: str = Field(..., min_length=1, max_length=200)
    chunk_count: int = Field(..., ge=0)


class ChatSessionRenameRequest(BaseModel):
    title: str = Field(..., max_length=200)


class ChatMessage(BaseModel):
    id: int
    session_id: str
    role: str          # user | assistant | system
    content: str
    is_compressed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionListItem(BaseModel):
    session_id: str
    mode: str
    title: Optional[str] = None
    running_summary: Optional[str] = None
    context_window: Optional[ChatContextWindow] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionMessages(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    context_window: Optional[ChatContextWindow] = None


class ChatTemplateItem(BaseModel):
    id: str
    label: str
    content: str


class ChatSummaryItem(BaseModel):
    id: int
    session_id: str
    summary: str
    compressed_message_count: int
    total_message_count: int
    # Phase 2.1：更直观的压缩快照展示（兼容旧数据，字段可选）
    compressed_user_count: Optional[int] = None
    compressed_assistant_count: Optional[int] = None
    start_message_id: Optional[int] = None
    end_message_id: Optional[int] = None
    start_created_at: Optional[datetime] = None
    end_created_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionSummaries(BaseModel):
    session_id: str
    items: list[ChatSummaryItem]
