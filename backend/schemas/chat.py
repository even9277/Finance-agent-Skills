"""对话相关 Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("session_id", mode="before")
    @classmethod
    def _normalize_optional_session_id(cls, value: object) -> object:
        """把空白 session_id 视为新会话，保持旧客户端兼容。"""
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
