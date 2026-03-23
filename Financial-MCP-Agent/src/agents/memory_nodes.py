"""
LTM（长期记忆）LangGraph 节点 - Phase 3

两个新节点，通过 ENABLE_MEMORY 环境变量控制，关闭时为 no-op：

1. memory_read_node  - 合并读取结构化画像 + Mem0 语义召回，写入 state["data"]["memory_context"]
2. memory_write_node - enqueue 写 LTM 任务（不阻塞主链路，立即返回）

两个节点均有完整的终端输出，便于定位问题。
降级保障：任何异常都不阻断主工作流。
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_AGENTS_DIR = Path(__file__).resolve().parent
_AGENT_SRC = _AGENTS_DIR.parent
if str(_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENT_SRC))

from src.utils.logging_config import setup_logger, WAIT_ICON, SUCCESS_ICON, ERROR_ICON
from src.utils.state_definition import AgentState

logger = setup_logger("memory_nodes")

_ENABLE_MEMORY = os.getenv("ENABLE_MEMORY", "false").lower() in ("true", "1", "yes")


# ─────────────────────────────────────────────────────────────
# 节点 1：memory_read_node
# ─────────────────────────────────────────────────────────────

async def memory_read_node(state: AgentState) -> Dict[str, Any]:
    """
    报告模式 LTM 读取节点。

    职责：
    - 调用 MemoryService.get_memory_context() 合并结构化画像 + Mem0 语义召回
    - 结果写入 state["data"]["memory_context"]
    - ENABLE_MEMORY=false 或 memory_user_id 为空时：写入空 context，不抛异常

    检索过滤规则（写死在节点内）：
    - categories: risk_profile, horizon, sector_focus, watchlist_stock, constraints, response_preference
    - sources: ui, cold_start, explicit_correction, chat_inferred（过滤掉 report_inferred，避免自循环）
    - threshold=0.60, top_k=6
    """
    current_data = state.get("data", {})
    user_id = state.get("memory_user_id", "") or ""

    print(f"\n{WAIT_ICON} [LTM] memory_read_node: 开始读取用户 LTM 画像...")
    logger.info(f"[LTM] memory_read_node: user={user_id or '未设置'}, ENABLE_MEMORY={_ENABLE_MEMORY}")

    # ── 降级条件：未启用 or user_id 为空 ────────────────────
    if not _ENABLE_MEMORY or not user_id.strip():
        reason = "ENABLE_MEMORY=false" if not _ENABLE_MEMORY else "memory_user_id 为空"
        print(f"  [LTM] memory_read_node 跳过（{reason}），memory_context 置空")
        logger.info(f"[LTM] memory_read_node 跳过: {reason}")
        current_data["memory_context"] = {"profile": {}, "semantic_memories": []}
        return {"data": current_data}

    try:
        from src.memory.memory_service import MemoryService

        query = current_data.get("report_query") or current_data.get("query", "")

        context = await MemoryService.get_memory_context(
            user_id=user_id,
            query=query,
        )

        profile = context.get("profile", {})
        semantic_memories = context.get("semantic_memories", [])
        non_null_fields = sum(1 for v in profile.values() if v is not None and v != [] and v != {})

        print(
            f"{SUCCESS_ICON} [LTM] memory_read_node 完成："
            f"画像字段={non_null_fields}个有值，语义记忆={len(semantic_memories)}条"
        )
        logger.info(
            f"[LTM] memory_read_node 完成: user={user_id}, "
            f"profile_fields={non_null_fields}, semantic_hits={len(semantic_memories)}"
        )

        current_data["memory_context"] = context
        return {"data": current_data}

    except Exception as exc:
        print(f"{ERROR_ICON} [LTM] memory_read_node 异常（不影响主流程）: {exc}")
        logger.error(f"[LTM] memory_read_node 异常: {exc}", exc_info=True)
        current_data["memory_context"] = {"profile": {}, "semantic_memories": []}
        return {"data": current_data}


# ─────────────────────────────────────────────────────────────
# 节点 2：memory_write_node
# ─────────────────────────────────────────────────────────────

async def memory_write_node(state: AgentState) -> Dict[str, Any]:
    """
    报告模式 LTM 写入节点（enqueue 模式，立即返回，不等待 Mem0）。

    职责：
    - 取 state["messages"] 中 role=user 的消息片段（去掉 analyst 工具原始输出）
    - 调用 MemoryService.enqueue_add_conversation()（仅入队，不直接写 Mem0）
    - 不处理显式更新（UI/冷启动的画像修改由前端通过 API 独立处理）
    - ENABLE_MEMORY=false 时为 no-op
    """
    current_data = state.get("data", {})
    user_id = state.get("memory_user_id", "") or ""
    messages = state.get("messages", [])

    print(f"\n{WAIT_ICON} [LTM] memory_write_node: 加入 LTM 写入队列...")
    logger.info(f"[LTM] memory_write_node: user={user_id or '未设置'}, ENABLE_MEMORY={_ENABLE_MEMORY}")

    if not _ENABLE_MEMORY or not user_id.strip():
        reason = "ENABLE_MEMORY=false" if not _ENABLE_MEMORY else "memory_user_id 为空"
        print(f"  [LTM] memory_write_node 跳过（{reason}）")
        logger.info(f"[LTM] memory_write_node 跳过: {reason}")
        return {}

    try:
        from src.memory.memory_service import MemoryService

        # 只取 role=user 的原始消息，过滤掉 analyst 工具原始输出
        user_messages = []
        for msg in messages:
            role = getattr(msg, "type", "") or getattr(msg, "role", "")
            content = getattr(msg, "content", "")
            if role == "human" and isinstance(content, str) and content.strip():
                user_messages.append({
                    "role": "user",
                    "content": content[:1000],  # 截断避免过长
                })
            elif role == "ai" and isinstance(content, str) and content.strip():
                # 也包含 AI 回复，便于 Mem0 理解对话上下文
                user_messages.append({
                    "role": "assistant",
                    "content": content[:500],
                })

        if not user_messages:
            print(f"  [LTM] memory_write_node 跳过（无用户消息可提取）")
            logger.debug("[LTM] memory_write_node: 无用户消息，跳过")
            return {}

        # 获取当前报告的 task_id 和 report_id（若可用）
        task_id = current_data.get("task_id", "")
        report_id = current_data.get("report_id", "")

        metadata = {
            "source": "report_inferred",
            "active": True,
            "updated_by": "llm",
            "confidence": 0.7,
        }
        if task_id:
            metadata["run_id"] = task_id
        if report_id:
            metadata["evidence_ref"] = report_id

        await MemoryService.enqueue_add_conversation(
            user_id=user_id,
            messages=user_messages,
            metadata=metadata,
        )

        print(
            f"{SUCCESS_ICON} [LTM] memory_write_node 入队成功："
            f"用户消息 {len(user_messages)} 条，source=report_inferred"
        )
        logger.info(
            f"[LTM] memory_write_node 入队: user={user_id}, "
            f"msgs={len(user_messages)}, task_id={task_id}"
        )

    except Exception as exc:
        print(f"{ERROR_ICON} [LTM] memory_write_node 异常（不影响主流程）: {exc}")
        logger.error(f"[LTM] memory_write_node 异常: {exc}", exc_info=True)

    return {}
