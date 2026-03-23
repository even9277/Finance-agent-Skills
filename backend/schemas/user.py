"""用户相关 Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserInitRequest(BaseModel):
    """冷启动：新用户提交初始偏好"""
    user_id: str = Field(..., description="前端生成的用户唯一标识（UUID）")
    display_name: Optional[str] = Field(None, max_length=100)
    preferences: Optional[dict] = Field(
        None,
        description="初始偏好，例如 {risk_profile, sectors, return_expectation, investment_horizon}",
    )


class UserProfileResponse(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    cold_start_done: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100)
