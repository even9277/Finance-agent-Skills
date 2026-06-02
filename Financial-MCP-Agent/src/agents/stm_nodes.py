"""
STM（短期记忆）节点模块 - Phase 2 新增

实现两个 LangGraph 工作流节点：
1. prepare_summary_context  — 汇总前：拼接 STM 上下文供 summary_agent 使用
2. maybe_summarize_state    — 汇总后：按阈值触发 state 压缩

触发阈值（满足任一即压缩）：
  - thread_meta["turn_count"] >= 10
  - thread_meta["token_estimate"] >= 6000

设计约束：
  - 两个节点只在 ENABLE_STM=true 时被插入工作流，否则完全不运行
  - 节点内部有详细的终端 print 输出，便于定位问题
  - 日志通过 setup_logger 写入，不使用 ExecutionLogger（对话模式专用）
  - 压缩后的消息在 DB messages 表打标（由 chat_service 负责），此处只更新 state
"""

import os
import time
from datetime import datetime
from typing import Any, Dict

from src.prompts.memory import (
    SUMMARIZE_CONVERSATION_PROMPT,
    TOOL_DIGEST_PROMPT,
)
from src.utils.logging_config import setup_logger, WAIT_ICON, SUCCESS_ICON, ERROR_ICON
from src.utils.state_definition import AgentState

logger = setup_logger(__name__)

# ─────────────────────────────────────────────────────────────
# 压缩触发阈值（与开发计划一致）
# ─────────────────────────────────────────────────────────────
STM_TURN_THRESHOLD = 10       # 轮次阈值
STM_TOKEN_THRESHOLD = 6000    # token 估算阈值
STM_KEEP_RECENT = 4           # 压缩后保留最近 N 条原始消息

