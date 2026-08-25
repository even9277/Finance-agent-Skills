"""
MemoryService - 统一 LTM 服务接口层（Phase 3）

架构：双轨制
  - 结构化主数据（user_invest_profiles）：直接读写 PostgreSQL/SQLite，网络延迟可控
  - 语义增强层（Mem0 + pgvector）：通过 ltm_write_tasks outbox 异步写入

所有上层代码（memory_nodes.py、chat_service.py、routers）
必须经过此层，禁止直接调 Mem0 SDK。

降级原则：
  - get_structured_profile 直接查 DB，不依赖 Mem0，永远可用
  - search_semantic 依赖 Mem0，不可用时静默返回 []
  - get_memory_context 合并两者，Mem0 不可用时仅返回结构化画像

注意：此模块运行在 Financial-MCP-Agent 的 Python 进程中，
      通过 backend 的 DB session 读写数据库。
      在 LangGraph 节点中调用时，需传入 db 路径；
      在 backend 服务中调用时，由 FastAPI 依赖注入提供 session。
"""

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 确保路径正确（被 backend 调用时路径不同）
_MEMORY_DIR = Path(__file__).resolve().parent
_AGENT_SRC = _MEMORY_DIR.parent
if str(_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENT_SRC))

from src.memory.mem0_schema import MemorySource  # noqa: E402
from src.utils.logging_config import setup_logger  # noqa: E402

logger = setup_logger("memory_service")


@dataclass(frozen=True)
class ProfileMutationDecision:
    """表示画像写入是否被候选治理边界接受。"""

    requires_confirmation: bool
    applied: bool

# Mem0 get_all 单次拉取上限（分页在应用层切片；过小会导致前端「加载更多」缺页）
_MEM0_GET_ALL_LIMIT = int(os.getenv("MEM0_GET_ALL_LIMIT", "500"))


def _normalize_memory_timestamp(val: Any) -> str:
    """将 Mem0 / DB 返回的时间统一为 ISO 字符串，供前端展示。"""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        try:
            return val.isoformat()
        except Exception:
            return str(val)
    return str(val).strip()


def _coerce_confidence(val: Any) -> float:
    try:
        if val is None:
            return 1.0
        return float(val)
    except (TypeError, ValueError):
        return 1.0

# ─────────────────────────────────────────────────────────────
# SQLite/PostgreSQL 直连工具（供 LangGraph 节点调用，非 FastAPI 路径）
# ─────────────────────────────────────────────────────────────

def _get_db_path() -> str:
    """获取 SQLite 数据库路径（仅 SQLite 模式使用）。"""
    return os.getenv(
        "SQLITE_DB_PATH",
        str(_AGENT_SRC.parent.parent / "backend" / "finance.db")
    )


async def _db_fetchone(sql: str, params: tuple = ()) -> Optional[dict]:
    """异步执行单行查询（兼容 aiosqlite）。"""
    try:
        import aiosqlite
        db_path = _get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    except ImportError:
        # aiosqlite 未安装时 fallback 同步 sqlite3
        import sqlite3
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        logger.error(f"[MemoryService] DB fetchone 失败: {exc}", exc_info=True)
        return None


async def _db_execute(sql: str, params: tuple = ()) -> bool:
    """异步执行写操作（INSERT/UPDATE/DELETE）。"""
    try:
        import aiosqlite
        db_path = _get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await db.execute(sql, params)
            await db.commit()
        return True
    except ImportError:
        import sqlite3
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        logger.error(f"[MemoryService] DB execute 失败: {exc}", exc_info=True)
        return False


async def _db_fetchall(sql: str, params: tuple = ()) -> list[dict]:
    """异步执行多行查询。"""
    try:
        import aiosqlite
        db_path = _get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
    except ImportError:
        import sqlite3
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error(f"[MemoryService] DB fetchall 失败: {exc}", exc_info=True)
        return []


# ─────────────────────────────────────────────────────────────
# MemoryService 主类
# ─────────────────────────────────────────────────────────────

