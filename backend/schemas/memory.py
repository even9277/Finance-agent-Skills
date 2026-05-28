"""
记忆/画像相关 Pydantic 模型 - Phase 3 完整实现

字段设计与 user_invest_profiles 表对齐，同时保持 Phase 1 API 路径兼容。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────
# 用户画像（来自 user_invest_profiles 权威表）
# ─────────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    """Phase 1 兼容字段 + Phase 3 扩展字段"""
    # Phase 1 兼容字段（保持不变）
    risk_profile: Optional[str] = None       # = risk_level（别名，兼容旧前端）
    sectors: list[str] = []
    return_expectation: Optional[float] = None  # = expected_return_min（别名）
    investment_horizon: Optional[str] = None
    watchlist: list[str] = []

    # Phase 3 扩展字段（结构化）
    risk_level: Optional[str] = None          # conservative/moderate/balanced/aggressive/speculative
    expected_return_min: Optional[float] = None
    expected_return_max: Optional[float] = None
    constraints: list[str] = []
    response_pref: str = "balanced"           # concise/balanced/detailed/risk_first
    updated_by: Optional[str] = None          # user/system/llm
    updated_at: Optional[str] = None


class MemoryProfileResponse(BaseModel):
    user_id: str
    profile: UserProfile
    total_memories: int = 0
    # Phase 3：来源统计（MemorySidebar 底部展示）
    stats: dict[str, Any] = {}
    note: str = "Phase 3: 来自 PostgreSQL user_invest_profiles"


# ─────────────────────────────────────────────────────────────
# 记忆条目（来自 Mem0 语义层）
# ─────────────────────────────────────────────────────────────

class MemoryItem(BaseModel):
    id: str
    content: str
    category: str = ""
    source: str = ""                          # ui/cold_start/chat_inferred/report_inferred
    confidence: float = 1.0
    evidence_ref: str = ""                    # 指向 messages.id 或 reports.id
    # 必有字段：ISO8601 字符串；Mem0/降级路径无法解析时为空串
    created_at: str = Field(default="", description="创建时间 ISO8601，未知时为空串")
    mem0_id: str = ""
    metadata: dict[str, Any] = {}

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_created_at(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        if hasattr(v, "isoformat"):
            try:
                return v.isoformat()
            except Exception:
                return str(v)
        return str(v)

class MemoryItemsResponse(BaseModel):
    items: list[MemoryItem] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


# ─────────────────────────────────────────────────────────────
# 画像更新请求（各组件调用对应接口）
# ─────────────────────────────────────────────────────────────

class MemoryUpdateRiskRequest(BaseModel):
    risk_profile: str = Field(
        ...,
        description="风险偏好: conservative/moderate/balanced/aggressive/speculative",
    )


class MemoryUpdateSectorsRequest(BaseModel):
    sectors: list[str] = Field(..., description="关注板块列表")


class MemoryUpdateReturnRequest(BaseModel):
    return_expectation: float = Field(..., ge=0, le=100, description="期望收益下限 (%)")
    return_max: Optional[float] = Field(None, ge=0, le=100, description="期望收益上限 (%)")
    investment_horizon: Optional[str] = Field(
        None,
        description="投资周期: ultra_short/short/swing/long",
    )


class MemoryUpdateHorizonRequest(BaseModel):
    investment_horizon: str = Field(
        ...,
        description="投资周期: ultra_short/short/swing/long",
    )


class MemoryUpdateResponsePrefRequest(BaseModel):
    response_pref: str = Field(
        ...,
        description="回答偏好: concise/balanced/detailed/risk_first",
    )


# ─────────────────────────────────────────────────────────────
# 记忆条目 CRUD 请求
# ─────────────────────────────────────────────────────────────

class MemoryAddRequest(BaseModel):
    category: str
    content: str
    metadata: dict[str, Any] = {}


class MemoryUpdateRequest(BaseModel):
    content: str
    metadata: dict[str, Any] = {}


# ─────────────────────────────────────────────────────────────
# 证据溯源响应
# ─────────────────────────────────────────────────────────────

class MemoryEvidenceResponse(BaseModel):
    memory_id: str
    memory_text: str = ""
    source: str = ""
    session_id: str = ""
    run_id: str = ""
    evidence_ref: str = ""
    evidence: list[dict] = []
