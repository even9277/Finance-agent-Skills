"""
LTM 异步写入 Worker - Phase 3

负责轮询 ltm_write_tasks 表中的 pending 任务，
并调用 AsyncMemory 执行实际的 Mem0 写入操作。

设计原则：
- 每隔 LTM_WORKER_INTERVAL_SEC（默认 5s）轮询一次
- 按 task_type 分发到对应的 Mem0 操作
- 成功 → status='done'，失败 → retry_count+1；≥3 次 → status='failed'，写 error_msg
- worker 异常不影响主进程（FastAPI 主链路完全解耦）
- 使用直连 SQLite（不依赖 FastAPI 的 DB session）

启动方式：在 FastAPI lifespan 中以 asyncio.create_task() 启动
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_MEMORY_DIR = Path(__file__).resolve().parent
_AGENT_SRC = _MEMORY_DIR.parent
if str(_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENT_SRC))

from src.utils.logging_config import setup_logger
from src.memory.mem0_schema import SOURCE_PRIORITY, MemorySource
from src.memory.memory_service import MemoryService

logger = setup_logger("ltm_worker")

LTM_WORKER_INTERVAL_SEC = int(os.getenv("LTM_WORKER_INTERVAL_SEC", "5"))
LTM_WORKER_MAX_RETRIES = 3
LTM_WORKER_BATCH_SIZE = 10  # 每次轮询最多处理 N 条任务
LTM_WORKER_TASK_TIMEOUT_SEC = int(os.getenv("LTM_WORKER_TASK_TIMEOUT_SEC", "90"))
LTM_WORKER_STALE_PROCESSING_SEC = int(os.getenv("LTM_WORKER_STALE_PROCESSING_SEC", "120"))

# Mem0 add(infer=True) 在部分版本/LLM 下会产出非字符串 facts，触发 embed 阶段 dict.replace 崩溃。
# 对话路径已由 profile_extractor 生成事实字符串；explicit_update/cold_start 亦为可读文本，无需二次推理。
# 默认关闭 infer；仅当显式 LTM_MEM0_INFER=true 且任务 metadata.mem0_infer!=False 时尝试（不推荐生产）。
_LTM_MEM0_INFER_OPT_IN = os.getenv("LTM_MEM0_INFER", "").lower() in ("true", "1", "yes")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


_ENABLE_PREWRITE_DEDUPE = _env_flag("ENABLE_PREWRITE_DEDUPE", False)
_ENABLE_MEMORY_CANDIDATE_POOL = _env_flag("ENABLE_MEMORY_CANDIDATE_POOL", False)
_IDEMPOTENCY_WINDOW_SEC = int(os.getenv("LTM_IDEMPOTENCY_WINDOW_SEC", "1800"))  # 30分钟
_CANDIDATE_FORGET_DAYS = int(os.getenv("MEMORY_CANDIDATE_FORGET_DAYS", "30"))
_GOVERNANCE_METRICS_INTERVAL_SEC = int(os.getenv("MEMORY_GOVERNANCE_METRICS_INTERVAL_SEC", "600"))
_LAST_GOVERNANCE_METRICS_TS = 0.0
_LAST_AUTO_FORGET_TS = 0.0

_CATEGORY_THRESHOLD_MAP: dict[str, float] = {
    "risk_profile": 0.82,
    "sector_focus": 0.88,
    "response_preference": 0.85,
}

_SINGLE_VALUE_CATEGORIES = {"risk_profile", "horizon", "response_preference"}

_TEXT_SYNONYMS = {
    "高股息": "红利",
    "大模型": "ai",
    "人工智能": "ai",
    "稳健": "moderate",
    "平衡": "balanced",
    "保守": "conservative",
    "激进": "aggressive",
}


def _candidate_governance_enabled() -> bool:
    """候选池治理仅在显式启用候选池时运行，避免缺表时污染主链路日志。"""
    return bool(_ENABLE_MEMORY_CANDIDATE_POOL)


def _is_postgres_mode() -> bool:
    """
    判断 outbox(ltm_write_tasks) 是否位于 PostgreSQL。
    Phase 3 真实部署通常使用 PostgreSQL；若 worker 仍读本地 SQLite，
    会导致“入队成功但永远 pending，Mem0 永远没有条目”。
    """
    db_url = os.getenv("DATABASE_URL", "") or ""
    return db_url.startswith("postgresql")


def _get_db_path() -> str:
    return os.getenv(
        "SQLITE_DB_PATH",
        str(_AGENT_SRC.parent.parent / "backend" / "finance.db")
    )


def _normalize_text_for_fingerprint(text: str) -> str:
    normalized = str(text or "").strip().lower()
    for src, dst in _TEXT_SYNONYMS.items():
        normalized = normalized.replace(src, dst)
    normalized = normalized.replace("，", ",").replace("。", ".").replace("；", ";")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[!！?？。.;；,，:：]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8", errors="ignore")).hexdigest()


def _source_priority(source: str) -> int:
    source_val = str(source or "").strip()
    for key, val in SOURCE_PRIORITY.items():
        if str(key.value) == source_val:
            return int(val)
    return 0


def _infer_category_from_fact_text(fact_text: str) -> str:
    """
    为 chat/summary 抽取出的事实补齐 category。
    背景：profile_extractor 当前按「文本 facts + 共享 metadata」入队，
    若 metadata 未携带 category，去重/冲突规则会被弱化。
    """
    text_raw = str(fact_text or "").strip()
    if not text_raw:
        return ""
    text_norm = _normalize_text_for_fingerprint(text_raw)

    # A 类结构化字段（profile_extractor.build_fact_messages 的固定模板）
    if "风险偏好" in text_raw:
        return "risk_profile"
    if "持有周期" in text_raw or "投资周期" in text_raw:
        return "horizon"
    if "关注投资板块" in text_raw or "板块" in text_raw:
        return "sector_focus"
    if "投资约束" in text_raw or "约束条件" in text_raw or "不碰" in text_raw:
        return "constraints"
    if "回答偏好" in text_raw:
        return "response_preference"
    if "期望收益率" in text_raw or "收益" in text_raw:
        return "risk_profile"

    # B 类风格事实（以“用户偏好：”开头）
    if text_raw.startswith("用户偏好"):
        if "简洁" in text_raw or "详细" in text_raw or "先陈述风险" in text_raw or "先讲风险" in text_raw:
            return "response_preference"
        return "response_preference"

    # 回退：无法识别时仍返回空，由既有逻辑兜底
    if "risk" in text_norm and "preference" in text_norm:
        return "risk_profile"
    return ""


def _is_weak_inferred_source(source: str) -> bool:
    return str(source or "").strip() in {
        MemorySource.CHAT_INFERRED.value,
        MemorySource.REPORT_INFERRED.value,
    }


def _extract_fact_texts(messages: Any) -> list[str]:
    facts: list[str] = []
    if not isinstance(messages, list):
        return facts
    for msg in messages:
        if isinstance(msg, dict):
            content = str(msg.get("content") or "").strip()
        else:
            content = str(msg or "").strip()
        if content:
            facts.append(content[:1200])
    return facts


def _coerce_messages_for_mem0(messages: Any) -> tuple[list[dict], list[str]]:
    """
    兼容不同 mem0 版本的 messages 入参格式：
    - 有的版本支持 [{"role","content"}] 结构
    - 有的版本内部会对 message 做 .replace(...)，因此只接受纯文本字符串
    返回 (dict_messages, text_messages) 两种表示，供重试回退。
    """
    dict_messages: list[dict] = []
    text_messages: list[str] = []

    if not messages:
        return ([], [])

    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict):
                role = str(m.get("role", "user"))
                content = m.get("content", "")
                content_str = str(content) if content is not None else ""
                dict_messages.append({"role": role, "content": content_str})
                text_messages.append(f"[{role}] {content_str}")
            else:
                s = str(m)
                dict_messages.append({"role": "user", "content": s})
                text_messages.append(s)
    else:
        s = str(messages)
        dict_messages = [{"role": "user", "content": s}]
        text_messages = [s]

    return (dict_messages, text_messages)


async def _mem0_add_safe(mem0_client: Any, *, user_id: str, messages: Any, metadata: dict) -> None:
    """
    对 mem0_client.add 做兼容与超时保护：
    - 尝试多种格式：dict messages / 纯文本列表 / 单条拼接文本
    - 针对不同 mem0 版本的兼容性异常做三层回退

    infer 策略（稳定优先）：
    - 默认 infer=False，避免 explicit_update / cold_start / 事实字符串入队等路径触发 Mem0 内部崩溃。
    - 仅当环境变量 LTM_MEM0_INFER=true 且 metadata 未禁止（mem0_infer 不为 False）且非预抽取任务时，
      才尝试 infer=True；失败仍按下方逻辑回退 infer=False。
    """
    dict_messages, text_messages = _coerce_messages_for_mem0(messages)
    single_text = "\n".join(text_messages) if text_messages else ""

    # 注意：extracted_fields 可能为 []（仅 B 类 style_facts、无结构化字段时），
    # 仍表示 payload 已是预格式化事实，必须用 infer=False；不能用 bool([])。
    has_pre_extraction = "extracted_fields" in metadata
    meta_infer = metadata.get("mem0_infer")
    # 显式 False 强制关闭；None/缺省在 opt-in 模式下才允许 True
    use_infer = (
        _LTM_MEM0_INFER_OPT_IN
        and not has_pre_extraction
        and meta_infer is not False
    )

    async def _call(payload_messages: Any, infer: bool) -> None:
        await asyncio.wait_for(
            mem0_client.add(
                messages=payload_messages,
                user_id=user_id,
                metadata=metadata,
                infer=infer,
            ),
            timeout=LTM_WORKER_TASK_TIMEOUT_SEC,
        )

    # 第一次尝试：标准 dict 消息格式
    try:
        await _call(dict_messages, infer=use_infer)
        return
    except Exception as exc1:
        msg1 = str(exc1)
        # 超时直接抛出不重试
        if isinstance(exc1, asyncio.TimeoutError):
            logger.warning(
                f"[ltm_worker] mem0.add 超时 ({LTM_WORKER_TASK_TIMEOUT_SEC}s): user={user_id}"
            )
            raise

        # infer=True 导致崩溃（dict.replace 问题），自动降级到 infer=False
        if use_infer and ("replace" in msg1 or "string indices must be integers" in msg1):
            logger.warning(
                f"[ltm_worker] infer=True 崩溃，自动回退 infer=False: user={user_id}, err={msg1[:120]}"
            )
            use_infer = False
            try:
                await _call(dict_messages, infer=False)
                return
            except Exception as exc_fallback:
                if isinstance(exc_fallback, asyncio.TimeoutError):
                    raise
                msg1 = str(exc_fallback)

        # 第二次尝试：纯文本列表格式
        if ("has no attribute 'replace'" in msg1 or "string indices must be integers" in msg1) and text_messages:
            try:
                logger.debug(
                    f"[ltm_worker] mem0.add dict格式失败，尝试纯文本列表: user={user_id}, err={msg1[:120]}"
                )
                await _call(text_messages, infer=False)
                return
            except Exception as exc2:
                msg2 = str(exc2)
                if isinstance(exc2, asyncio.TimeoutError):
                    raise

                # 第三次尝试：单条拼接文本（最后兜底）
                if ("string indices must be integers" in msg2 or "has no attribute" in msg2) and single_text:
                    try:
                        logger.debug(
                            f"[ltm_worker] mem0.add 纯文本列表失败，尝试单条文本: user={user_id}, err={msg2[:120]}"
                        )
                        await _call(single_text, infer=False)
                        return
                    except Exception as exc3:
                        logger.error(
                            f"[ltm_worker] mem0.add 三种格式均失败: user={user_id}, "
                            f"final_err={exc3}",
                            exc_info=True,
                        )
                        raise exc3
                else:
                    raise exc2
        else:
            raise exc1


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


async def _fetch_recent_candidate_by_idempotency(
    user_id: str,
    idempotency_key: str,
    *,
    window_sec: int = _IDEMPOTENCY_WINDOW_SEC,
) -> dict | None:
    cutoff = datetime.utcnow() - timedelta(seconds=max(1, int(window_sec)))
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT id, status, created_at
                        FROM memory_candidates
                        WHERE user_id = :uid
                          AND idempotency_key = :idem
                          AND created_at >= :cutoff
                          AND status <> 'deleted'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"uid": user_id, "idem": idempotency_key, "cutoff": cutoff},
                )
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception:
            return None

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, status, created_at
                FROM memory_candidates
                WHERE user_id = ?
                  AND idempotency_key = ?
                  AND created_at >= ?
                  AND status <> 'deleted'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, idempotency_key, cutoff.isoformat()),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    except Exception:
        return None


async def _fetch_recent_candidate_by_fingerprint(
    user_id: str,
    category: str,
    fingerprint: str,
) -> dict | None:
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT id, status, source, confidence, text, created_at, updated_at
                        FROM memory_candidates
                        WHERE user_id = :uid
                          AND category = :category
                          AND fingerprint = :fp
                          AND status <> 'deleted'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"uid": user_id, "category": category, "fp": fingerprint},
                )
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception:
            return None

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, status, source, confidence, text, created_at, updated_at
                FROM memory_candidates
                WHERE user_id = ?
                  AND category = ?
                  AND fingerprint = ?
                  AND status <> 'deleted'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, category, fingerprint),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    except Exception:
        return None


async def _insert_candidate(
    *,
    user_id: str,
    text_value: str,
    category: str,
    source: str,
    confidence: float,
    evidence_ref: str,
    status: str,
    fingerprint: str,
    idempotency_key: str,
    conflict_group_id: str,
    metadata: dict,
    reviewed_by: str = "",
    rejected_reason: str = "",
) -> str:
    candidate_id = str(uuid.uuid4())
    now_dt = datetime.utcnow()
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)

    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO memory_candidates
                        (id, user_id, text, category, source, confidence, evidence_ref, status,
                         conflict_group_id, fingerprint, idempotency_key, candidate_metadata,
                         active, reviewed_at, reviewed_by, rejected_reason, created_at, updated_at)
                        VALUES
                        (:id, :uid, :text, :category, :source, :confidence, :evidence_ref, :status,
                         :conflict_group_id, :fingerprint, :idempotency_key, CAST(:metadata AS JSONB),
                         :active, :reviewed_at, :reviewed_by, :rejected_reason, :created_at, :updated_at)
                        """
                    ),
                    {
                        "id": candidate_id,
                        "uid": user_id,
                        "text": text_value,
                        "category": category,
                        "source": source,
                        "confidence": confidence,
                        "evidence_ref": evidence_ref,
                        "status": status,
                        "conflict_group_id": conflict_group_id or None,
                        "fingerprint": fingerprint,
                        "idempotency_key": idempotency_key,
                        "metadata": meta_json,
                        "active": status != "deleted",
                        "reviewed_at": now_dt if status != "pending" else None,
                        "reviewed_by": reviewed_by or None,
                        "rejected_reason": rejected_reason or None,
                        "created_at": now_dt,
                        "updated_at": now_dt,
                    },
                )
                await db.commit()
            return candidate_id
        except Exception as exc:
            logger.warning("[ltm_worker] insert candidate PG 失败: %s", exc)
            return ""

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            await db.execute(
                """
                INSERT INTO memory_candidates
                (id, user_id, text, category, source, confidence, evidence_ref, status,
                 conflict_group_id, fingerprint, idempotency_key, candidate_metadata,
                 active, reviewed_at, reviewed_by, rejected_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    user_id,
                    text_value,
                    category,
                    source,
                    confidence,
                    evidence_ref,
                    status,
                    conflict_group_id or None,
                    fingerprint,
                    idempotency_key,
                    meta_json,
                    0 if status == "deleted" else 1,
                    now_dt.isoformat() if status != "pending" else None,
                    reviewed_by or None,
                    rejected_reason or None,
                    now_dt.isoformat(),
                    now_dt.isoformat(),
                ),
            )
            await db.commit()
        return candidate_id
    except Exception as exc:
        logger.warning("[ltm_worker] insert candidate SQLite 失败: %s", exc)
        return ""


async def _update_candidate_status(
    candidate_id: str,
    *,
    status: str,
    reviewed_by: str = "worker",
    rejected_reason: str = "",
    conflict_group_id: str = "",
) -> None:
    now_dt = datetime.utcnow()
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                await db.execute(
                    text(
                        """
                        UPDATE memory_candidates
                        SET status = :status,
                            reviewed_at = :reviewed_at,
                            reviewed_by = :reviewed_by,
                            rejected_reason = :rejected_reason,
                            conflict_group_id = COALESCE(:conflict_group_id, conflict_group_id),
                            active = :active,
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    {
                        "status": status,
                        "reviewed_at": now_dt,
                        "reviewed_by": reviewed_by,
                        "rejected_reason": rejected_reason or None,
                        "conflict_group_id": conflict_group_id or None,
                        "active": status != "deleted",
                        "updated_at": now_dt,
                        "id": candidate_id,
                    },
                )
                await db.commit()
            return
        except Exception:
            return

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            await db.execute(
                """
                UPDATE memory_candidates
                SET status = ?,
                    reviewed_at = ?,
                    reviewed_by = ?,
                    rejected_reason = ?,
                    conflict_group_id = COALESCE(?, conflict_group_id),
                    active = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    now_dt.isoformat(),
                    reviewed_by,
                    rejected_reason or None,
                    conflict_group_id or None,
                    0 if status == "deleted" else 1,
                    now_dt.isoformat(),
                    candidate_id,
                ),
            )
            await db.commit()
    except Exception:
        return


async def _insert_audit_log(
    *,
    user_id: str,
    candidate_id: str,
    action: str,
    reason: str,
    before_json: dict | None = None,
    after_json: dict | None = None,
    actor: str = "worker",
) -> None:
    before_payload = json.dumps(before_json or {}, ensure_ascii=False, default=str)
    after_payload = json.dumps(after_json or {}, ensure_ascii=False, default=str)
    now_dt = datetime.utcnow()

    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO memory_audit_logs
                        (candidate_id, user_id, actor, action, before_json, after_json, reason, created_at)
                        VALUES
                        (:candidate_id, :user_id, :actor, :action,
                         CAST(:before_json AS JSONB), CAST(:after_json AS JSONB), :reason, :created_at)
                        """
                    ),
                    {
                        "candidate_id": candidate_id,
                        "user_id": user_id,
                        "actor": actor,
                        "action": action,
                        "before_json": before_payload,
                        "after_json": after_payload,
                        "reason": reason,
                        "created_at": now_dt,
                    },
                )
                await db.commit()
            return
        except Exception:
            return

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            await db.execute(
                """
                INSERT INTO memory_audit_logs
                (candidate_id, user_id, actor, action, before_json, after_json, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    user_id,
                    actor,
                    action,
                    before_payload,
                    after_payload,
                    reason,
                    now_dt.isoformat(),
                ),
            )
            await db.commit()
    except Exception:
        return


async def _decide_before_write(
    *,
    user_id: str,
    fact_text: str,
    metadata: dict,
) -> dict[str, Any]:
    category = str(metadata.get("category") or "")
    source = str(metadata.get("source") or "")
    confidence = _to_float(metadata.get("confidence"), 0.7)
    normalized = _normalize_text_for_fingerprint(fact_text)
    fingerprint = _sha256(f"{user_id}|{category}|{normalized}")
    idempotency_key = _sha256(f"{user_id}|{category}|{fingerprint}|{source}")

    decision: dict[str, Any] = {
        "action": "ADD",
        "reason": "default_add",
        "category": category,
        "source": source,
        "confidence": confidence,
        "normalized_text": normalized,
        "fingerprint": fingerprint,
        "idempotency_key": idempotency_key,
        "conflict_group_id": "",
        "semantic_hit": None,
    }

    idem_hit = await _fetch_recent_candidate_by_idempotency(user_id, idempotency_key)
    if idem_hit:
        decision["action"] = "NOOP"
        decision["reason"] = "idempotency_window_hit"
        return decision

    hard_hit = await _fetch_recent_candidate_by_fingerprint(user_id, category, fingerprint)
    if hard_hit:
        decision["action"] = "NOOP"
        decision["reason"] = "hard_dedupe_hit"
        return decision

    semantic_hits = await MemoryService.search_semantic(
        user_id=user_id,
        query=fact_text,
        categories=[category] if category else None,
        top_k=3,
        threshold=0.60,
        dedupe_mode=True,
        category_threshold_map=_CATEGORY_THRESHOLD_MAP,
    )
    if not semantic_hits:
        return decision

    top_hit = semantic_hits[0]
    decision["semantic_hit"] = top_hit
    existing_text = str(top_hit.get("text") or "")
    existing_norm = _normalize_text_for_fingerprint(existing_text)
    if existing_norm == normalized:
        decision["action"] = "MERGE"
        decision["reason"] = "semantic_same_fact"
        return decision

    if category in _SINGLE_VALUE_CATEGORIES:
        decision["conflict_group_id"] = f"{user_id}:{category}"
        decision["reason"] = "single_value_conflict"
        new_pri = _source_priority(source)
        old_source = str(top_hit.get("source") or (top_hit.get("metadata") or {}).get("source") or "")
        old_pri = _source_priority(old_source)
        if new_pri < old_pri:
            decision["action"] = "NOOP"
            decision["reason"] = "lower_source_priority"
            return decision
        if new_pri > old_pri:
            decision["action"] = "UPDATE"
            return decision

        old_conf = _to_float(top_hit.get("confidence"), 0.0)
        if confidence > old_conf:
            decision["action"] = "UPDATE"
            decision["reason"] = "same_priority_higher_confidence"
        elif confidence < old_conf:
            decision["action"] = "NOOP"
            decision["reason"] = "same_priority_lower_confidence"
        else:
            old_updated = _parse_dt(top_hit.get("updated_at"))
            new_updated = _parse_dt(metadata.get("updated_at")) or datetime.utcnow()
            if old_updated is None or new_updated >= old_updated:
                decision["action"] = "UPDATE"
                decision["reason"] = "same_priority_newer_update"
            else:
                decision["action"] = "NOOP"
                decision["reason"] = "same_priority_older_update"
        return decision

    decision["action"] = "ADD"
    decision["reason"] = "semantic_near_but_multi_value"
    return decision

async def _fetch_pending_tasks(limit: int = LTM_WORKER_BATCH_SIZE) -> list[dict]:
    """认领 pending 任务并标记 processing（PostgreSQL: FOR UPDATE SKIP LOCKED）。"""
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                # 回收卡住的 processing 任务：避免因异常/超时导致永远停留在 processing 而不再被消费
                try:
                    await db.execute(
                        text(
                            "UPDATE ltm_write_tasks "
                            "SET status='pending', retry_count=retry_count+1, "
                            "error_msg=COALESCE(error_msg,'') || ' | stale-processing-reset' "
                            "WHERE status='processing' "
                            "AND COALESCE(processed_at, created_at) < (NOW() - (:sec * INTERVAL '1 second'))"
                        ),
                        {"sec": LTM_WORKER_STALE_PROCESSING_SEC},
                    )
                    await db.commit()
                except Exception:
                    # 回收失败不阻断正常拉取
                    await db.rollback()

                result = await db.execute(
                    text(
                        """
                        WITH picked AS (
                            SELECT id
                            FROM ltm_write_tasks
                            WHERE status = 'pending'
                            ORDER BY created_at ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT :limit
                        )
                        UPDATE ltm_write_tasks t
                        SET status = 'processing',
                            processed_at = NOW(),
                            error_msg = COALESCE(t.error_msg, '')
                        FROM picked
                        WHERE t.id = picked.id
                        RETURNING t.id, t.user_id, t.task_type, t.payload, t.retry_count
                        """
                    ),
                    {"limit": limit},
                )
                rows = [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "task_type": r.task_type,
                        "payload": r.payload,
                        "retry_count": r.retry_count,
                    }
                    for r in result.fetchall()
                ]
                await db.commit()
                return rows
        except Exception as exc:
            logger.error(f"[ltm_worker] fetch_pending_tasks(PG) 失败: {exc}", exc_info=True)
            return []

    try:
        import aiosqlite
        async with aiosqlite.connect(_get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            try:
                async with db.execute(
                    "SELECT id, user_id, task_type, payload, retry_count FROM ltm_write_tasks "
                    "WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
                    (limit,),
                ) as cursor:
                    rows = await cursor.fetchall()
                claimed: list[dict] = []
                for row in rows:
                    task_id = int(row["id"])
                    cur = await db.execute(
                        "UPDATE ltm_write_tasks SET status='processing', processed_at=? "
                        "WHERE id=? AND status='pending'",
                        (datetime.utcnow().isoformat(), task_id),
                    )
                    if cur.rowcount and int(cur.rowcount) > 0:
                        claimed.append(dict(row))
                await db.commit()
                return claimed
            except aiosqlite.OperationalError as exc:
                # SQLite 模式下尚未创建 ltm_write_tasks 表时，视为“当前无任务”，避免刷屏错误。
                if "no such table" in str(exc):
                    logger.debug("[ltm_worker] SQLite 中尚未创建 ltm_write_tasks 表，视为无 pending 任务")
                    return []
                raise
    except ImportError:
        import sqlite3
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                "SELECT id, user_id, task_type, payload, retry_count FROM ltm_write_tasks "
                "WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
            claimed: list[dict] = []
            for row in rows:
                task_id = int(row["id"])
                updated = conn.execute(
                    "UPDATE ltm_write_tasks SET status='processing', processed_at=? "
                    "WHERE id=? AND status='pending'",
                    (datetime.utcnow().isoformat(), task_id),
                )
                if updated.rowcount and int(updated.rowcount) > 0:
                    claimed.append(dict(row))
            conn.commit()
            return claimed
        except sqlite3.OperationalError as exc:
            # 本地 SQLite 尚未创建 ltm_write_tasks 表时，静默视为“无任务”，避免刷屏报错。
            if "no such table" in str(exc):
                logger.debug("[ltm_worker] SQLite 中尚未创建 ltm_write_tasks 表，视为无 pending 任务")
                return []
            raise
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"[ltm_worker] fetch_pending_tasks 失败: {exc}", exc_info=True)
        return []


async def _update_task_status(
    task_id: int,
    status: str,
    retry_count: int = 0,
    error_msg: str = "",
) -> None:
    """更新 ltm_write_tasks 任务状态。"""
    now_dt = datetime.utcnow()
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                if status in ("done", "failed"):
                    await db.execute(
                        text(
                            "UPDATE ltm_write_tasks "
                            "SET status=:status, retry_count=:retry, error_msg=:err, processed_at=:now "
                            "WHERE id=:id"
                        ),
                        {
                            "status": status,
                            "retry": retry_count,
                            "err": error_msg,
                            "now": now_dt,
                            "id": task_id,
                        },
                    )
                else:
                    await db.execute(
                        text(
                            "UPDATE ltm_write_tasks "
                            "SET status=:status, retry_count=:retry, error_msg=:err "
                            "WHERE id=:id"
                        ),
                        {
                            "status": status,
                            "retry": retry_count,
                            "err": error_msg,
                            "id": task_id,
                        },
                    )
                await db.commit()
            return
        except Exception as exc:
            logger.error(f"[ltm_worker] update_task_status(PG) 失败: {exc}", exc_info=True)
            return

    now = now_dt.isoformat()
    try:
        import aiosqlite
        async with aiosqlite.connect(_get_db_path()) as db:
            if status in ("done", "failed"):
                await db.execute(
                    "UPDATE ltm_write_tasks SET status=?, retry_count=?, error_msg=?, "
                    "processed_at=? WHERE id=?",
                    (status, retry_count, error_msg, now, task_id),
                )
            else:
                await db.execute(
                    "UPDATE ltm_write_tasks SET status=?, retry_count=?, error_msg=? WHERE id=?",
                    (status, retry_count, error_msg, task_id),
                )
            await db.commit()
    except ImportError:
        import sqlite3
        conn = sqlite3.connect(_get_db_path())
        if status in ("done", "failed"):
            conn.execute(
                "UPDATE ltm_write_tasks SET status=?, retry_count=?, error_msg=?, "
                "processed_at=? WHERE id=?",
                (status, retry_count, error_msg, now, task_id),
            )
        else:
            conn.execute(
                "UPDATE ltm_write_tasks SET status=?, retry_count=?, error_msg=? WHERE id=?",
                (status, retry_count, error_msg, task_id),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error(f"[ltm_worker] update_task_status 失败: {exc}", exc_info=True)


def _base_decision(user_id: str, fact_text: str, metadata: dict) -> dict[str, Any]:
    category = str(metadata.get("category") or "")
    source = str(metadata.get("source") or "")
    normalized = _normalize_text_for_fingerprint(fact_text)
    fingerprint = _sha256(f"{user_id}|{category}|{normalized}")
    idempotency_key = _sha256(f"{user_id}|{category}|{fingerprint}|{source}")
    return {
        "action": "ADD",
        "reason": "dedupe_disabled",
        "category": category,
        "source": source,
        "confidence": _to_float(metadata.get("confidence"), 0.7),
        "normalized_text": normalized,
        "fingerprint": fingerprint,
        "idempotency_key": idempotency_key,
        "conflict_group_id": "",
        "semantic_hit": None,
    }


async def _process_fact_write(
    *,
    mem0_client: Any,
    user_id: str,
    fact_text: str,
    metadata: dict,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    meta.setdefault("active", True)
    meta.setdefault("source", "chat_inferred")
    meta.setdefault("confidence", 0.7)
    meta.setdefault("updated_by", "llm")
    meta.setdefault("mem0_infer", False)
    # 真实 chat/summary 抽取链路里 category 可能缺失；补齐后才能稳定命中去重/冲突规则。
    if not str(meta.get("category") or "").strip():
        inferred_category = _infer_category_from_fact_text(fact_text)
        if inferred_category:
            meta["category"] = inferred_category

    decision = _base_decision(user_id, fact_text, meta)
    if _ENABLE_PREWRITE_DEDUPE:
        decision = await _decide_before_write(user_id=user_id, fact_text=fact_text, metadata=meta)

    category = str(decision.get("category") or meta.get("category") or "")
    source = str(decision.get("source") or meta.get("source") or "")
    confidence = _to_float(decision.get("confidence"), _to_float(meta.get("confidence"), 0.7))
    fingerprint = str(decision.get("fingerprint") or "")
    idempotency_key = str(decision.get("idempotency_key") or "")
    conflict_group_id = str(decision.get("conflict_group_id") or "")
    action = str(decision.get("action") or "ADD")
    reason = str(decision.get("reason") or "")

    weak_candidate_only = (
        _ENABLE_MEMORY_CANDIDATE_POOL
        and _is_weak_inferred_source(source)
        and not bool(meta.get("from_candidate_review"))
    )

    candidate_id = ""
    if weak_candidate_only:
        status = "pending"
        rejected_reason = ""
        if action in {"NOOP", "MERGE"}:
            status = "rejected"
            rejected_reason = reason or "dedupe_reject"
        candidate_id = await _insert_candidate(
            user_id=user_id,
            text_value=fact_text,
            category=category,
            source=source,
            confidence=confidence,
            evidence_ref=str(meta.get("evidence_ref") or ""),
            status=status,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            conflict_group_id=conflict_group_id,
            metadata=meta,
            reviewed_by="worker" if status != "pending" else "",
            rejected_reason=rejected_reason,
        )
        if candidate_id:
            await _insert_audit_log(
                user_id=user_id,
                candidate_id=candidate_id,
                action="candidate_ingest",
                reason=f"action={action}|{reason or 'weak_source'}",
                before_json={},
                after_json={"status": status, "source": source, "category": category},
                actor="worker",
            )
        return {
            "action": action,
            "reason": reason or "weak_source_candidate_only",
            "written": False,
            "candidate_id": candidate_id,
            "conflict": bool(conflict_group_id),
        }

    if action in {"NOOP", "MERGE"}:
        reviewed_candidate_id = str(meta.get("candidate_id") or "")
        if reviewed_candidate_id:
            await _update_candidate_status(
                reviewed_candidate_id,
                status="promoted",
                reviewed_by="worker",
                rejected_reason="",
                conflict_group_id=conflict_group_id,
            )
            await _insert_audit_log(
                user_id=user_id,
                candidate_id=reviewed_candidate_id,
                action="promote_noop",
                reason=reason or "already_exists",
                before_json={},
                after_json={"status": "promoted"},
                actor="worker",
            )
        return {"action": action, "reason": reason, "written": False, "candidate_id": reviewed_candidate_id, "conflict": bool(conflict_group_id)}

    if action == "UPDATE":
        semantic_hit = decision.get("semantic_hit") or {}
        memory_id = str(semantic_hit.get("id") or "")
        if memory_id:
            await mem0_client.update(memory_id, fact_text, metadata=meta)
            reviewed_candidate_id = str(meta.get("candidate_id") or "")
            if reviewed_candidate_id:
                await _update_candidate_status(reviewed_candidate_id, status="promoted", reviewed_by="worker")
            return {"action": action, "reason": reason, "written": True, "candidate_id": reviewed_candidate_id, "conflict": bool(conflict_group_id)}

    await _mem0_add_safe(
        mem0_client,
        user_id=user_id,
        messages=[{"role": "user", "content": fact_text}],
        metadata=meta,
    )
    reviewed_candidate_id = str(meta.get("candidate_id") or "")
    if reviewed_candidate_id:
        await _update_candidate_status(reviewed_candidate_id, status="promoted", reviewed_by="worker")
        await _insert_audit_log(
            user_id=user_id,
            candidate_id=reviewed_candidate_id,
            action="promote",
            reason=reason or "mem0_add",
            before_json={},
            after_json={"status": "promoted"},
            actor="worker",
        )
    return {"action": action, "reason": reason, "written": True, "candidate_id": reviewed_candidate_id, "conflict": bool(conflict_group_id)}


async def _process_task(task: dict, mem0_client: Any) -> None:
    """执行单条 LTM 任务，对应 AsyncMemory API 调用。"""
    task_id = task["id"]
    user_id = task["user_id"]
    task_type = task["task_type"]
    retry_count = task.get("retry_count", 0)

    try:
        payload = json.loads(task["payload"])
    except Exception:
        await _update_task_status(task_id, "failed", retry_count, "payload JSON 解析失败")
        return

    try:
        if task_type == "add_conversation":
            messages = payload.get("messages", [])
            metadata = payload.get("metadata", {})
            fact_texts = _extract_fact_texts(messages)
            writes = 0
            noops = 0
            conflicts = 0
            for fact_text in fact_texts:
                outcome = await _process_fact_write(
                    mem0_client=mem0_client,
                    user_id=user_id,
                    fact_text=fact_text,
                    metadata=metadata,
                )
                if outcome.get("written"):
                    writes += 1
                if str(outcome.get("action") or "") in {"NOOP", "MERGE"}:
                    noops += 1
                if outcome.get("conflict"):
                    conflicts += 1
            logger.info(
                f"[ltm_worker] add_conversation 完成: task={task_id}, user={user_id}, "
                f"facts={len(fact_texts)}, writes={writes}, noops={noops}, conflicts={conflicts}, "
                f"source={metadata.get('source')}"
            )

        elif task_type == "explicit_update":
            field = payload.get("field", "")
            value = payload.get("value", "")
            source = payload.get("source", "ui")
            
            # 将 value 转为可读字符串（列表时用逗号分隔）
            if isinstance(value, list):
                value_str = ", ".join(str(v) for v in value)
            else:
                value_str = str(value) if value is not None else ""
            
            # 构建可读的文本事实
            fact_text = f"用户更新 {field} 为 {value_str}"
            metadata = {
                "category": _field_to_category(field),
                "source": source,
                "confidence": 1.0,
                "updated_by": "user",
                "active": True,
                "mem0_infer": False,
            }
            await _process_fact_write(
                mem0_client=mem0_client,
                user_id=user_id,
                fact_text=fact_text,
                metadata=metadata,
            )
            logger.info(
                f"[ltm_worker] explicit_update 完成: task={task_id}, user={user_id}, "
                f"field={field}, source={source}"
            )

        elif task_type == "explicit_delete":
            memory_id = payload.get("memory_id", "")
            if memory_id and memory_id != "noop":
                await mem0_client.delete(memory_id)
                logger.info(f"[ltm_worker] explicit_delete 完成: task={task_id}, memory_id={memory_id}")

        elif task_type == "cold_start":
            tags = payload.get("tags", {})
            watchlist = payload.get("watchlist", [])
            meta_base = payload.get("metadata", {})

            # 构建 cold_start 事实列表（按单事实逐条决策）
            facts: list[tuple[str, dict]] = []
            for field, value in tags.items():
                if value:
                    facts.append(
                        (
                            f"冷启动设置 {field} = {value}",
                            {
                                **meta_base,
                                "category": _field_to_category(str(field)),
                                "source": meta_base.get("source", "cold_start"),
                                "confidence": _to_float(meta_base.get("confidence"), 1.0),
                                "updated_by": "user",
                                "active": True,
                                "mem0_infer": False,
                            },
                        )
                    )
            for stock in watchlist:
                facts.append(
                    (
                        f"自选股/关注标的：{stock}",
                        {
                            **meta_base,
                            "category": "watchlist_stock",
                            "source": meta_base.get("source", "cold_start"),
                            "confidence": _to_float(meta_base.get("confidence"), 1.0),
                            "updated_by": "user",
                            "active": True,
                            "mem0_infer": False,
                        },
                    )
                )

            if facts:
                writes = 0
                noops = 0
                for fact_text, fact_meta in facts:
                    outcome = await _process_fact_write(
                        mem0_client=mem0_client,
                        user_id=user_id,
                        fact_text=fact_text,
                        metadata=fact_meta,
                    )
                    if outcome.get("written"):
                        writes += 1
                    if str(outcome.get("action") or "") in {"NOOP", "MERGE"}:
                        noops += 1
                logger.info(
                    f"[ltm_worker] cold_start 完成: task={task_id}, user={user_id}, "
                    f"facts={len(facts)}, writes={writes}, noops={noops}"
                )

        else:
            logger.warning(f"[ltm_worker] 未知 task_type: {task_type}, task={task_id}")

        await _update_task_status(task_id, "done", retry_count)
        print(f"[ltm_worker] task={task_id} {task_type} 完成 (user={user_id[:8]}...)")

    except Exception as exc:
        new_retry = retry_count + 1
        if new_retry >= LTM_WORKER_MAX_RETRIES:
            await _update_task_status(task_id, "failed", new_retry, str(exc))
            logger.error(
                f"[ltm_worker] task={task_id} 失败超过 {LTM_WORKER_MAX_RETRIES} 次，"
                f"标记为 failed: {exc}",
                exc_info=True,
            )
            print(f"[ltm_worker] task={task_id} 最终失败（已重试 {new_retry} 次）: {exc}")
        else:
            await _update_task_status(task_id, "pending", new_retry, str(exc))
            logger.warning(
                f"[ltm_worker] task={task_id} 失败（重试 {new_retry}/{LTM_WORKER_MAX_RETRIES}）: {exc}",
                exc_info=True,
            )


def _field_to_category(field: str) -> str:
    """将 profile 字段名映射到 MemoryCategory。"""
    mapping = {
        "risk_level": "risk_profile",
        "investment_horizon": "horizon",
        "expected_return_min": "risk_profile",
        "expected_return_max": "risk_profile",
        "sectors": "sector_focus",
        "constraints": "constraints",
        "response_pref": "response_preference",
    }
    return mapping.get(field, field)


async def _auto_forget_candidates() -> None:
    """自动遗忘：将过旧 pending/rejected 候选软删除。"""
    if not _candidate_governance_enabled():
        return
    cutoff = datetime.utcnow() - timedelta(days=max(1, _CANDIDATE_FORGET_DAYS))
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                result = await db.execute(
                    text(
                        """
                        UPDATE memory_candidates
                        SET status = 'deleted',
                            active = false,
                            reviewed_at = COALESCE(reviewed_at, :now),
                            reviewed_by = COALESCE(reviewed_by, 'worker'),
                            rejected_reason = COALESCE(rejected_reason, 'auto_forget'),
                            updated_at = :now
                        WHERE status IN ('pending', 'rejected')
                          AND created_at < :cutoff
                        RETURNING id, user_id
                        """
                    ),
                    {"cutoff": cutoff, "now": datetime.utcnow()},
                )
                rows = result.fetchall()
                await db.commit()
                if rows:
                    for row in rows:
                        await _insert_audit_log(
                            user_id=str(row.user_id or ""),
                            candidate_id=str(row.id),
                            action="auto_forget",
                            reason=f"older_than_{_CANDIDATE_FORGET_DAYS}d",
                            before_json={},
                            after_json={"status": "deleted"},
                            actor="worker",
                        )
                    logger.info("[ltm_worker] auto_forget_candidates: count=%s", len(rows))
            return
        except Exception as exc:
            logger.warning("[ltm_worker] auto_forget_candidates(PG) 失败: %s", exc)
            return

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, user_id
                FROM memory_candidates
                WHERE status IN ('pending', 'rejected')
                  AND created_at < ?
                """,
                (cutoff.isoformat(),),
            ) as cur:
                stale_rows = await cur.fetchall()
            cur = await db.execute(
                """
                UPDATE memory_candidates
                SET status='deleted',
                    active=0,
                    reviewed_at=COALESCE(reviewed_at, ?),
                    reviewed_by=COALESCE(reviewed_by, 'worker'),
                    rejected_reason=COALESCE(rejected_reason, 'auto_forget'),
                    updated_at=?
                WHERE status IN ('pending', 'rejected')
                  AND created_at < ?
                """,
                (
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat(),
                    cutoff.isoformat(),
                ),
            )
            await db.commit()
            if cur.rowcount and int(cur.rowcount) > 0:
                for row in stale_rows:
                    await _insert_audit_log(
                        user_id=str(row["user_id"] or ""),
                        candidate_id=str(row["id"]),
                        action="auto_forget",
                        reason=f"older_than_{_CANDIDATE_FORGET_DAYS}d",
                        before_json={},
                        after_json={"status": "deleted"},
                        actor="worker",
                    )
                logger.info("[ltm_worker] auto_forget_candidates(sqlite): count=%s", int(cur.rowcount))
    except Exception as exc:
        logger.warning("[ltm_worker] auto_forget_candidates(SQLite) 失败: %s", exc)


