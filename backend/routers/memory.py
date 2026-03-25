"""
记忆/画像路由 - Phase 3 完整实现

所有接口路径与 Phase 1 保持一致，只替换底层实现（前端无需改动 API 调用代码）。
写操作遵循"先写 PostgreSQL 权威表（立即响应 200），Mem0 通过 outbox 异步同步"原则。
"""

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.middleware.auth import require_query_user
from backend.schemas.memory import (
    MemoryAddRequest,
    MemoryEvidenceResponse,
    MemoryItemsResponse,
    MemoryProfileResponse,
    MemoryUpdateHorizonRequest,
    MemoryUpdateRequest,
    MemoryUpdateResponsePrefRequest,
    MemoryUpdateReturnRequest,
    MemoryUpdateRiskRequest,
    MemoryUpdateSectorsRequest,
    UserProfile,
)
from backend.services import memory_service

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger

logger = setup_logger("memory_router", log_dir=str(_AGENT_ROOT / "logs"))

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# GET /api/memory/profile  ── 获取用户 LTM 结构化画像
# ─────────────────────────────────────────────────────────────

@router.get("/profile", response_model=MemoryProfileResponse, summary="获取用户 LTM 结构化画像")
async def get_memory_profile(
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    profile_data = await memory_service.get_user_profile(user_id, db)
    stats = await memory_service.get_memory_stats(user_id, db)
    total_memories = stats.get("total_tasks", 0)

    logger.info(f"[memory_router] GET /profile: user={user_id}")
    print(f"[memory_router] GET /profile: user={user_id[:8]}...")

    return MemoryProfileResponse(
        user_id=user_id,
        profile=UserProfile(**profile_data),
        total_memories=total_memories,
        stats=stats,
        note="Phase 3: 来自 PostgreSQL user_invest_profiles",
    )


# ─────────────────────────────────────────────────────────────
# PUT /api/memory/profile/risk  ── 更新风险偏好（RiskProfileCard）
# ─────────────────────────────────────────────────────────────

@router.put("/profile/risk", summary="更新风险偏好（RiskProfileCard 调用）")
async def update_risk(
    user_id: str = Depends(require_query_user),
    body: MemoryUpdateRiskRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    await memory_service.update_risk_profile(user_id, body.risk_profile, db)
    logger.info(f"[memory_router] PUT /profile/risk: user={user_id}, value={body.risk_profile}")
    print(f"[memory_router] 更新风险偏好: user={user_id[:8]}..., value={body.risk_profile}")
    return {"message": "已更新", "field": "risk_level", "value": body.risk_profile}


# ─────────────────────────────────────────────────────────────
# PUT /api/memory/profile/sectors  ── 更新关注板块（SectorTagSelector，debounce 800ms）
# ─────────────────────────────────────────────────────────────

@router.put("/profile/sectors", summary="更新关注板块（SectorTagSelector 调用）")
async def update_sectors(
    user_id: str = Depends(require_query_user),
    body: MemoryUpdateSectorsRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    await memory_service.update_sectors(user_id, body.sectors, db)
    logger.info(f"[memory_router] PUT /profile/sectors: user={user_id}, sectors={body.sectors}")
    print(f"[memory_router] 更新关注板块: user={user_id[:8]}..., sectors={body.sectors}")
    return {"message": "已更新", "field": "sectors", "value": body.sectors}


# ─────────────────────────────────────────────────────────────
# PUT /api/memory/profile/return  ── 更新期望收益（ReturnExpectation，debounce 800ms）
# ─────────────────────────────────────────────────────────────

@router.put("/profile/return", summary="更新期望收益（ReturnExpectation 调用）")
async def update_return(
    user_id: str = Depends(require_query_user),
    body: MemoryUpdateReturnRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    await memory_service.update_return_expectation(
        user_id,
        body.return_expectation,
        db,
        return_max=body.return_max,
        investment_horizon=body.investment_horizon,
    )
    logger.info(
        f"[memory_router] PUT /profile/return: user={user_id}, "
        f"min={body.return_expectation}, max={body.return_max}"
    )
    print(f"[memory_router] 更新期望收益: user={user_id[:8]}..., min={body.return_expectation}%")
    return {
        "message": "已更新",
        "expected_return_min": body.return_expectation,
        "expected_return_max": body.return_max,
    }


# ─────────────────────────────────────────────────────────────
# PUT /api/memory/profile/horizon  ── 更新投资周期（新增端点）
# ─────────────────────────────────────────────────────────────

@router.put("/profile/horizon", summary="更新投资周期")
async def update_horizon(
    user_id: str = Depends(require_query_user),
    body: MemoryUpdateHorizonRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    await memory_service.update_return_expectation(
        user_id, 0, db,
        investment_horizon=body.investment_horizon,
    )
    logger.info(f"[memory_router] PUT /profile/horizon: user={user_id}, value={body.investment_horizon}")
    return {"message": "已更新", "field": "investment_horizon", "value": body.investment_horizon}


# ─────────────────────────────────────────────────────────────
# PUT /api/memory/profile/pref  ── 更新回答偏好（新增端点）
# ─────────────────────────────────────────────────────────────

@router.put("/profile/pref", summary="更新回答偏好")
async def update_pref(
    user_id: str = Depends(require_query_user),
    body: MemoryUpdateResponsePrefRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    await memory_service.update_response_pref(user_id, body.response_pref, db)
    logger.info(f"[memory_router] PUT /profile/pref: user={user_id}, value={body.response_pref}")
    return {"message": "已更新", "field": "response_pref", "value": body.response_pref}


# ─────────────────────────────────────────────────────────────
# GET /api/memory/items  ── 获取所有记忆条目（分页，来自 Mem0）
# ─────────────────────────────────────────────────────────────

@router.get("/items", response_model=MemoryItemsResponse, summary="获取所有记忆条目（分页）")
async def get_memory_items(
    user_id: str = Depends(require_query_user),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    data = await memory_service.get_memory_items(user_id, page, size, db)
    logger.debug(f"[memory_router] GET /items: user={user_id}, total={data.get('total')}")
    return MemoryItemsResponse(**data)


# ─────────────────────────────────────────────────────────────
# POST /api/memory/items  ── 手动添加记忆
# ─────────────────────────────────────────────────────────────

@router.post("/items", summary="手动添加记忆条目")
async def add_memory_item(
    user_id: str = Depends(require_query_user),
    body: MemoryAddRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    item = await memory_service.add_memory_item(
        user_id, body.category, body.content, body.metadata, db
    )
    logger.info(f"[memory_router] POST /items: user={user_id}, category={body.category}")
    return item


# ─────────────────────────────────────────────────────────────
# PUT /api/memory/items/{memory_id}  ── 编辑记忆条目
# ─────────────────────────────────────────────────────────────

@router.put("/items/{memory_id}", summary="编辑记忆条目")
async def update_memory_item(
    memory_id: str,
    user_id: str = Depends(require_query_user),
    body: MemoryUpdateRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    ok = await memory_service.update_memory_item(
        user_id, memory_id, body.content, body.metadata, db
    )
    if not ok:
        raise HTTPException(status_code=404, detail="记忆条目不存在或 Mem0 不可用")
    logger.info(f"[memory_router] PUT /items/{memory_id}: user={user_id}")
    return {"message": "已更新"}


# ─────────────────────────────────────────────────────────────
# DELETE /api/memory/items/{memory_id}  ── 删除记忆条目
# ─────────────────────────────────────────────────────────────

@router.delete("/items/{memory_id}", summary="删除记忆条目")
async def delete_memory_item(
    memory_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await memory_service.delete_memory_item(user_id, memory_id, db)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    logger.info(f"[memory_router] DELETE /items/{memory_id}: user={user_id}")
    return {"message": "已删除"}


# ─────────────────────────────────────────────────────────────
# DELETE /api/memory/all  ── 清空所有记忆（GDPR 合规，二次确认）
# ─────────────────────────────────────────────────────────────

@router.delete("/all", summary="清空所有记忆（二次确认后调用）")
async def delete_all_memories(
    user_id: str = Depends(require_query_user),
    confirm: bool = Query(False, description="必须传 true 才执行"),
    db: AsyncSession = Depends(get_db),
):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="请传入 confirm=true 以确认删除所有记忆（此操作不可撤销）",
        )
    await memory_service.delete_all_memories(user_id, db)
    logger.warning(f"[memory_router] DELETE /all: user={user_id}")
    print(f"[memory_router] 清空所有记忆: user={user_id[:8]}...")
    return {"message": "已清空所有记忆（Mem0 + user_invest_profiles 均已重置）"}


# ─────────────────────────────────────────────────────────────
# GET /api/memory/items/{memory_id}/evidence  ── 查看记忆来源对话
# ─────────────────────────────────────────────────────────────

@router.get(
    "/items/{memory_id}/evidence",
    response_model=MemoryEvidenceResponse,
    summary="查看记忆来源于哪条对话",
)
async def get_memory_evidence(
    memory_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    result = await memory_service.get_memory_evidence(user_id, memory_id, db)
    logger.debug(f"[memory_router] GET /items/{memory_id}/evidence: user={user_id}")
    return MemoryEvidenceResponse(**result)
