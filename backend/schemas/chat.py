"""对话相关 Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    user_id: str = Field(..., description="用户唯一标识")
    message: str = Field(..., description="用户消息内容")
    session_id: Optional[str] = Field(None, description="会话ID，为空则创建新会话")


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: str
    # Phase 3 新增：本次对话参考的用户画像（来自 user_invest_profiles，不调 Mem0）
    # 前端做 null 判断；ENABLE_MEMORY=false 时为 None
    memory_profile: Optional[dict] = None


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionMessages(BaseModel):
    session_id: str
    messages: list[ChatMessage]


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