async def _emit_governance_metrics() -> None:
    """输出治理核心指标（dedupe/冲突/接受率）。"""
    if not _candidate_governance_enabled():
        return
    if _is_postgres_mode():
        try:
            from sqlalchemy import text
            from backend.db.database import AsyncSessionFactory

            async with AsyncSessionFactory() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT
                            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_cnt,
                            SUM(CASE WHEN status = 'promoted' THEN 1 ELSE 0 END) AS promoted_cnt,
                            SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted_cnt,
                            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_cnt,
                            SUM(CASE WHEN conflict_group_id IS NOT NULL AND conflict_group_id <> '' THEN 1 ELSE 0 END) AS conflict_cnt
                        FROM memory_candidates
                        """
                    )
                )
                row = result.fetchone()
                if not row:
                    return
                rejected = int(row.rejected_cnt or 0)
                promoted = int(row.promoted_cnt or 0)
                accepted = int(row.accepted_cnt or 0)
                pending = int(row.pending_cnt or 0)
                conflict_cnt = int(row.conflict_cnt or 0)
                reviewed_total = max(1, rejected + promoted + accepted)
                accept_rate = round((promoted + accepted) / reviewed_total, 4)
                dedupe_noop_ratio = round(rejected / reviewed_total, 4)
                logger.info(
                    "[ltm_worker][metrics] dedupe_noop_ratio=%s conflict_count=%s accept_rate=%s pending=%s",
                    dedupe_noop_ratio,
                    conflict_cnt,
                    accept_rate,
                    pending,
                )
            return
        except Exception as exc:
            logger.debug("[ltm_worker] emit metrics(PG) 失败: %s", exc)
            return

    try:
        import aiosqlite

        async with aiosqlite.connect(_get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_cnt,
                    SUM(CASE WHEN status = 'promoted' THEN 1 ELSE 0 END) AS promoted_cnt,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted_cnt,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_cnt,
                    SUM(CASE WHEN conflict_group_id IS NOT NULL AND conflict_group_id <> '' THEN 1 ELSE 0 END) AS conflict_cnt
                FROM memory_candidates
                """
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return
            rejected = int(row["rejected_cnt"] or 0)
            promoted = int(row["promoted_cnt"] or 0)
            accepted = int(row["accepted_cnt"] or 0)
            pending = int(row["pending_cnt"] or 0)
            conflict_cnt = int(row["conflict_cnt"] or 0)
            reviewed_total = max(1, rejected + promoted + accepted)
            accept_rate = round((promoted + accepted) / reviewed_total, 4)
            dedupe_noop_ratio = round(rejected / reviewed_total, 4)
            logger.info(
                "[ltm_worker][metrics] dedupe_noop_ratio=%s conflict_count=%s accept_rate=%s pending=%s",
                dedupe_noop_ratio,
                conflict_cnt,
                accept_rate,
                pending,
            )
    except Exception:
        return


