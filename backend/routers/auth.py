"""登录鉴权路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.middleware.auth import AuthContext, require_auth
from backend.schemas.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    AuthRegisterRequest,
    AuthUserResponse,
)
from backend.services.auth_service import (
    AuthError,
    authenticate_user,
    create_access_token,
    get_account_and_user_by_payload,
    register_user,
)

router = APIRouter()


@router.post("/login", response_model=AuthLoginResponse, summary="账号登录")
async def login(body: AuthLoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        account, user = await authenticate_user(db, body.username.strip(), body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token = create_access_token(
        account_id=account.id,
        username=account.username,
        user_id=account.user_id,
    )
    return AuthLoginResponse(
        access_token=token,
        user_id=user.id,
        username=account.username,
        display_name=user.display_name,
        cold_start_done=user.cold_start_done,
        created_at=user.created_at,
    )


@router.post("/register", response_model=AuthLoginResponse, summary="注册新账号")
async def register(body: AuthRegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        account, user = await register_user(
            db,
            username=body.username,
            password=body.password,
            display_name=body.display_name,
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = create_access_token(
        account_id=account.id,
        username=account.username,
        user_id=account.user_id,
    )
    return AuthLoginResponse(
        access_token=token,
        user_id=user.id,
        username=account.username,
        display_name=user.display_name,
        cold_start_done=user.cold_start_done,
        created_at=user.created_at,
    )


@router.get("/me", response_model=AuthUserResponse, summary="获取当前登录用户")
async def me(auth: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    try:
        account, user = await get_account_and_user_by_payload(
            db,
            {
                "sub": auth.account_id,
                "username": auth.username,
                "user_id": auth.user_id,
            },
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return AuthUserResponse(
        user_id=user.id,
        username=account.username,
        display_name=user.display_name,
        cold_start_done=user.cold_start_done,
        created_at=user.created_at,
    )


@router.post("/logout", response_model=AuthLogoutResponse, summary="退出登录")
async def logout(_: AuthContext = Depends(require_auth)):
    return AuthLogoutResponse()
