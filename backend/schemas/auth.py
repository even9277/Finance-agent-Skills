"""鉴权相关 Pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class AuthRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)


class AuthUserResponse(BaseModel):
    user_id: str
    username: str
    display_name: str | None = None
    cold_start_done: bool
    created_at: datetime


class AuthLoginResponse(AuthUserResponse):
    access_token: str
    token_type: str = "bearer"


class AuthLogoutResponse(BaseModel):
    message: str = "已退出登录"
