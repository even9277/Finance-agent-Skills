"""对话相关 Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    user_id: str = Field(..., description="用户唯一标识")
    message: str = Field(..., description="用户消息内容")
    session_id: Optional[str] = Field(None, description="会话ID，为空则创建新会话")
    sop_skill_id: Optional[str] = Field(
        None,
        description="用户从面板显式选择的 SOP skill_id；为空时仅走 tushare/fallback 路由",
    )


class SopSkillListItem(BaseModel):
    name: str
    official_name: str = ""
    description: str = ""
    execution_mode: str = "deterministic"


class ChatContextWindow(BaseModel):
    used_tokens: int = 0
    budget_tokens: int = 0
    usage_percent: int = 0
    counting_mode: str = "estimated"
    compression_status: str = "idle"
    strategy: str = "dynamic_budget"
    updated_at: Optional[datetime] = None
    memory_hint: Optional[str] = None
    memory_hint_level: Optional[str] = None
    # 当前前端主要展示 token 预算与风险区间；旧异步 worker 已下线。
    model_window_tokens: int = 0
    working_budget_tokens: int = 0
    reserved_output_tokens: int = 0
    budget_status: str = "healthy"


class ChatRouteSummaryUserFacing(BaseModel):
    """User-visible portion of the route summary."""
    skill_label: str = ""
    analysis_mode: str = ""
    evidence_status: str = ""
    failure_hint: str = ""


class ChatRouteSummaryDebug(BaseModel):
    """Developer-only debug portion of the route summary."""
    route_kind: str = ""
    grounding_policy: str = ""
    claim_policy: str = ""
    skill_contract: str = ""
    evidence_tier: str = ""
    evidence_missing_dimensions: list[str] = Field(default_factory=list)
    evidence_allowed_claim_level: str = ""
    failure_code: str = ""


class ChatRouteSummary(BaseModel):
    selected_skill_family: str = "fallback"
    selected_skill: str = "fallback"
    skill_name: Optional[str] = None
    analysis_mode: str = "general_chat"
    execution_policy: str = "agentic"
    reply_mode: str = "fallback"
    route_confidence: float = 0.0
    used_tools: bool = False
    evidence_ok: bool = False
    tools_used: list[str] = Field(default_factory=list)
    tools_attempted: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # FIX-1/FIX-9: layered route summary
    route_kind: str = ""
    grounding_policy: str = ""
    claim_policy: str = ""
    skill_contract: str = ""
    failure_code: str = ""
    user_facing: Optional[ChatRouteSummaryUserFacing] = None
    debug: Optional[ChatRouteSummaryDebug] = None


class PlanPreviewStep(BaseModel):
    step_id: str = ""
    title: str = ""
    tool_name: str = ""
    required: bool = True
    evidence_type: str = ""
    status: str = "planned"


class PlanPreviewPayload(BaseModel):
    plan_id: str = ""
    items: list[PlanPreviewStep] = Field(default_factory=list)


class StepStatusPayload(BaseModel):
    plan_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    status: str = "planned"
    message: str = ""


class VerificationSummaryPayload(BaseModel):
    plan_id: str = ""
    status: str = ""
    evidence_score: int = 0
    allowed_claim_level: str = ""
    missing_dimensions: list[str] = Field(default_factory=list)


class SkillConfirmOption(BaseModel):
    key: str = ""
    label: str = ""
    recommended: bool = False


class SkillConfirmPayload(BaseModel):
    session_id: str
    options: list[SkillConfirmOption] = Field(default_factory=list)
    reasoning: str = ""
    resolved_query: str = ""
    confidence: float = 0.0


class SkillConfirmRequest(BaseModel):
    user_id: str = Field(..., description="用户唯一标识")
    user_choice: str = Field(..., description="用户选择的路由 key，如 fund-compare、tushare-data、fallback")


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: str
    # Phase 3 新增：本次对话参考的用户画像（来自 user_invest_profiles，不调 Mem0）
    # 前端做 null 判断；ENABLE_MEMORY=false 时为 None
    memory_profile: Optional[dict] = None
    context_window: Optional[ChatContextWindow] = None
    route_summary: Optional[ChatRouteSummary] = None
    plan_artifact: Optional[dict] = None
    skill_artifact: Optional[dict] = None
    verification: Optional[dict] = None
    allowed_claim_level: Optional[str] = None
    # STM：当前会话滚动摘要（压缩后写入 sessions.running_summary）
    running_summary: Optional[str] = None
    running_summary_state: Optional[dict] = None
    running_summary_mode: Optional[str] = None
    # 低置信度路由：需用户确认后继续，此时 reply 可能为空
    skill_confirm: Optional[SkillConfirmPayload] = None


class ChatSessionRenameRequest(BaseModel):
    title: str = Field(..., max_length=200)


class ChatMessage(BaseModel):
    id: int
    session_id: str
    role: str          # user | assistant | system
    content: str
    is_compressed: bool
    created_at: datetime
    route_summary: Optional[ChatRouteSummary] = None
    plan_artifact: Optional[dict] = None
    skill_artifact: Optional[dict] = None
    verification: Optional[dict] = None
    allowed_claim_level: Optional[str] = None

    model_config = {"from_attributes": True}


class ChatSessionListItem(BaseModel):
    session_id: str
    mode: str
    title: Optional[str] = None
    running_summary: Optional[str] = None
    running_summary_state: Optional[dict] = None
    running_summary_mode: Optional[str] = None
    context_window: Optional[ChatContextWindow] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionMessages(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    running_summary: Optional[str] = None
    running_summary_state: Optional[dict] = None
    running_summary_mode: Optional[str] = None
    context_window: Optional[ChatContextWindow] = None


class ChatTemplateItem(BaseModel):
    id: str
    label: str
    content: str


class ChatSummaryItem(BaseModel):
    id: int
    session_id: str
    summary: str
    summary_payload: Optional[dict] = None
    summary_mode: Optional[str] = None
    summary_trigger: Optional[str] = None
    compressed_message_count: int
    total_message_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionSummaries(BaseModel):
    session_id: str
    items: list[ChatSummaryItem]