async def ltm_worker_loop(stop_event: asyncio.Event = None) -> None:
    """
    LTM Worker 主循环。

    - 每隔 LTM_WORKER_INTERVAL_SEC 秒轮询 pending 任务
    - 通过 stop_event 支持优雅停止（FastAPI shutdown 时触发）
    - Mem0 不可用时：任务继续在队列中等待（retry），不影响主进程
    """
    from src.memory.mem0_client import get_mem0_client, is_mem0_available

    print(f"[ltm_worker] 启动，轮询间隔 {LTM_WORKER_INTERVAL_SEC}s")
    logger.info(
        "[ltm_worker] 启动，轮询间隔=%s dedupe=%s candidate_pool=%s",
        LTM_WORKER_INTERVAL_SEC,
        _ENABLE_PREWRITE_DEDUPE,
        _ENABLE_MEMORY_CANDIDATE_POOL,
    )

    while True:
        # 检查停止信号
        if stop_event and stop_event.is_set():
            print("[ltm_worker] 收到停止信号，退出")
            logger.info("[ltm_worker] 停止")
            break

        try:
            now_ts = datetime.utcnow().timestamp()
            global _LAST_AUTO_FORGET_TS, _LAST_GOVERNANCE_METRICS_TS
            if now_ts - _LAST_AUTO_FORGET_TS >= max(60, _GOVERNANCE_METRICS_INTERVAL_SEC):
                await _auto_forget_candidates()
                _LAST_AUTO_FORGET_TS = now_ts

            if now_ts - _LAST_GOVERNANCE_METRICS_TS >= max(60, _GOVERNANCE_METRICS_INTERVAL_SEC):
                await _emit_governance_metrics()
                _LAST_GOVERNANCE_METRICS_TS = now_ts

            if not is_mem0_available():
                logger.warning("[ltm_worker] Mem0 不可用，使用降级路径继续消费任务")

            tasks = await _fetch_pending_tasks()
            if tasks:
                print(f"[ltm_worker] 发现 {len(tasks)} 条 pending 任务，开始处理...")
                logger.info(f"[ltm_worker] 处理 {len(tasks)} 条 pending 任务")
                mem0_client = get_mem0_client()
                for task in tasks:
                    await _process_task(task, mem0_client)
            else:
                logger.debug("[ltm_worker] 无 pending 任务")

        except asyncio.CancelledError:
            print("[ltm_worker] 任务被取消，优雅退出")
            logger.info("[ltm_worker] 任务被取消")
            break
        except Exception as exc:
            logger.error(f"[ltm_worker] worker 循环异常（不影响主进程）: {exc}", exc_info=True)
            print(f"[ltm_worker] 异常（将在下次轮询重试）: {exc}")

        await asyncio.sleep(LTM_WORKER_INTERVAL_SEC)
