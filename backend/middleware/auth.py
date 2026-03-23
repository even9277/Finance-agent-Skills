"""
鉴权中间件（Phase 1: 预留，Phase 4 实现 JWT）
当前阶段：透传，不做任何鉴权校验。
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    """Phase 4 实现：校验 Authorization: Bearer <token> 头部。"""

    async def dispatch(self, request: Request, call_next):
        # Phase 1: 直接放行
        response = await call_next(request)
        return response
