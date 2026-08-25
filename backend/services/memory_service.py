"""
后端记忆服务桥接层 - Phase 3 真实实现

职责：作为 backend routers 与 Financial-MCP-Agent/src/memory/memory_service.py 之间的桥接层。
所有路由函数通过此层调用，不直接操作 Mem0 SDK 或数据库。

设计：
- FastAPI 路由将 db_session (SQLAlchemy AsyncSession) 传入，由 MemoryService 统一处理
- 所有写操作遵循"先写 PostgreSQL 权威表，Mem0 通过 outbox 异步同步"原则
- ENABLE_MEMORY=false 时，所有 Mem0 相关操作为 no-op，结构化画像仍可正常读写
"""

import sys
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.memory.authority import AuthorityMutationResult
from backend.db.models import MemoryRecordRow, UserInvestProfile
from backend.infrastructure.memory.authority_repository import (
    SqlAlchemyAuthoritativeMemoryRepository,
)

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger  # noqa: E402
from src.memory.memory_service import MemoryService  # noqa: E402
from src.memory.mem0_schema import MemorySource as LegacyMemorySource  # noqa: E402
from src.memory.contracts import (  # noqa: E402
    MemoryRecordStatus,
    MemorySource,
    ProfileField,
)

logger = setup_logger("backend.memory_service", log_dir=str(_AGENT_ROOT / "logs"))


async def _invalidate_profile_cache(user_id: str) -> None:
    """在权威画像写路径完成后删除可丢弃紧凑画像缓存。"""
    from backend.infrastructure.memory.runtime import get_memory_cache

    cache = get_memory_cache()
    if cache is not None:
        try:
            await cache.invalidate_profile(user_id)
        except Exception as exc:
            # 权威画像写已经完成；派生缓存失败只能降级，不能改写 API 成败。
            logger.warning(
                "memory_cache_invalidate_failed stage=%s status=%s error_code=%s "
                "error_type=%s",
                "memory.cache.invalidate",
                "DEGRADED",
                "UNAVAILABLE",
                type(exc).__name__,
            )


# ─────────────────────────────────────────────────────────────
# 画像读取
# ─────────────────────────────────────────────────────────────

async def get_user_profile(user_id: str, db=None) -> dict[str, Any]:
    """
    获取用户画像：
    - 结构化画像（user_invest_profiles）权威来源
    - 返回格式兼容 Phase 1 API 的 UserProfile schema
    """
    if db is None:
        profile = await MemoryService.get_structured_profile(user_id, db_session=db)
    else:
        row = await db.scalar(
            select(UserInvestProfile).where(UserInvestProfile.user_id == user_id)
        )
        profile = {
            "risk_level": row.risk_level if row else None,
            "sectors": row.sectors if row else [],
            "expected_return_min": row.expected_return_min if row else None,
            "expected_return_max": row.expected_return_max if row else None,
            "investment_horizon": row.investment_horizon if row else None,
            "constraints": row.constraints if row else [],
            "response_pref": row.response_pref if row else "balanced",
            "updated_by": row.updated_by if row else None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        }

    logger.debug(
        "memory_profile_read stage=%s status=%s",
        "memory.profile.read",
        "SUCCEEDED",
    )

    # 兼容 Phase 1 API 字段名映射
    return {
        "risk_profile": profile.get("risk_level"),
        "sectors": profile.get("sectors") or [],
        "return_expectation": profile.get("expected_return_min"),
        "investment_horizon": profile.get("investment_horizon"),
        "watchlist": [],  # watchlist 存于 Mem0 语义层，此处返回空（WatchlistPanel 单独拉取）
        # Phase 3 扩展字段
        "risk_level": profile.get("risk_level"),
        "expected_return_min": profile.get("expected_return_min"),
        "expected_return_max": profile.get("expected_return_max"),
        "constraints": profile.get("constraints") or [],
        "response_pref": profile.get("response_pref", "balanced"),
        "updated_by": profile.get("updated_by"),
        "updated_at": profile.get("updated_at"),
    }


async def get_memory_context_for_chat(
    user_id: str,
    query: str,
    db=None,
) -> dict[str, Any]:
    """供聊天应用层调用：获取完整 memory_context（画像+语义记忆）。"""
    return await MemoryService.get_memory_context(user_id, query, db_session=db)


# ─────────────────────────────────────────────────────────────
# 画像更新（UI 显式操作 → 权威表立即更新 + Mem0 异步队列）
# ─────────────────────────────────────────────────────────────

