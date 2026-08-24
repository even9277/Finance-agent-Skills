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

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger
from src.memory.memory_service import MemoryService
from src.memory.mem0_schema import MemorySource

logger = setup_logger("backend.memory_service", log_dir=str(_AGENT_ROOT / "logs"))


# ─────────────────────────────────────────────────────────────
# 画像读取
# ─────────────────────────────────────────────────────────────

async def get_user_profile(user_id: str, db=None) -> dict[str, Any]:
    """
    获取用户画像：
    - 结构化画像（user_invest_profiles）权威来源
    - 返回格式兼容 Phase 1 API 的 UserProfile schema
    """
    profile = await MemoryService.get_structured_profile(user_id, db_session=db)

    logger.debug(f"[memory_service] get_user_profile: user={user_id}, profile={profile}")
    print(f"[memory_service] get_user_profile: user={user_id[:8]}...")

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
    # 字段名映射：前端用 risk_profile，DB 用 risk_level
    await MemoryService.update_profile_and_enqueue(
        user_id=user_id,
        field="risk_level",
        value=risk_profile,
        source=MemorySource.UI,
        db_session=db,
    )
    logger.info(f"[memory_service] update_risk_profile: user={user_id}, value={risk_profile}")
    print(f"[memory_service] 更新风险偏好: user={user_id[:8]}..., value={risk_profile}")
    return True


async def update_sectors(user_id: str, sectors: list[str], db=None) -> bool:
    """更新关注板块（SectorTagSelector 变更调用，debounce 800ms）。"""
    await MemoryService.update_profile_and_enqueue(
        user_id=user_id,
        field="sectors",
        value=sectors,
        source=MemorySource.UI,
        db_session=db,
    )
    logger.info(f"[memory_service] update_sectors: user={user_id}, sectors={sectors}")
    print(f"[memory_service] 更新关注板块: user={user_id[:8]}..., sectors={sectors}")
    return True


async def update_return_expectation(
    user_id: str,
    value: float,
    db=None,
    return_max: Optional[float] = None,
    investment_horizon: Optional[str] = None,
) -> bool:
    """更新期望收益（ReturnExpectation 变更调用，debounce 800ms）。"""
    await MemoryService.update_profile_and_enqueue(
        user_id=user_id,
        field="expected_return_min",
        value=value,
        source=MemorySource.UI,
        db_session=db,
    )
    if return_max is not None:
        await MemoryService.update_profile_and_enqueue(
            user_id=user_id,
            field="expected_return_max",
            value=return_max,
            source=MemorySource.UI,
            db_session=db,
        )
    if investment_horizon:
        await MemoryService.update_profile_and_enqueue(
            user_id=user_id,
            field="investment_horizon",
            value=investment_horizon,
            source=MemorySource.UI,
            db_session=db,
        )
    logger.info(f"[memory_service] update_return_expectation: user={user_id}, min={value}, max={return_max}")
    print(f"[memory_service] 更新期望收益: user={user_id[:8]}..., min={value}%")
    return True


async def update_response_pref(user_id: str, pref: str, db=None) -> bool:
    """更新回答偏好。"""
    await MemoryService.update_profile_and_enqueue(
        user_id=user_id,
        field="response_pref",
        value=pref,
        source=MemorySource.UI,
        db_session=db,
    )
    return True


# ─────────────────────────────────────────────────────────────
# 记忆条目 CRUD（Mem0 直接操作）
# ─────────────────────────────────────────────────────────────

async def get_memory_items(
    user_id: str,
    page: int = 1,
    size: int = 20,
    db=None,
) -> dict[str, Any]:
    """获取所有记忆条目（分页，来自 Mem0）。"""
    result = await MemoryService.get_all_memories(
        user_id, page=page, page_size=size, db_session=db
    )
    logger.debug(f"[memory_service] get_memory_items: user={user_id}, total={result.get('total')}")
    return result


async def add_memory_item(
    user_id: str,
    category: str,
    content: str,
    metadata: dict,
    db=None,
) -> dict[str, Any]:
    """手动添加记忆条目。"""
    metadata["category"] = category
    metadata.setdefault("source", MemorySource.UI.value)
    metadata.setdefault("confidence", 1.0)
    result = await MemoryService.add_memory(user_id, content, metadata)
    logger.info(f"[memory_service] add_memory_item: user={user_id}, category={category}")
    return result


async def update_memory_item(
    user_id: str,
    memory_id: str,
    content: str,
    metadata: dict,
    db=None,
) -> bool:
    """编辑记忆条目。"""
    ok = await MemoryService.update_memory(user_id, memory_id, content, metadata)
    logger.info(f"[memory_service] update_memory_item: user={user_id}, id={memory_id}")
    return ok


async def delete_memory_item(user_id: str, memory_id: str, db=None) -> bool:
    """删除记忆条目（软删除：标记 active=False）。"""
    ok = await MemoryService.delete_memory(user_id, memory_id, db_session=db)
    logger.info(f"[memory_service] delete_memory_item: user={user_id}, id={memory_id}")
    return ok


async def delete_all_memories(user_id: str, db=None) -> bool:
    """清空所有记忆（Mem0 全清 + user_invest_profiles 重置）。"""
    await MemoryService.delete_all(user_id, db_session=db)
    logger.warning(f"[memory_service] delete_all_memories: user={user_id}")
    print(f"[memory_service] 清空所有记忆: user={user_id[:8]}...")
    return True


async def get_memory_stats(user_id: str, db=None) -> dict[str, Any]:
    """获取记忆来源统计，用于 MemorySidebar 底部展示。"""
    return await MemoryService.get_memory_stats(user_id, db_session=db)


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

    await MemoryService.cold_start(user_id, tags=preferences, db_session=db)
    logger.info(f"[memory_service] cold_start: user={user_id}, prefs={list(preferences.keys())}")
    print(f"[memory_service] cold_start 完成: user={user_id[:8]}..., keys={list(preferences.keys())}")
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
        logger.warning(f"[memory_service] get_memory_evidence 失败: {exc}")
        return {"memory_id": memory_id, "evidence": [], "error": str(exc)}
