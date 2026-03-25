"""JWT 鉴权中间件与依赖。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, WebSocket, status
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import settings
from backend.services.auth_service import AuthError, decode_access_token

_PUBLIC_PATH_PREFIXES = (
    "/api/health",
    "/api/auth/login",
    "/api/docs",
    "/api/openapi.json",
)


@dataclass
class AuthContext:
    account_id: str
    username: str
    user_id: str


def _extract_bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return parts[1].strip()
    return None


def _build_auth_context(token: str) -> AuthContext:
    payload = decode_access_token(token)
    return AuthContext(
        account_id=payload["sub"],
        username=payload["username"],
        user_id=payload["user_id"],
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    只负责解析并把鉴权结果挂到 request.state。
    是否强制要求登录由依赖层控制，避免影响 health/docs/login 等公开接口。
    """

    async def dispatch(self, request: Request, call_next):
        request.state.auth_ctx = None
        request.state.auth_error = None

        if not settings.auth_enabled:
            return await call_next(request)

        if request.url.path.startswith(_PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        token = _extract_bearer_token(request.headers.get("Authorization"))
        if token:
            try:
                request.state.auth_ctx = _build_auth_context(token)
            except AuthError as exc:
                request.state.auth_error = str(exc)

        return await call_next(request)


async def require_auth(request: Request) -> AuthContext:
    if not settings.auth_enabled:
        return AuthContext(account_id="auth-disabled", username="auth-disabled", user_id="")

    cached = getattr(request.state, "auth_ctx", None)
    if cached:
        return cached

    cached_error = getattr(request.state, "auth_error", None)
    if cached_error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=cached_error)

    token = _extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或缺少 Bearer Token")

    try:
        ctx = _build_auth_context(token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    request.state.auth_ctx = ctx
    return ctx


def ensure_user_access(requested_user_id: str | None, auth: AuthContext) -> str:
    if not settings.auth_enabled:
        return requested_user_id or ""
    if not requested_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="目标数据未绑定用户，无法访问")
    if requested_user_id and requested_user_id != auth.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问其他用户数据")
    return auth.user_id


async def require_query_user(
    request: Request,
    user_id: str,
    auth: AuthContext = Depends(require_auth),
) -> str:
    _ = request
    return ensure_user_access(user_id, auth)


async def authenticate_websocket(websocket: WebSocket) -> AuthContext:
    if not settings.auth_enabled:
        return AuthContext(account_id="auth-disabled", username="auth-disabled", user_id="")

    token = websocket.query_params.get("token")
    if not token:
        token = _extract_bearer_token(websocket.headers.get("Authorization"))
    if not token:
        raise AuthError("未登录或缺少 token")
    return _build_auth_context(token)


def auth_context_to_dict(auth: AuthContext) -> dict[str, Any]:
    return {
        "account_id": auth.account_id,
        "username": auth.username,
        "user_id": auth.user_id,
    }
