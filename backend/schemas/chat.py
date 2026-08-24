"""对话相关 Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ChatMessageRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="用户唯一标识")
    message: str = Field(..., min_length=1, max_length=10_000, description="用户消息内容")
    session_id: Optional[str] = Field(None, description="会话ID，为空则创建新会话")

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


class ChatContextWindow(BaseModel):
    used_tokens: int = 0
    budget_tokens: int = 0
    usage_percent: int = 0
    counting_mode: str = "estimated"
    compression_status: str = "idle"
    strategy: str = "dynamic_budget"
    updated_at: Optional[datetime] = None


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: str
    # Phase 3 新增：本次对话参考的用户画像（来自 user_invest_profiles，不调 Mem0）
    # 前端做 null 判断；ENABLE_MEMORY=false 时为 None
    memory_profile: Optional[dict] = None
    context_window: Optional[ChatContextWindow] = None


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
