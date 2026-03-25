"""用户路由：冷启动、用户信息 CRUD"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User
from backend.middleware.auth import AuthContext, ensure_user_access, require_auth
from backend.schemas.user import UserInitRequest, UserProfileResponse, UserUpdateRequest
from backend.services import memory_service

router = APIRouter()


@router.post("/init", response_model=UserProfileResponse, summary="冷启动：提交初始偏好")
async def init_user(
    body: UserInitRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    """
    新用户冷启动：
    - 若用户不存在则创建
    - 更新 cold_start_done = True
    - Phase 1: 仅落库；Phase 3: 写入 Mem0
    """
    effective_user_id = ensure_user_access(body.user_id, auth)
    result = await db.execute(select(User).where(User.id == effective_user_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=effective_user_id,
            display_name=body.display_name,
            cold_start_done=True,
        )
        db.add(user)
    else:
        user.cold_start_done = True
        if body.display_name:
            user.display_name = body.display_name

    await db.commit()
    await db.refresh(user)

    # Phase 3 冷启动：写入 user_invest_profiles + 加入 ltm_write_tasks 队列
    if body.preferences:
        await memory_service.cold_start(effective_user_id, body.preferences, db)

    return UserProfileResponse(
        user_id=user.id,
        display_name=user.display_name,
        cold_start_done=user.cold_start_done,
        created_at=user.created_at,
    )


@router.get("/profile", response_model=UserProfileResponse, summary="获取用户信息")
async def get_profile(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    effective_user_id = ensure_user_access(user_id, auth)
    result = await db.execute(select(User).where(User.id == effective_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=effective_user_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return UserProfileResponse(
        user_id=user.id,
        display_name=user.display_name,
        cold_start_done=user.cold_start_done,
        created_at=user.created_at,
    )


@router.put("/profile", response_model=UserProfileResponse, summary="更新用户基本信息")
async def update_profile(
    user_id: str,
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    effective_user_id = ensure_user_access(user_id, auth)
    result = await db.execute(select(User).where(User.id == effective_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.display_name is not None:
        user.display_name = body.display_name
    await db.commit()
    await db.refresh(user)
    return UserProfileResponse(
        user_id=user.id,
        display_name=user.display_name,
        cold_start_done=user.cold_start_done,
        created_at=user.created_at,
    )