async def update_risk_profile(user_id: str, risk_profile: str, db=None) -> bool:
    """更新风险偏好（RiskProfileCard 点击调用）。"""
    if db is None:
        await MemoryService.update_profile_and_enqueue(
            user_id=user_id,
            field="risk_level",
            value=risk_profile,
            source=LegacyMemorySource.UI,
            db_session=None,
        )
        await _invalidate_profile_cache(user_id)
        return True
    await _write_profile(
        user_id=user_id,
        field=ProfileField.RISK_LEVEL,
        value=risk_profile,
        db=_require_db(db),
    )
    await _invalidate_profile_cache(user_id)
    logger.info(
        "memory_profile_write stage=%s status=%s field=%s",
        "memory.profile.write",
        "SUCCEEDED",
        "risk_level",
    )
    return True


async def update_sectors(user_id: str, sectors: list[str], db=None) -> bool:
    """更新关注板块（SectorTagSelector 变更调用，debounce 800ms）。"""
    await _write_profile(
        user_id=user_id,
        field=ProfileField.SECTORS,
        value=tuple(sectors),
        db=_require_db(db),
    )
    await _invalidate_profile_cache(user_id)
    logger.info(
        "memory_profile_write stage=%s status=%s field=%s",
        "memory.profile.write",
        "SUCCEEDED",
        "sectors",
    )
    return True


async def update_return_expectation(
    user_id: str,
    value: float,
    db=None,
    return_max: Optional[float] = None,
    investment_horizon: Optional[str] = None,
) -> bool:
    """更新期望收益（ReturnExpectation 变更调用，debounce 800ms）。"""
    database = _require_db(db)
    await _write_profile(
        user_id=user_id,
        field=ProfileField.EXPECTED_RETURN_MIN,
        value=value,
        db=database,
        commit=False,
    )
    if return_max is not None:
        await _write_profile(
            user_id=user_id,
            field=ProfileField.EXPECTED_RETURN_MAX,
            value=return_max,
            db=database,
            commit=False,
        )
    if investment_horizon:
        await _write_profile(
            user_id=user_id,
            field=ProfileField.INVESTMENT_HORIZON,
            value=investment_horizon,
            db=database,
            commit=False,
        )
    await database.commit()
    await _invalidate_profile_cache(user_id)
    logger.info(
        "memory_profile_write stage=%s status=%s field=%s",
        "memory.profile.write",
        "SUCCEEDED",
        "return_expectation",
    )
    return True


async def update_response_pref(user_id: str, pref: str, db=None) -> bool:
    """把用户显式回答偏好写入文本权威记录，并维护旧字段投影。"""
    database = _require_db(db)
    await SqlAlchemyAuthoritativeMemoryRepository(database).add_text(
        user_id=user_id,
        category="response_preference",
        content=f"回答偏好：{pref}",
        source=MemorySource.USER_UI,
        evidence_ref="ui:response_preference",
    )
    profile = await database.scalar(
        select(UserInvestProfile).where(UserInvestProfile.user_id == user_id)
    )
    if profile is None:
        profile = UserInvestProfile(user_id=user_id, updated_by="user")
        database.add(profile)
    profile.response_pref = pref
    profile.updated_by = "user"
    await database.commit()
    await _invalidate_profile_cache(user_id)
    return True


# ─────────────────────────────────────────────────────────────
# 记忆条目 CRUD（PostgreSQL 权威记录；派生向量索引在 M6 接入）
# ─────────────────────────────────────────────────────────────