# ─────────────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """简单 token 估算：中文约 1.5 字/token，英文约 4 字符/token。"""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def _get_llm():
    """懒加载 LLM 客户端，复用 agent 环境变量配置。"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", ""),
        base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
        temperature=0.3,
        max_tokens=600,
    )


# ─────────────────────────────────────────────────────────────
# 节点 1：prepare_summary_context
# ─────────────────────────────────────────────────────────────
async def prepare_summary_context(state: AgentState) -> Dict[str, Any]:
    """
    汇总前节点：将三段式 STM 上下文拼装为 summary_agent 的输入。

    组装内容：
    1. state["running_summary"]         — 早期对话摘要（若存在）
    2. state["messages"][-N:]           — 最近 N 条原始消息
    3. state["recent_tool_digest"]      — analyst 工具精炼结论
    4. state["data"]["memory_context"]  — Mem0 LTM 召回（Phase 3，此阶段为空）

    拼装结果写入 state["data"]["summary_input_context"]
    """
    print(f"\n{WAIT_ICON} [STM] prepare_summary_context: 开始拼装汇总上下文...")
    logger.info("[STM] prepare_summary_context: 开始拼装汇总上下文")

    current_data = state.get("data", {})
    messages = state.get("messages", [])
    running_summary = state.get("running_summary", "")
    recent_tool_digest = state.get("recent_tool_digest", "")
    memory_context = state.get("memory_context", {})

    # 取最近 12 条消息的文本内容（不包含 tool 消息）
    recent_msgs_text = ""
    recent_messages = list(messages)[-12:]
    for msg in recent_messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            recent_msgs_text += f"[{role}]: {content[:500]}\n"

    # 拼装汇总上下文
    context_parts = []

    if running_summary.strip():
        context_parts.append(f"【早期对话摘要】\n{running_summary}")

    if recent_msgs_text.strip():
        context_parts.append(f"【近期对话记录】\n{recent_msgs_text}")

    if recent_tool_digest.strip():
        context_parts.append(f"【分析工具精炼结论】\n{recent_tool_digest}")

    if memory_context:
        # Phase 3 激活时注入 LTM，此阶段为空
        ltm_text = str(memory_context)
        if ltm_text and ltm_text != "{}":
            context_parts.append(f"【用户长期记忆画像（仅参考，不覆盖实时数据）】\n{ltm_text}")

    summary_input_context = "\n\n".join(context_parts) if context_parts else ""

    print(f"{SUCCESS_ICON} [STM] prepare_summary_context 完成，上下文长度={len(summary_input_context)} 字符")
    logger.info(
        f"[STM] prepare_summary_context 完成："
        f"running_summary={len(running_summary)}字, "
        f"recent_msgs={len(recent_messages)}条, "
        f"tool_digest={len(recent_tool_digest)}字, "
        f"ltm_context={'有' if memory_context else '空'}"
    )

    current_data["summary_input_context"] = summary_input_context
    return {"data": current_data}


# ─────────────────────────────────────────────────────────────
# 节点 2：maybe_summarize_state
# ─────────────────────────────────────────────────────────────
async def maybe_summarize_state(state: AgentState) -> Dict[str, Any]:
    """
    汇总后节点：按阈值触发 state 压缩（对话报告 STM 管理）。

    触发条件（满足任一）：
    - thread_meta["turn_count"] >= STM_TURN_THRESHOLD（10）
    - thread_meta["token_estimate"] >= STM_TOKEN_THRESHOLD（6000）

    压缩逻辑：
    - 调用 LLM 对 messages[:-STM_KEEP_RECENT] + 旧 running_summary 生成新 running_summary
    - 压缩后在 LangGraph state 中保留最近 STM_KEEP_RECENT 条原始消息
    - 更新 thread_meta（last_compress_at、turn_count 重置）
    """
    print(f"\n{WAIT_ICON} [STM] maybe_summarize_state: 检查是否需要压缩 state...")
    logger.info("[STM] maybe_summarize_state: 检查压缩阈值")

    current_data = state.get("data", {})
    messages = list(state.get("messages", []))
    thread_meta = state.get("thread_meta", {}) or {}
    running_summary = state.get("running_summary", "") or ""

    turn_count = thread_meta.get("turn_count", 0)
    token_estimate = thread_meta.get("token_estimate", 0)

    # 动态估算当前 token 总量
    all_text = " ".join(
        getattr(m, "content", "") for m in messages if isinstance(getattr(m, "content", ""), str)
    )
    current_token_estimate = _estimate_tokens(all_text) + _estimate_tokens(running_summary)

    should_compress = (
        turn_count >= STM_TURN_THRESHOLD or
        current_token_estimate >= STM_TOKEN_THRESHOLD
    )

    print(
        f"  turn_count={turn_count} (阈值={STM_TURN_THRESHOLD}), "
        f"token_estimate≈{current_token_estimate} (阈值={STM_TOKEN_THRESHOLD}), "
        f"触发压缩={should_compress}"
    )
    logger.info(
        f"[STM] turn_count={turn_count}, token_estimate≈{current_token_estimate}, "
        f"should_compress={should_compress}"
    )

    if not should_compress:
        # 只更新 token 估算，不压缩
        thread_meta["token_estimate"] = current_token_estimate
        return {
            "thread_meta": thread_meta,
            "running_summary": running_summary,
        }

    # ── 触发压缩 ───────────────────────────────────────────────
    print(f"{WAIT_ICON} [STM] 触发 state 压缩，保留最近 {STM_KEEP_RECENT} 条消息...")
    logger.info(f"[STM] 触发压缩，消息总数={len(messages)}，保留最近 {STM_KEEP_RECENT} 条")

    compress_start = time.time()
    try:
        llm = _get_llm()

        # 取待压缩的消息（除保留的最近 N 条外的其余消息）
        msgs_to_compress = messages[:-STM_KEEP_RECENT] if len(messages) > STM_KEEP_RECENT else messages

        compress_text_parts = []
        if running_summary.strip():
            compress_text_parts.append(f"【已有摘要】\n{running_summary}")

        for msg in msgs_to_compress:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                compress_text_parts.append(f"[{role}]: {content[:800]}")

        compress_input = "\n".join(compress_text_parts)

        from langchain_core.messages import HumanMessage, SystemMessage
        compress_messages = [
            SystemMessage(content=SUMMARIZE_CONVERSATION_PROMPT),
            HumanMessage(content=f"请压缩以下对话历史：\n\n{compress_input}")
        ]
        response = await llm.ainvoke(compress_messages)
        new_running_summary = response.content.strip()

        compress_elapsed = time.time() - compress_start
        print(
            f"{SUCCESS_ICON} [STM] 压缩完成，"
            f"新摘要={len(new_running_summary)}字，耗时={compress_elapsed:.1f}s"
        )
        logger.info(
            f"[STM] 压缩完成：原消息{len(msgs_to_compress)}条 → 摘要{len(new_running_summary)}字，"
            f"耗时={compress_elapsed:.1f}s"
        )

        # 更新 thread_meta
        thread_meta.update({
            "turn_count": 0,
            "token_estimate": _estimate_tokens(new_running_summary),
            "last_compress_at": datetime.utcnow().isoformat(),
            "compress_count": thread_meta.get("compress_count", 0) + 1,
        })

        return {
            "running_summary": new_running_summary,
            "thread_meta": thread_meta,
        }

    except Exception as exc:
        logger.error(f"[STM] 压缩失败（不影响主流程）: {exc}", exc_info=True)
        print(f"{ERROR_ICON} [STM] 压缩失败（不影响主流程）: {exc}")
        # 压缩失败不阻断主流程
        thread_meta["token_estimate"] = current_token_estimate
        return {
            "thread_meta": thread_meta,
            "running_summary": running_summary,
        }
