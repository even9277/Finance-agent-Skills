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
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_MEMORY_DIR = Path(__file__).resolve().parent
_AGENT_SRC = _MEMORY_DIR.parent
if str(_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENT_SRC))

from src.utils.logging_config import setup_logger

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

async def _fetch_pending_tasks(limit: int = LTM_WORKER_BATCH_SIZE) -> list[dict]:
    """从 ltm_write_tasks 取 pending 任务（按创建时间升序）。"""
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
                            "WHERE status='processing' AND processed_at IS NULL "
                            "AND created_at < (NOW() - (:sec * INTERVAL '1 second'))"
                        ),
                        {"sec": LTM_WORKER_STALE_PROCESSING_SEC},
                    )
                    await db.commit()
                except Exception:
                    # 回收失败不阻断正常拉取
                    await db.rollback()

                result = await db.execute(
                    text(
                        "SELECT id, user_id, task_type, payload, retry_count "
                        "FROM ltm_write_tasks "
                        "WHERE status = 'pending' "
                        "ORDER BY created_at ASC "
                        "LIMIT :limit"
                    ),
                    {"limit": limit},
                )
                rows = result.fetchall()
                return [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "task_type": r.task_type,
                        "payload": r.payload,
                        "retry_count": r.retry_count,
                    }
                    for r in rows
                ]
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
                    return [dict(r) for r in rows]
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
            return [dict(r) for r in rows]
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

    # 标记为 processing
    await _update_task_status(task_id, "processing", retry_count)

    try:
        if task_type == "add_conversation":
            messages = payload.get("messages", [])
            metadata = payload.get("metadata", {})
            metadata.setdefault("active", True)
            await _mem0_add_safe(mem0_client, user_id=user_id, messages=messages, metadata=metadata)
            logger.info(
                f"[ltm_worker] add_conversation 完成: task={task_id}, user={user_id}, "
                f"msgs={len(messages)}, source={metadata.get('source')}"
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
            # 传单条 dict 消息，避免 Mem0 内部 parse_vision_messages 误判
            await _mem0_add_safe(
                mem0_client,
                user_id=user_id,
                messages=[{"role": "user", "content": fact_text}],
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

            # 构建 cold_start 事实列表
            facts = []
            for field, value in tags.items():
                if value:
                    facts.append(f"冷启动设置 {field} = {value}")
            for stock in watchlist:
                facts.append(f"自选股/关注标的：{stock}")

            if facts:
                metadata = {**meta_base, "active": True, "updated_by": "user", "mem0_infer": False}
                # 分批添加，每个 fact 单独一条消息
                messages = [{"role": "user", "content": f} for f in facts]
                await _mem0_add_safe(mem0_client, user_id=user_id, messages=messages, metadata=metadata)
                logger.info(
                    f"[ltm_worker] cold_start 完成: task={task_id}, user={user_id}, "
                    f"facts={len(facts)}"
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


async def ltm_worker_loop(stop_event: asyncio.Event = None) -> None:
    """
    LTM Worker 主循环。

    - 每隔 LTM_WORKER_INTERVAL_SEC 秒轮询 pending 任务
    - 通过 stop_event 支持优雅停止（FastAPI shutdown 时触发）
    - Mem0 不可用时：任务继续在队列中等待（retry），不影响主进程
    """
    from src.memory.mem0_client import get_mem0_client, is_mem0_available

    print(f"[ltm_worker] 启动，轮询间隔 {LTM_WORKER_INTERVAL_SEC}s")
    logger.info(f"[ltm_worker] 启动，轮询间隔={LTM_WORKER_INTERVAL_SEC}s")

    while True:
        # 检查停止信号
        if stop_event and stop_event.is_set():
            print("[ltm_worker] 收到停止信号，退出")
            logger.info("[ltm_worker] 停止")
            break

        try:
            if not is_mem0_available():
                # Mem0 不可用，跳过（但不退出，等待 Mem0 恢复或依赖注入）
                await asyncio.sleep(LTM_WORKER_INTERVAL_SEC)
                continue

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