async def get_memory_items(
    user_id: str,
    page: int = 1,
    size: int = 20,
    db=None,
) -> dict[str, Any]:
    """按认证用户分页读取仍有效的 PostgreSQL 权威文本记忆。"""
    database = _require_db(db)
    statement = (
        select(MemoryRecordRow)
        .where(
            MemoryRecordRow.user_id == user_id,
            MemoryRecordRow.kind == "text",
            MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
        )
        .order_by(MemoryRecordRow.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = list((await database.execute(statement)).scalars().all())
    total = int(
        await database.scalar(
            select(func.count(MemoryRecordRow.id)).where(
                MemoryRecordRow.user_id == user_id,
                MemoryRecordRow.kind == "text",
                MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
            )
        )
        or 0
    )
    result = {
        "items": [
            {
                "id": row.id,
                "content": row.content or "",
                "category": row.category,
                "source": row.source,
                "confidence": 1.0,
                "evidence_ref": row.evidence_ref or "",
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "metadata": {
                    "status": row.status,
                    "version": row.version,
                    "activation_source": row.activation_source,
                },
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": size,
    }
    logger.debug(
        "memory_items_read stage=%s status=%s item_count=%s",
        "memory.items.read",
        "SUCCEEDED",
        result.get("total"),
    )
    return result


async def add_memory_item(
    user_id: str,
    category: str,
    content: str,
    metadata: dict,
    db=None,
) -> dict[str, Any]:
    """手动添加记忆条目。"""
    del metadata
    database = _require_db(db)
    result = await SqlAlchemyAuthoritativeMemoryRepository(database).add_text(
        user_id=user_id,
        category=category,
        content=content,
        source=MemorySource.USER_UI,
        evidence_ref="ui:memory_item",
    )
    await database.commit()
    logger.info(
        "memory_item_write stage=%s status=%s operation=%s",
        "memory.item.write",
        "SUCCEEDED",
        "add",
    )
    return {
        "id": result.record_id,
        "content": content,
        "category": category,
        "source": MemorySource.USER_UI.value,
        "confidence": 1.0,
        "evidence_ref": "ui:memory_item",
        "created_at": "",
        "metadata": {"status": result.status.value, "version": result.version},
    }


async def update_memory_item(
    user_id: str,
    memory_id: str,
    content: str,
    metadata: dict,
    db=None,
) -> AuthorityMutationResult | None:
    """编辑记忆条目。"""
    del metadata
    database = _require_db(db)
    result = await SqlAlchemyAuthoritativeMemoryRepository(database).update_text(
        user_id=user_id,
        record_id=memory_id,
        content=content,
    )
    if result is not None:
        await database.commit()
    else:
        await database.rollback()
    logger.info(
        "memory_item_write stage=%s status=%s operation=%s",
        "memory.item.write",
        "SUCCEEDED" if result else "FAILED",
        "update",
    )
    return result

async def delete_memory_item(
    user_id: str,
    memory_id: str,
    db=None,
) -> AuthorityMutationResult | None:
    """软删除当前用户拥有的权威记忆并返回可检查生命周期。"""
    database = _require_db(db)
    result = await SqlAlchemyAuthoritativeMemoryRepository(database).delete_record(
        user_id=user_id,
        record_id=memory_id,
    )
    if result is not None:
        await database.commit()
    else:
        await database.rollback()
    logger.info(
        "memory_item_write stage=%s status=%s operation=%s",
        "memory.item.write",
        "SUCCEEDED" if result else "FAILED",
        "delete",
    )
    return result

async def delete_all_memories(user_id: str, db=None) -> bool:
    """在已由路由确认后软删除该用户记录并重置兼容画像投影。"""
    if db is None:
        await MemoryService.delete_all(user_id, db_session=None)
        await _invalidate_profile_cache(user_id)
        return True
    database = _require_db(db)
    await database.execute(
        update(MemoryRecordRow)
        .where(
            MemoryRecordRow.user_id == user_id,
            MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
        )
        .values(
            status=MemoryRecordStatus.INACTIVE.value,
            deleted_at=func.now(),
            version=MemoryRecordRow.version + 1,
        )
    )
    profile = await database.scalar(
        select(UserInvestProfile).where(UserInvestProfile.user_id == user_id)
    )
    if profile is not None:
        profile.risk_level = None
        profile.investment_horizon = None
        profile.expected_return_min = None
        profile.expected_return_max = None
        profile.sectors = []
        profile.constraints = []
        profile.response_pref = "balanced"
        profile.updated_by = "user"
    await database.commit()
    await _invalidate_profile_cache(user_id)
    logger.warning(
        "memory_items_write stage=%s status=%s operation=%s",
        "memory.items.write",
        "SUCCEEDED",
        "delete_all",
    )
    return True


async def get_memory_stats(user_id: str, db=None) -> dict[str, Any]:
    """按 PostgreSQL 权威生命周期返回低基数统计。"""
    database = _require_db(db)
    total = int(
        await database.scalar(
            select(func.count(MemoryRecordRow.id)).where(
                MemoryRecordRow.user_id == user_id,
                MemoryRecordRow.status == MemoryRecordStatus.ACTIVE.value,
            )
        )
        or 0
    )
    return {"total_tasks": total, "active_records": total}


# ─────────────────────────────────────────────────────────────
# 冷启动
# ─────────────────────────────────────────────────────────────

async def cold_start(user_id: str, preferences: Optional[dict], db=None) -> bool:
    """
    冷启动：
    - 写入 user_invest_profiles（updated_by=user，source=cold_start）
    - 加入 ltm_write_tasks（Mem0 异步同步，优先级最高）
    """
    if not preferences:
        return True

    if db is None:
        await MemoryService.cold_start(user_id, tags=preferences, db_session=None)
        await _invalidate_profile_cache(user_id)
        return True

    database = _require_db(db)
    mapping = {
        "risk_profile": ProfileField.RISK_LEVEL,
        "risk_level": ProfileField.RISK_LEVEL,
        "investment_horizon": ProfileField.INVESTMENT_HORIZON,
        "return_expectation": ProfileField.EXPECTED_RETURN_MIN,
        "expected_return_min": ProfileField.EXPECTED_RETURN_MIN,
        "expected_return_max": ProfileField.EXPECTED_RETURN_MAX,
        "sectors": ProfileField.SECTORS,
        "constraints": ProfileField.CONSTRAINTS,
    }
    repository = SqlAlchemyAuthoritativeMemoryRepository(database)
    for key, raw_value in preferences.items():
        field = mapping.get(key)
        if field is None or raw_value is None:
            continue
        value = tuple(raw_value) if isinstance(raw_value, list) else raw_value
        await repository.write_profile(
            user_id=user_id,
            field=field,
            value=value,
            source=MemorySource.USER_UI,
            evidence_ref="ui:cold_start",
        )
    await database.commit()
    await _invalidate_profile_cache(user_id)
    logger.info(
        "memory_profile_write stage=%s status=%s operation=%s field_count=%s",
        "memory.profile.write",
        "SUCCEEDED",
        "cold_start",
        len(preferences),
    )
    return True


# ─────────────────────────────────────────────────────────────
# 证据溯源（Phase 3 实现）
# ─────────────────────────────────────────────────────────────

async def get_memory_evidence(user_id: str, memory_id: str, db=None) -> dict[str, Any]:
    """
    查看某条记忆来源于哪次对话（通过 evidence_ref 关联 messages.id）。
    Phase 3 初版：从 Mem0 中读取 metadata.evidence_ref，再查 DB messages 表。
    """
    try:
        from src.memory.mem0_client import get_mem0_client, is_mem0_available
        if not is_mem0_available():
            return {"memory_id": memory_id, "evidence": [], "note": "Mem0 不可用"}

        client = get_mem0_client()
        all_mems = await client.get_all(user_id=user_id)
        items = all_mems.get("results", []) if isinstance(all_mems, dict) else []

        target = next((i for i in items if i.get("id") == memory_id), None)
        if not target:
            return {"memory_id": memory_id, "evidence": [], "note": "记忆条目不存在"}

        meta = target.get("metadata", {})
        evidence_ref = meta.get("evidence_ref", "")
        source = meta.get("source", "")
        session_id = meta.get("session_id", "")
        run_id = meta.get("run_id", "")

        return {
            "memory_id": memory_id,
            "memory_text": target.get("memory", ""),
            "source": source,
            "evidence_ref": evidence_ref,
            "session_id": session_id,
            "run_id": run_id,
            "evidence": [],  # TODO: 按 evidence_ref 查 messages 表返回原文
        }
    except Exception as exc:
        logger.warning(
            "memory_evidence_read_failed stage=%s status=%s error_code=%s "
            "error_type=%s",
            "memory.evidence.read",
            "FAILED",
            "UNEXPECTED_ERROR",
            type(exc).__name__,
        )
        return {
            "memory_id": memory_id,
            "evidence": [],
            "error": "MEMORY_EVIDENCE_READ_FAILED",
        }


async def _write_profile(
    *,
    user_id: str,
    field: ProfileField,
    value: str | float | tuple[str, ...],
    db: AsyncSession,
    commit: bool = True,
) -> AuthorityMutationResult:
    """通过唯一显式权威仓储写画像，并按调用方需要提交事务。"""
    result = await SqlAlchemyAuthoritativeMemoryRepository(db).write_profile(
        user_id=user_id,
        field=field,
        value=value,
        source=MemorySource.USER_UI,
        evidence_ref=f"ui:profile:{field.value}",
    )
    if commit:
        await db.commit()
    return result


def _require_db(db: object) -> AsyncSession:
    """拒绝新权威写路径退回本地 SQLite/Provider 隐式连接。"""
    if not isinstance(db, AsyncSession):
        raise RuntimeError("authoritative memory operation requires AsyncSession")
    return db