class MemoryService:
    """
    LTM 统一服务接口。

    两种调用模式：
    1. FastAPI 模式（backend 路由/服务）：通过 SQLAlchemy AsyncSession 操作 DB
    2. LangGraph 节点模式：通过 aiosqlite 直连 SQLite

    为保持接口统一，所有方法接受可选的 db_session 参数；
    传入时使用 SQLAlchemy（FastAPI 模式），不传入时使用直连模式。
    """

    # ── 读取接口 ─────────────────────────────────────────────

    @staticmethod
    async def get_structured_profile(user_id: str, db_session=None) -> dict:
        """
        从 user_invest_profiles 读取结构化投资画像（权威主数据）。
        这是报告/对话注入的"确定性"主干，网络延迟可控，永远不依赖 Mem0。
        """
        if db_session is not None:
            # FastAPI SQLAlchemy 模式
            from sqlalchemy import text
            try:
                result = await db_session.execute(
                    text(
                        "SELECT risk_level, investment_horizon, expected_return_min, "
                        "expected_return_max, sectors, constraints, response_pref, "
                        "updated_by, updated_at "
                        "FROM user_invest_profiles WHERE user_id = :uid"
                    ),
                    {"uid": user_id},
                )
                row = result.fetchone()
                if row:
                    return _row_to_profile_dict(dict(row._mapping))
            except Exception as exc:
                logger.warning(f"[MemoryService] get_structured_profile SQLAlchemy 失败: {exc}")
            return _empty_profile()

        # 直连模式（LangGraph 节点调用）
        row = await _db_fetchone(
            "SELECT risk_level, investment_horizon, expected_return_min, "
            "expected_return_max, sectors, constraints, response_pref, "
            "updated_by, updated_at "
            "FROM user_invest_profiles WHERE user_id = ?",
            (user_id,),
        )
        if row:
            return _row_to_profile_dict(row)
        return _empty_profile()

    @staticmethod
    async def search_semantic(
        user_id: str,
        query: str,
        categories: Optional[list[str]] = None,
        sources: Optional[list[str]] = None,
        top_k: int = 5,
        threshold: float = 0.60,
    ) -> list[dict]:
        """
        Mem0 语义搜索（补充增强层）。
        Mem0 不可用时静默返回 []，不影响调用方。
        """
        try:
            from src.memory.mem0_client import get_mem0_client, is_mem0_available
            if not is_mem0_available():
                return []

            client = get_mem0_client()
            raw_results = await client.search(
                query=query,
                user_id=user_id,
                limit=top_k,
            )

            results = []
            for item in (raw_results or []):
                if isinstance(item, str):
                    item = {"memory": item, "score": 1.0, "metadata": {}}
                if not isinstance(item, dict):
                    logger.warning(
                        "[MemoryService] search_semantic 跳过非 dict 结果: type=%s",
                        type(item).__name__,
                    )
                    continue
                score = item.get("score", 1.0)
                if score < threshold:
                    continue
                meta = item.get("metadata", {})

                # categories/sources 侧过滤
                if categories and meta.get("category") not in categories:
                    continue
                if sources and meta.get("source") not in sources:
                    continue
                if not meta.get("active", True):
                    continue

                results.append({
                    "id": item.get("id", ""),
                    "text": item.get("memory", ""),
                    "score": score,
                    "metadata": meta,
                })

            logger.debug(
                f"[MemoryService] search_semantic: user={user_id}, "
                f"query={query[:30]}, hits={len(results)}"
            )
            return results

        except Exception as exc:
            logger.warning(f"[MemoryService] search_semantic 失败（降级空结果）: {exc}")
            return []

    @staticmethod
    async def get_memory_context(
        user_id: str,
        query: str,
        db_session=None,
    ) -> dict:
        """
        合并结构化画像 + Mem0 语义召回，返回统一的 memory_context 字典。

        memory_read_node 和 chat_service 统一调用此方法。
        Mem0 不可用时，semantic_memories=[]，结构化画像正常返回，主流程不受影响。
        """
        if not user_id:
            return {"profile": _empty_profile(), "semantic_memories": []}

        # 并发读取：结构化画像（主数据） + 语义召回（补充）
        profile_task = asyncio.ensure_future(
            MemoryService.get_structured_profile(user_id, db_session)
        )
        semantic_task = asyncio.ensure_future(
            MemoryService.search_semantic(
                user_id=user_id,
                query=query,
                categories=[
                    "risk_profile", "horizon", "sector_focus",
                    "watchlist_stock", "constraints", "response_preference",
                ],
                sources=["ui", "cold_start", "explicit_correction", "chat_inferred"],
                top_k=6,
                threshold=0.60,
            )
        )

        profile, semantic_memories = await asyncio.gather(
            profile_task, semantic_task, return_exceptions=True
        )

        if isinstance(profile, BaseException):
            logger.warning(f"[MemoryService] get_structured_profile 异常: {profile}")
            profile = _empty_profile()
        if isinstance(semantic_memories, BaseException):
            logger.warning(f"[MemoryService] search_semantic 异常: {semantic_memories}")
            semantic_memories = []

        logger.info(
            f"[MemoryService] get_memory_context: user={user_id}, "
            f"profile_fields={sum(1 for v in profile.values() if v)}, "
            f"semantic_hits={len(semantic_memories)}"
        )
        return {"profile": profile, "semantic_memories": semantic_memories}

    # ── 写入接口（enqueue 模式，不阻塞主链路）────────────────

    @staticmethod
    async def enqueue_add_conversation(
        user_id: str,
        messages: list[dict],
        metadata: dict,
        db_session=None,
    ) -> None:
        """
        将对话推断任务加入 ltm_write_tasks outbox 队列。
        立即返回，由 ltm_worker 后台异步执行实际 Mem0 写入。
        """
        payload = json.dumps(
            {"messages": messages, "metadata": metadata}, ensure_ascii=False
        )
        await _enqueue_task(
            user_id=user_id,
            task_type="add_conversation",
            payload=payload,
            db_session=db_session,
        )
        logger.debug(
            f"[MemoryService] enqueue_add_conversation: user={user_id}, "
            f"msgs={len(messages)}, source={metadata.get('source')}"
        )

    # 允许直写的画像字段白名单（防止 f-string SQL 注入）
    _ALLOWED_PROFILE_FIELDS = frozenset({
        "risk_level", "investment_horizon", "expected_return_min",
        "expected_return_max", "sectors", "constraints", "response_pref",
    })

    @staticmethod
    async def update_profile_field(
        user_id: str,
        field: str,
        value: Any,
        source: str = "chat_inferred",
        db_session=None,
    ) -> "ProfileMutationDecision":
        """
        显式来源可继续写兼容画像；模型推断只返回待确认决定。

        旧版本曾允许 ``chat_inferred`` 直接改写高影响画像。M5 将该入口
        收紧为 fail-closed，候选必须由统一 REM Worker 携带用户证据创建。
        """
        if field not in MemoryService._ALLOWED_PROFILE_FIELDS:
            return ProfileMutationDecision(requires_confirmation=False, applied=False)
        if source in {"chat_inferred", "report_inferred", "model_inferred"}:
            logger.info(
                "memory_profile_inference_blocked stage=%s status=%s field=%s",
                "memory.candidate.govern",
                "CONFIRMATION_REQUIRED",
                field,
            )
            return ProfileMutationDecision(requires_confirmation=True, applied=False)
        await _upsert_profile_field(user_id, field, value, source, db_session)
        logger.info(
            f"[MemoryService] update_profile_field: user={user_id}, "
            f"field={field}, source={source}"
        )
        return ProfileMutationDecision(requires_confirmation=False, applied=True)

    @staticmethod
    async def update_profile_and_enqueue(
        user_id: str,
        field: str,
        value: Any,
        source: MemorySource,
        db_session=None,
    ) -> None:
        """
        显式更新通道（UI/冷启动/主动纠正）：
        1. 立即写入 user_invest_profiles（权威表，立即生效）
        2. 加入 ltm_write_tasks（Mem0 异步同步）
        """
        await _upsert_profile_field(user_id, field, value, source.value, db_session)
        payload = json.dumps(
            {"field": field, "value": value, "source": source.value},
            ensure_ascii=False,
        )
        await _enqueue_task(
            user_id=user_id,
            task_type="explicit_update",
            payload=payload,
            db_session=db_session,
        )
        logger.info(
            "memory_profile_enqueue stage=%s status=%s field=%s source=%s",
            "memory.profile.enqueue",
            "SUCCEEDED",
            field,
            source.value,
        )

    @staticmethod
    async def enqueue_explicit_delete(
        user_id: str, memory_id: str, db_session=None
    ) -> None:
        payload = json.dumps({"memory_id": memory_id}, ensure_ascii=False)
        await _enqueue_task(
            user_id=user_id,
            task_type="explicit_delete",
            payload=payload,
            db_session=db_session,
        )
        logger.info(
            "memory_delete_enqueue stage=%s status=%s",
            "memory.delete.enqueue",
            "SUCCEEDED",
        )

    @staticmethod
    async def cold_start(
        user_id: str,
        tags: dict,
        db_session=None,
    ) -> None:
        """
        冷启动写入：
        1. UPSERT user_invest_profiles（批量设置，updated_by=user）
        2. 加入 ltm_write_tasks（source=cold_start，最高优先级）
        """
        # 将 Phase 1 的字段名映射到 Phase 3 结构化字段
        # preferences keys: risk_profile / sectors / return_expectation / investment_horizon / watchlist ...
        tags = dict(tags or {})
        if "risk_profile" in tags and "risk_level" not in tags:
            tags["risk_level"] = tags["risk_profile"]
        if "return_expectation" in tags and "expected_return_min" not in tags:
            tags["expected_return_min"] = tags["return_expectation"]

        # 构建 UPSERT 更新字段
        allowed_fields = {
            "risk_level", "investment_horizon",
            "expected_return_min", "expected_return_max",
            "sectors", "constraints", "response_pref",
        }
        clean_tags = {k: v for k, v in (tags or {}).items() if k in allowed_fields and v is not None}

        # 处理 watchlist：存入 sectors 扩展字段或单独 watchlist 字段（按计划无此字段，跳过）
        # watchlist 存入 ltm_write_tasks payload 供 Mem0 异步处理
        watchlist = tags.get("watchlist", []) if tags else []

        for field, value in clean_tags.items():
            await _upsert_profile_field(user_id, field, value, "user", db_session)

        # 将 cold_start 完整数据加入队列，供 ltm_worker 写入 Mem0
        payload = json.dumps(
            {
                "tags": clean_tags,
                "watchlist": watchlist,
                "metadata": {
                    "source": MemorySource.COLD_START.value,
                    "confidence": 1.0,
                    "updated_by": "user",
                    "active": True,
                },
            },
            ensure_ascii=False,
        )
        await _enqueue_task(
            user_id=user_id,
            task_type="cold_start",
            payload=payload,
            db_session=db_session,
        )
        logger.info(
            "memory_cold_start stage=%s status=%s field_count=%s watchlist_count=%s",
            "memory.cold_start",
            "SUCCEEDED",
            len(clean_tags),
            len(watchlist),
        )

    # ── 直接操作接口（/api/memory/items 端点调用）────────────

    @staticmethod
    async def get_all_memories(
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        db_session=None,
    ) -> dict:
        """
        获取记忆条目列表。

        优先从 Mem0 读取；若 Mem0 不可用（当前环境未安装 mem0ai 或未配置 pgvector），
        则回退到 PostgreSQL 的 ltm_write_tasks 表，按历史写入行为生成「伪记忆条目」，
        让前端能看到大致的画像变更轨迹（满足 Phase 3 的优雅降级要求）。
        """
        try:
            from src.memory.mem0_client import get_mem0_client, is_mem0_available

            # ── 分支 1：Mem0 可用，直接调用向量库 ─────────────────────
            if is_mem0_available():
                client = get_mem0_client()
                result = await client.get_all(user_id=user_id, limit=_MEM0_GET_ALL_LIMIT)
                items = result.get("results", []) if isinstance(result, dict) else (result or [])

                active_items = [
                    i for i in items
                    if (i.get("metadata") or {}).get("active", True)
                ]

                # 按创建时间倒序，保证前端列表与「最新写入」一致
                def _item_ts(it: dict) -> str:
                    return _normalize_memory_timestamp(
                        it.get("created_at")
                        or (it.get("metadata") or {}).get("created_at")
                        or it.get("updated_at")
                        or (it.get("metadata") or {}).get("updated_at")
                        or ""
                    )

                active_items.sort(key=_item_ts, reverse=True)

                # 若 Mem0 返回为空，但 outbox/画像更新已发生，则回退到 ltm_write_tasks，
                # 避免前端出现“明明入队成功但 Memory Items 永远空白”的误解。
                if not active_items:
                    logger.debug("[MemoryService] Mem0 get_all 为空，回退到 ltm_write_tasks 展示任务轨迹")
                else:
                    total = len(active_items)
                    start = (page - 1) * page_size
                    paged = active_items[start: start + page_size]

                    formatted = []
                    for item in paged:
                        meta = item.get("metadata") or {}
                        # Mem0 v1.1+ 将 created_at / updated_at 放在条目顶层，不在 metadata 内
                        created_raw = (
                            item.get("created_at")
                            or meta.get("created_at")
                            or item.get("updated_at")
                            or meta.get("updated_at")
                        )
                        created_at = _normalize_memory_timestamp(created_raw)

                        mem_text = item.get("memory") or ""
                        raw_id = item.get("id") or item.get("hash")
                        if not raw_id and mem_text:
                            raw_id = "h-" + hashlib.md5(
                                mem_text.encode("utf-8", errors="ignore")
                            ).hexdigest()[:20]
                        mem_id = str(raw_id) if raw_id is not None else ""

                        formatted.append({
                            "id": mem_id,
                            "content": mem_text,
                            "category": str(meta.get("category", "") or ""),
                            "source": str(meta.get("source", "") or ""),
                            "confidence": _coerce_confidence(meta.get("confidence", 1.0)),
                            "evidence_ref": str(meta.get("evidence_ref", "") or ""),
                            "created_at": created_at,
                            "metadata": meta,
                        })

                    return {"items": formatted, "total": total, "page": page, "page_size": page_size}

            # ── 分支 2：Mem0 不可用，回退到 ltm_write_tasks 生成伪记忆 ────
            logger.debug("[MemoryService] Mem0 不可用，get_all_memories 回退到 ltm_write_tasks")

            # 优先使用 SQLAlchemy（PostgreSQL），无 db_session 时退回 SQLite
            rows: list[dict]
            if db_session is not None:
                from sqlalchemy import text
                result = await db_session.execute(
                    text(
                        "SELECT id, task_type, payload, created_at "
                        "FROM ltm_write_tasks "
                        "WHERE user_id = :uid "
                        "ORDER BY created_at DESC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    {
                        "uid": user_id,
                        "limit": page_size,
                        "offset": (page - 1) * page_size,
                    },
                )
                rows = [
                    {
                        "id": r.id,
                        "task_type": r.task_type,
                        "payload": r.payload,
                        "created_at": getattr(r, "created_at", None),
                    }
                    for r in result.fetchall()
                ]

                # 计算总数
                count_result = await db_session.execute(
                    text("SELECT COUNT(*) FROM ltm_write_tasks WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                total = int(count_result.scalar() or 0)
            else:
                # 开发环境：本地 SQLite
                rows = await _db_fetchall(
                    "SELECT id, task_type, payload, created_at "
                    "FROM ltm_write_tasks WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (user_id, page_size, (page - 1) * page_size),
                )
                count_rows = await _db_fetchall(
                    "SELECT COUNT(*) as cnt FROM ltm_write_tasks WHERE user_id = ?",
                    (user_id,),
                )
                total = int(count_rows[0]["cnt"]) if count_rows else 0

            items: list[dict] = []
            for r in rows:
                try:
                    payload = json.loads(r["payload"])
                except Exception:
                    payload = {}

                task_type = r.get("task_type", "")
                created_at_raw = r.get("created_at")

                # 根据 task_type + payload 构造可读内容
                if task_type == "cold_start":
                    tags = payload.get("tags", {})
                    content = f"冷启动画像设定：{tags}"
                    source = "cold_start"
                    category = "cold_start"
                elif task_type == "explicit_update":
                    field = payload.get("field", "")
                    value = payload.get("value")
                    content = f"显式更新画像字段 {field} 为 {value}"
                    source = payload.get("source", "ui")
                    category = field
                elif task_type == "add_conversation":
                    source = payload.get("metadata", {}).get("source", "chat_inferred")
                    content = "对话中抽取的偏好线索（Mem0 未启用，当前仅记录为任务）"
                    category = "chat_inferred"
                else:
                    source = task_type
                    content = f"LTM 任务 {task_type}"
                    category = task_type

                items.append(
                    {
                        "id": str(r.get("id")),
                        "content": content,
                        "category": category,
                        "source": source,
                        "confidence": 1.0,
                        "evidence_ref": "",
                        "created_at": _normalize_memory_timestamp(created_at_raw),
                        "metadata": {
                            "ltm_task_id": str(r.get("id")),
                            "task_type": task_type,
                        },
                    }
                )

            return {"items": items, "total": total, "page": page, "page_size": page_size}

        except Exception as exc:
            logger.warning(f"[MemoryService] get_all_memories 失败: {exc}")
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @staticmethod
    async def add_memory(user_id: str, content: str, metadata: dict) -> dict:
        """手动添加记忆条目（立即写 Mem0，同时加 enqueue 记录）。"""
        try:
            from src.memory.mem0_client import get_mem0_client, is_mem0_available
            if not is_mem0_available():
                return {"id": "noop", "content": content, "note": "Mem0 不可用"}

            client = get_mem0_client()
            metadata.setdefault("active", True)
            metadata.setdefault("updated_by", "user")

            result = await client.add(
                messages=[{"role": "user", "content": content}],
                user_id=user_id,
                metadata=metadata,
            )
            memory_id = ""
            if isinstance(result, dict):
                results_list = result.get("results", [])
                if results_list:
                    memory_id = results_list[0].get("id", "")

            logger.info(
                "memory_item_write stage=%s status=%s operation=%s",
                "memory.item.write",
                "SUCCEEDED",
                "add",
            )
            return {"id": memory_id, "content": content, "metadata": metadata}

        except Exception as exc:
            logger.error(
                "memory_item_write_failed stage=%s status=%s operation=%s "
                "error_type=%s",
                "memory.item.write",
                "FAILED",
                "add",
                type(exc).__name__,
                exc_info=True,
            )
            return {"id": "", "content": content, "error": str(exc)}

    @staticmethod
    async def update_memory(user_id: str, memory_id: str, content: str, metadata: dict) -> bool:
        """更新 Mem0 中的记忆条目。"""
        try:
            from src.memory.mem0_client import get_mem0_client, is_mem0_available
            if not is_mem0_available():
                return False
            client = get_mem0_client()
            await client.update(memory_id, content, metadata=metadata)
            logger.info(
                "memory_item_write stage=%s status=%s operation=%s",
                "memory.item.write",
                "SUCCEEDED",
                "update",
            )
            return True
        except Exception as exc:
            logger.warning(
                "memory_item_write_failed stage=%s status=%s operation=%s "
                "error_type=%s",
                "memory.item.write",
                "FAILED",
                "update",
                type(exc).__name__,
            )
            return False

    @staticmethod
    async def delete_memory(user_id: str, memory_id: str, db_session=None) -> bool:
        """软删除：标记 active=False + 加入 ltm_write_tasks 异步删除。"""
        await MemoryService.enqueue_explicit_delete(user_id, memory_id, db_session)
        return True

    @staticmethod
    async def delete_all(user_id: str, db_session=None) -> None:
        """
        清空所有记忆：
        1. 直接调 Mem0 delete_all（立即执行）
        2. 重置 user_invest_profiles 为 NULL 默认值
        """
        try:
            from src.memory.mem0_client import get_mem0_client, is_mem0_available
            if is_mem0_available():
                client = get_mem0_client()
                await client.delete_all(user_id=user_id)
                logger.info(
                    "memory_items_write stage=%s status=%s operation=%s target=%s",
                    "memory.items.write",
                    "SUCCEEDED",
                    "delete_all",
                    "mem0",
                )
        except Exception as exc:
            logger.warning(
                "memory_items_write_failed stage=%s status=%s operation=%s "
                "target=%s error_type=%s",
                "memory.items.write",
                "DEGRADED",
                "delete_all",
                "mem0",
                type(exc).__name__,
            )

        # 重置 user_invest_profiles
        await _reset_profile(user_id, db_session)
        logger.info(
            "memory_items_write stage=%s status=%s operation=%s target=%s",
            "memory.items.write",
            "SUCCEEDED",
            "delete_all",
            "authoritative_profile",
        )

    @staticmethod
    async def get_memory_stats(user_id: str, db_session=None) -> dict:
        """
        统计各来源记忆数量，用于 MemorySidebar 底部\"来自 X 次对话 + Y 次手动\"展示。

        优先使用 SQLAlchemy（与后端主库保持一致），仅在无 db_session 时才退回到
        本地 SQLite 直连（开发环境单进程调试用）。
        """
        try:
            if db_session is not None:
                from sqlalchemy import text

                result = await db_session.execute(
                    text(
                        "SELECT task_type, COUNT(*) as cnt FROM ltm_write_tasks "
                        "WHERE user_id = :uid AND status = 'done' GROUP BY task_type"
                    ),
                    {"uid": user_id},
                )
                rows = [
                    {"task_type": r[0], "cnt": r[1]}
                    for r in result.fetchall()
                ]
            else:
                rows = await _db_fetchall(
                    "SELECT task_type, COUNT(*) as cnt FROM ltm_write_tasks "
                    "WHERE user_id = ? AND status = 'done' GROUP BY task_type",
                    (user_id,),
                )

            stats = {r["task_type"]: r["cnt"] for r in rows}
            return {
                "from_conversations": stats.get("add_conversation", 0),
                "from_reports": stats.get("explicit_update", 0),  # report_inferred
                "from_manual": stats.get("cold_start", 0) + stats.get("explicit_update", 0),
                "total_tasks": sum(stats.values()),
            }
        except Exception as exc:
            logger.debug(f"[MemoryService] get_memory_stats 失败: {exc}")
            return {"from_conversations": 0, "from_reports": 0, "from_manual": 0, "total_tasks": 0}


# ─────────────────────────────────────────────────────────────
# 私有辅助函数
# ─────────────────────────────────────────────────────────────

def _empty_profile() -> dict:
    return {
        "risk_level": None,
        "investment_horizon": None,
        "expected_return_min": None,
        "expected_return_max": None,
        "sectors": [],
        "constraints": [],
        "response_pref": "balanced",
        "updated_by": None,
        "updated_at": None,
    }


def _row_to_profile_dict(row: dict) -> dict:
    """将 DB 行转换为标准 profile 字典（处理 JSON 字段）。"""
    profile = _empty_profile()
    for k, v in row.items():
        if v is None:
            continue
        if k in ("sectors", "constraints"):
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    v = []
            profile[k] = v if isinstance(v, list) else []
        elif k == "updated_at" and hasattr(v, "isoformat"):
            profile[k] = v.isoformat()
        else:
            profile[k] = v
    return profile


async def _upsert_profile_field(
    user_id: str,
    field: str,
    value: Any,
    updated_by: str,
    db_session=None,
) -> None:
    """UPSERT user_invest_profiles 单个字段。"""
    # 处理 JSON 类型字段
    is_json_field = field in ("sectors", "constraints")
    if is_json_field:
        # PostgreSQL JSON/JSONB 列：用 JSON 字符串 + 显式 CAST，避免被当成纯文本
        value_db = json.dumps(value if isinstance(value, (list, dict)) else [], ensure_ascii=False)
    else:
        value_db = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value

    # 注意：SQLAlchemy + PostgreSQL 需要真正的 datetime 对象，
    # SQLite 直连分支仍然使用 ISO 字符串。
    now_dt = datetime.utcnow()
    now_str = now_dt.isoformat()

    if db_session is not None:
        from sqlalchemy import text
        try:
            # 先确认行存在
            result = await db_session.execute(
                text("SELECT id FROM user_invest_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            exists = result.fetchone() is not None

            if exists:
                await db_session.execute(
                    text(
                        (
                            f"UPDATE user_invest_profiles SET {field} = "
                            + ("CAST(:val AS JSONB)" if is_json_field else ":val")
                            + ", updated_by = :upd, updated_at = :now WHERE user_id = :uid"
                        )
                    ),
                    {"val": value_db, "upd": updated_by, "now": now_dt, "uid": user_id},
                )
            else:
                import uuid as _uuid
                await db_session.execute(
                    text(
                        # 首次插入时，确保 response_pref 有默认值 'balanced'，避免 NOT NULL 约束报错
                        (
                            f"INSERT INTO user_invest_profiles (id, user_id, {field}, updated_by, updated_at, created_at, response_pref) "
                            + "VALUES (:id, :uid, "
                            + ("CAST(:val AS JSONB)" if is_json_field else ":val")
                            + ", :upd, :now, :now, :resp)"
                        )
                    ),
                    {
                        "id": str(_uuid.uuid4()),
                        "uid": user_id,
                        "val": value_db,
                        "upd": updated_by,
                        "now": now_dt,
                        "resp": "balanced",
                    },
                )
            await db_session.commit()
        except Exception as exc:
            logger.error(
                "memory_profile_store_failed stage=%s status=%s error_code=%s "
                "error_type=%s target=%s",
                "memory.profile.store",
                "FAILED",
                "DATABASE_WRITE_FAILED",
                type(exc).__name__,
                "sqlalchemy",
            )
        return

    # 直连模式
    try:
        import uuid as _uuid

        import aiosqlite
        db_path = _get_db_path()
        async with aiosqlite.connect(db_path) as db:
            row = await db.execute(
                "SELECT id FROM user_invest_profiles WHERE user_id = ?", (user_id,)
            )
            exists = await row.fetchone()
            if exists:
                await db.execute(
                    f"UPDATE user_invest_profiles SET {field} = ?, updated_by = ?, "
                    f"updated_at = ? WHERE user_id = ?",
                    (value_db, updated_by, now_str, user_id),
                )
            else:
                await db.execute(
                    # SQLite 分支也补齐 response_pref，保证与 PG NOT NULL 约束一致
                    f"INSERT INTO user_invest_profiles (id, user_id, {field}, updated_by, updated_at, created_at, response_pref) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(_uuid.uuid4()), user_id, value_db, updated_by, now_str, now_str, "balanced"),
                )
            await db.commit()
    except ImportError:
        import sqlite3
        import uuid as _uuid
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT id FROM user_invest_profiles WHERE user_id = ?", (user_id,))
        exists = cur.fetchone()
        if exists:
            conn.execute(
                f"UPDATE user_invest_profiles SET {field} = ?, updated_by = ?, "
                f"updated_at = ? WHERE user_id = ?",
                (value_db, updated_by, now_str, user_id),
            )
        else:
            conn.execute(
                # SQLite 分支也补齐 response_pref，保证与 PG NOT NULL 约束一致
                f"INSERT INTO user_invest_profiles (id, user_id, {field}, updated_by, updated_at, created_at, response_pref) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(_uuid.uuid4()), user_id, value_db, updated_by, now_str, now_str, "balanced"),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error(
            "memory_profile_store_failed stage=%s status=%s error_code=%s "
            "error_type=%s target=%s",
            "memory.profile.store",
            "FAILED",
            "DATABASE_WRITE_FAILED",
            type(exc).__name__,
            "sqlite",
        )


async def _enqueue_task(
    user_id: str,
    task_type: str,
    payload: str,
    db_session=None,
) -> None:
    """向 ltm_write_tasks 队列插入待处理任务。"""
    now_dt = datetime.utcnow()
    now_str = now_dt.isoformat()

    if db_session is not None:
        from sqlalchemy import text
        try:
            await db_session.execute(
                text(
                    "INSERT INTO ltm_write_tasks (user_id, task_type, payload, status, retry_count, created_at) "
                    "VALUES (:uid, :tt, :pl, 'pending', 0, :now)"
                ),
                {"uid": user_id, "tt": task_type, "pl": payload, "now": now_dt},
            )
            await db_session.commit()
        except Exception as exc:
            logger.error(
                "memory_task_enqueue_failed stage=%s status=%s error_code=%s "
                "error_type=%s",
                "memory.task.enqueue",
                "FAILED",
                "DATABASE_WRITE_FAILED",
                type(exc).__name__,
            )
        return

    # 直连模式
    await _db_execute(
        "INSERT INTO ltm_write_tasks (user_id, task_type, payload, status, retry_count, created_at) "
        "VALUES (?, ?, ?, 'pending', 0, ?)",
        (user_id, task_type, payload, now_str),
    )


async def _reset_profile(user_id: str, db_session=None) -> None:
    """重置 user_invest_profiles 所有字段为 NULL 默认值。"""
    now_dt = datetime.utcnow()
    now_str = now_dt.isoformat()

    if db_session is not None:
        from sqlalchemy import text
        try:
            await db_session.execute(
                text(
                    "UPDATE user_invest_profiles SET "
                    "risk_level=NULL, investment_horizon=NULL, "
                    "expected_return_min=NULL, expected_return_max=NULL, "
                    "sectors=CAST(:empty_sectors AS JSONB), constraints=CAST(:empty_constraints AS JSONB), response_pref='balanced', "
                    "updated_by='system', updated_at=:now "
                    "WHERE user_id=:uid"
                ),
                {"now": now_dt, "uid": user_id, "empty_sectors": "[]", "empty_constraints": "[]"},
            )
            await db_session.commit()
        except Exception as exc:
            logger.error(
                "memory_profile_reset_failed stage=%s status=%s error_code=%s "
                "error_type=%s",
                "memory.profile.reset",
                "FAILED",
                "DATABASE_WRITE_FAILED",
                type(exc).__name__,
            )
        return

    await _db_execute(
        "UPDATE user_invest_profiles SET "
        "risk_level=NULL, investment_horizon=NULL, "
        "expected_return_min=NULL, expected_return_max=NULL, "
        "sectors='[]', constraints='[]', response_pref='balanced', "
        "updated_by='system', updated_at=? "
        "WHERE user_id=?",
        (now_str, user_id),
    )
