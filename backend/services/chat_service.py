"""
对话服务层 - Phase 3 扩展（LTM 集成）
=============================
Phase 1 功能保持不变：
  - get_or_create_session / get_sessions / get_session_messages / delete_session / rename_session

Phase 2 新增 STM（短期记忆）功能：
  - compress_if_needed        : 对话模式 STM 压缩（ENABLE_STM=true 时触发）
  - stream_chat_single_turn   : 流式生成器，逐 token yield，供 WebSocket 路由使用

Phase 3 新增 LTM（长期记忆）集成：
  - 每次对话前读取用户画像，注入 system prompt（ENABLE_MEMORY=true 时）
  - 对话后非阻塞触发 maybe_update_ltm_from_chat，抽取偏好写入 ltm_write_tasks
  - 对话中用户主动纠正时，解析 LLM 输出的结构化 action，调用 update_profile_and_enqueue

STM/LTM 分工：
  - STM：对话模式专用，存 sessions.running_summary + messages 表，独立于 LangGraph
  - LTM：跨会话画像，存 user_invest_profiles（权威）+ Mem0（语义增强）
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Message, Session, SessionSummary, User
from backend.config import settings
from backend.services import memory_service as _memory_svc
from backend.services.chat_hitl_pending import pop_pending_skill_confirm, set_pending_skill_confirm
from backend.services.chat_route_runtime import (
    enrich_context_window,
    get_runtime_route_state,
    record_route_runtime_state,
    seed_route_runtime_from_summary_payload,
)
from backend.services.entity_resolver import resolve_entity
from backend.services.working_state import get_working_state, upsert_active_entity
from backend.services.stm_context_service import (
    refresh_session_context_metrics,
)
from backend.services.stm_summary_runtime import (
    apply_route_entity_hot_update,
    format_answer_policy_context,
    format_route_active_entities_context,
    maybe_run_preflight_summary_compaction,
    resolve_session_rolling_payload,
    run_summary_compaction,
    should_run_preflight_summary_compaction,
)
from backend.services.token_counter import count_message_tokens

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger  # noqa: E402
from src.agents.skill_executor_node import execute_skill  # noqa: E402
from src.agents.query_rewriter import (  # noqa: E402
    _load_skill_doc_sections,
    rewrite_for_fallback,
    rewrite_for_sop,
    rewrite_for_tushare,
    rewrite_for_tushare_v2,
)
from src.agents.synthesis.synthesize_fallback import build_fallback_synthesis_prompt  # noqa: E402
from src.agents.synthesis.synthesize_sop import build_sop_synthesis_prompt  # noqa: E402
from src.agents.synthesis.synthesize_tushare import build_tushare_synthesis_prompt  # noqa: E402
from src.agents.entity_resolver_v2 import resolve_authoritative_entity  # noqa: E402
from src.agents.constraints_extractor import extract_constraints  # noqa: E402
from src.agents.reply_preference_extractor import extract_reply_preference  # noqa: E402
from src.agents.rewrite_context import RewriteContextPacket  # noqa: E402
from src.agents.skill_runner_v2 import run_sop_v2_pipeline, run_tushare_v2_pipeline  # noqa: E402
from src.agents.skill_router_node import (  # noqa: E402
    _build_executor_route_trace,
    registry_execution_policy_for_skill,
    route_chat_skill,
    rewrite_query_for_skill,
    skill_route_decision_from_dict,
    user_explicit_sop_decision,
)
from src.agents.tushare_plan_executor import execute_tushare_plan  # noqa: E402
from src.skills.skill_registry import get_skill_registry  # noqa: E402
from src.tools.skill_trace import (  # noqa: E402
    log_compaction_enqueue,
    log_degrade_transition,
    log_memory_enqueue,
    log_model_stage,
    log_reply_completed,
    log_router_decision,
    log_tool_plan,
    log_trace_finished,
    log_trace_started,
    new_trace_id,
    skill_trace_context,
    trace_span,
)
from src.tools.tushare_client import TushareClient, configure_tushare_client_factory  # noqa: E402

logger = setup_logger("chat_service", log_dir=str(_AGENT_ROOT / "logs"))

# ─────────────────────────────────────────────────────────────
# 常量配置
# ─────────────────────────────────────────────────────────────
_RECENT_MSG_LIMIT = int(settings.stm_keep_recent) + 2  # 保留最近 N+2 条消息作为上下文
_STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES = int(
    settings.stm_fallback_min_uncompressed_messages
)
_CHAT_STREAM_CHUNK_SIZE = 48
_skill_runtime_checked = False
_STM_OVERFLOW_ERROR_PATTERNS = (
    "context length",
    "context window",
    "maximum context",
    "max context",
    "too many tokens",
    "token limit",
    "prompt is too long",
    "context too long",
)
_ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE = 500

# ─────────────────────────────────────────────────────────────
# Phase 3：画像 action 规范化（修复“模型输出枚举混乱/不在范围内”）
# 目标：将不稳定的 LLM 输出/用户输入，映射到系统支持的有限枚举，非法值直接拒绝写入，避免污染画像。
# ─────────────────────────────────────────────────────────────

# 与前端 `RiskProfileCard.vue`/产品文案保持一致的风险枚举（允许别名映射）
_RISK_LEVEL_ALLOWED = {
    "conservative",
    "moderate",
    "balanced_conservative",
    "balanced",
    "aggressive",
    "speculative",
    "very_aggressive",
}

_HORIZON_ALLOWED = {"ultra_short", "short", "swing", "long"}
_RESPONSE_PREF_ALLOWED = {"concise", "balanced", "detailed", "risk_first"}

# 前端内置板块（`SectorTagSelector.vue`）的规范名（用于同义归一）
_SECTOR_CANONICAL = [
    "科技/半导体", "消费/白酒", "金融/银行", "医疗/医药",
    "能源/煤炭", "新能源/电动车", "红利/央国企", "黄金/贵金属",
    "AI/大模型", "房地产", "军工", "农业",
]

_SECTOR_SYNONYMS: dict[str, str] = {
    # 常见简称 → 规范名
    "半导体": "科技/半导体",
    "芯片": "科技/半导体",
    "科技": "科技/半导体",
    "黄金": "黄金/贵金属",
    "贵金属": "黄金/贵金属",
    "红利": "红利/央国企",
    "高股息": "红利/央国企",
    "央国企": "红利/央国企",
    "大模型": "AI/大模型",
    "AI": "AI/大模型",
    "人工智能": "AI/大模型",
    "新能源": "新能源/电动车",
    "电动车": "新能源/电动车",
    "白酒": "消费/白酒",
    "消费": "消费/白酒",
    "银行": "金融/银行",
    "金融": "金融/银行",
    "医药": "医疗/医药",
    "医疗": "医疗/医药",
}

_RISK_LEVEL_SYNONYMS: dict[str, str] = {
    # 中文/常见别名 → 枚举
    "保守": "conservative",
    "稳健": "balanced_conservative",
    "偏稳健": "balanced_conservative",
    "中性": "balanced",
    "平衡": "balanced",
    "进取": "aggressive",
    "激进": "very_aggressive",
    "超激进": "very_aggressive",
    # 兼容历史枚举
    "moderate": "balanced_conservative",
    "speculative": "very_aggressive",
}

_HORIZON_SYNONYMS: dict[str, str] = {
    "超短": "ultra_short",
    "超短线": "ultra_short",
    "短线": "short",
    "短期": "short",
    "波段": "swing",
    "中期": "swing",
    "中长线": "long",
    "长线": "long",
    "长期": "long",
}

_RESPONSE_PREF_SYNONYMS: dict[str, str] = {
    "简洁": "concise",
    "精简": "concise",
    "均衡": "balanced",
    "详细": "detailed",
    "先讲风险": "risk_first",
    "风险优先": "risk_first",
    "先风险后机会": "risk_first",
}


def _normalize_sectors(value) -> list[str] | None:
    if value is None:
        return None

    raw_list: list[str] = []
    if isinstance(value, str):
        # 允许模型输出 "半导体, 黄金" 或 "半导体、黄金" 这种形式
        separators = [",", "，", "、", ";", "；", "|", "\n"]
        tmp = value
        for sep in separators:
            tmp = tmp.replace(sep, ",")
        raw_list = [x.strip() for x in tmp.split(",") if x.strip()]
    elif isinstance(value, list):
        raw_list = [str(x).strip() for x in value if str(x).strip()]
    else:
        return None

    normalized: list[str] = []
    for item in raw_list:
        # 若直接是规范名则保留
        if item in _SECTOR_CANONICAL:
            norm = item
        else:
            norm = _SECTOR_SYNONYMS.get(item, item)
            # 进一步：有些模型会输出 "科技/半导体/芯片" 这种，取前两段
            if isinstance(norm, str) and norm.count("/") >= 2:
                parts = [p for p in norm.split("/") if p]
                norm = "/".join(parts[:2])

        if norm and norm not in normalized:
            normalized.append(norm)

    # 限制长度，避免异常污染
    return normalized[:20]


def _normalize_profile_action(field: str, value):
    """
    规范化 action 值：
    - risk_level / investment_horizon / response_pref：必须映射到允许枚举，否则拒绝写入
    - sectors：做去重/清洗/同义归一，返回 list[str]
    返回：(field, normalized_value) 或 None（表示无效/不写入）
    """
    if not field:
        return None
    field = str(field).strip()

    if field == "risk_level":
        if value is None:
            return None
        v = str(value).strip()
        v = _RISK_LEVEL_SYNONYMS.get(v, v)
        if v not in _RISK_LEVEL_ALLOWED:
            return None
        return field, v

    if field == "investment_horizon":
        if value is None:
            return None
        v = str(value).strip()
        v = _HORIZON_SYNONYMS.get(v, v)
        if v not in _HORIZON_ALLOWED:
            return None
        return field, v

    if field == "response_pref":
        if value is None:
            return None
        v = str(value).strip()
        v = _RESPONSE_PREF_SYNONYMS.get(v, v)
        if v not in _RESPONSE_PREF_ALLOWED:
            return None
        return field, v

    if field == "sectors":
        sectors = _normalize_sectors(value)
        if sectors is None:
            return None
        return field, sectors

    return None

# 对话模式基础系统 Prompt（含 Phase 3 画像更新约定）
_CHAT_SYSTEM_PROMPT = """你是一位专业的A股投研助手，具备深厚的金融分析能力。
你的职责：
- 回答用户关于A股、基本面、技术面、估值的问题
- 提供专业、客观的投资参考意见
- 若需要完整深度报告，建议用户切换到"调研报告模式"

注意事项：
- 回答简洁专业，重要数据加粗标注
- 不保证投资收益，所有建议仅供参考
- 用中文回答

【用户画像更新（非常重要，请严格执行）】
当你识别到用户在对话中表达了「长期偏好」或「希望保存到画像」的信息时，
除了正常回答以外，必须在回复末尾追加一个 JSON 动作块，格式如下：

<action>{"action": "update_profile", "field": "...", "value": ...}</action>

要求：
1. action 必须是 "update_profile"
2. field 只能取以下之一：
   - "risk_level"           风险偏好（只允许以下枚举）：
                            conservative / balanced_conservative / balanced / aggressive / very_aggressive
   - "sectors"             关注板块：字符串数组，例如 ["半导体","黄金","新能源"]
   - "investment_horizon"  投资周期：ultra_short / short / swing / long
   - "response_pref"       回答偏好：concise / balanced / detailed / risk_first
3. value：
   - risk_level / investment_horizon / response_pref：使用上面约定的英文枚举值
   - sectors：使用中文板块名列表，例如 ["半导体","黄金"]
4. 除非用户只是问一句行情、不会改变长期偏好，否则尽量输出 action，保证画像能被及时更新。

【示例（非常关键，请模仿执行）】
示例1：
用户说："我风险承受能力比较弱，以稳健为主，请帮我改成稳健型。"
→ 你的回复结尾必须包含：
<action>{"action": "update_profile", "field": "risk_level", "value": "balanced_conservative"}</action>

示例2：
用户说："我主要长期关注半导体和黄金板块，请记到我的画像里。"
→ 你的回复结尾必须包含：
<action>{"action": "update_profile", "field": "sectors", "value": ["半导体","黄金"]}</action>

示例3：
用户说："我更关心风险，回答时先讲风险再讲机会。"
→ 你的回复结尾必须包含：
<action>{"action": "update_profile", "field": "response_pref", "value": "risk_first"}</action>

注意：上述 <action> JSON 片段必须是合法 JSON，不要添加注释或多余文字。
该片段之外的内容为正常中文回答。"""

# LTM 记忆画像注入 Prompt 模板（与 summary_agent 中的格式保持一致）
_MEMORY_CONTEXT_PROMPT_TEMPLATE = """
【用户投资画像（参考辅助，不覆盖实时数据）】
{profile_text}

补充历史偏好线索（置信度低于上方结构化字段）：
{semantic_text}

【重要约束】
1. 投资建议必须以当前实时分析数据为准，画像仅供个性化调整语气和侧重点
2. 若偏好与分析结论冲突，必须如实说明，不得迎合偏好
"""

# LTM 触发条件
_MIN_LTM_INTERVAL_SEC = int(os.getenv("MIN_LTM_INTERVAL", "300"))  # 最小间隔 300s
_LTM_TRIGGER_MSG_COUNT = 5  # 未处理 user 消息数阈值

def _get_llm():
    """懒加载 LLM 客户端（复用 agent 环境变量）。"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        openai_api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", ""),
        openai_api_base=os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
        temperature=0.7,
    )
def _profile_to_summary(profile: dict) -> str:
    if not profile:
        return ""

    summary_lines: list[str] = []
    for label, key in (
        ("风险偏好", "risk_level"),
        ("投资周期", "investment_horizon"),
        ("回答偏好", "response_pref"),
    ):
        value = profile.get(key)
        if value:
            summary_lines.append(f"{label}: {value}")

    sectors = profile.get("sectors") or []
    if sectors:
        summary_lines.append(f"关注板块: {', '.join(str(item) for item in sectors)}")

    return "\n".join(summary_lines)


def _profile_to_route_summary(profile: dict) -> str:
    if not profile:
        return ""

    summary_lines: list[str] = []
    for label, key in (
        ("风险偏好", "risk_level"),
        ("投资周期", "investment_horizon"),
        ("回答偏好", "response_pref"),
    ):
        value = profile.get(key)
        if value:
            summary_lines.append(f"{label}: {value}")

    return "\n".join(summary_lines)


def _trace_query_summary(text: str, limit: int = 120) -> str:
    summary = (text or "").strip().replace("\n", " ")
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3] + "..."


async def _prepare_chat_preflight_inputs(
    db: AsyncSession,
    session: Session,
    *,
    user_id: str,
    user_message: str,
) -> tuple[dict, str]:
    memory_profile, memory_system_prompt = await _load_memory_context_for_chat(
        db,
        user_id,
        user_message,
    )
    del session
    return memory_profile, memory_system_prompt


async def _run_chat_preflight_compaction(
    db: AsyncSession,
    session: Session,
    *,
    user_message: str,
    user_message_id: int,
    memory_system_prompt: str,
    trigger: str,
    stream_status_emitter: Any | None = None,
) -> None:
    if not settings.enable_stm or not settings.stm_summary_preflight_enabled:
        return

    await maybe_run_preflight_summary_compaction(
        db=db,
        session=session,
        pending_user_message=user_message,
        system_prompt_text=_CHAT_SYSTEM_PROMPT,
        memory_prompt_text=memory_system_prompt,
        exclude_message_ids={int(user_message_id)},
        trigger=trigger,
        stream_status_emitter=stream_status_emitter,
    )
    await db.refresh(session)


def _trace_root_metrics(skill_trace: dict | None) -> dict[str, object]:
    trace = skill_trace or {}
    executor = trace.get("executor") if isinstance(trace.get("executor"), dict) else {}
    metrics = {
        "route_confidence": round(float(trace.get("confidence") or 0.0), 4),
        "evidence_ok": bool(executor.get("evidence_ok", False)),
        "tool_batch_size": int(executor.get("tool_batch_size") or 0),
        "tool_failure_rate": float(executor.get("tool_failure_rate") or 0.0),
        "p95_latency": float(executor.get("p95_latency") or 0.0),
        "degrade_stage": str(executor.get("degrade_stage") or "none"),
        "policy_violation_count": int(executor.get("policy_violation_count") or 0),
    }
    return metrics


def _trace_root_payload(
    *,
    final_status: str,
    selected_skill_family: str,
    selected_skill: str,
    skill_name: str | None,
    analysis_mode: str,
    execution_policy: str,
    skill_trace: dict | None,
) -> dict[str, object]:
    executor = (skill_trace or {}).get("executor") if isinstance((skill_trace or {}).get("executor"), dict) else {}
    return {
        "final_status": final_status,
        "reply_mode": executor.get("reply_mode") or ("fallback" if selected_skill == "fallback" else "skill"),
        "final_selected_skill_family": selected_skill_family,
        "final_selected_skill": selected_skill,
        "final_skill_name": skill_name,
        "selected_skill_family": selected_skill_family,
        "selected_skill": selected_skill,
        "skill_name": skill_name,
        "analysis_mode": analysis_mode,
        "execution_policy": execution_policy,
        "degrade_stage_final": executor.get("degrade_stage"),
        "evidence_ok_final": executor.get("evidence_ok"),
        "claim_count_final": len(executor.get("claims") or []),
    }


def _trace_root_refs(skill_trace: dict | None) -> dict[str, object]:
    executor = (skill_trace or {}).get("executor") if isinstance((skill_trace or {}).get("executor"), dict) else {}
    return {
        "prompt_ref": executor.get("prompt_ref"),
        "reply_ref": executor.get("reply_ref"),
        "claim_ref": executor.get("claim_ref"),
        "payload_refs": executor.get("payload_refs") or [],
    }


class InvalidSopSkillError(ValueError):
    """Raised when the user explicitly selects an unknown SOP skill."""


def _ensure_skill_runtime_ready() -> None:
    global _skill_runtime_checked
    if _skill_runtime_checked:
        return

    try:
        get_skill_registry(refresh=True)
    except Exception as exc:
        logger.warning("[chat-skill] skill registry init failed: %s", exc, exc_info=True)

    configure_tushare_client_factory(
        lambda: TushareClient(token=settings.tushare_token or "")
    )
    _skill_runtime_checked = True


def normalize_requested_sop_skill_id(sop_skill_id: str | None) -> str | None:
    normalized = str(sop_skill_id or "").strip()
    return normalized or None


def validate_requested_sop_skill_id(sop_skill_id: str | None) -> str | None:
    normalized = normalize_requested_sop_skill_id(sop_skill_id)
    if normalized is None:
        return None

    _ensure_skill_runtime_ready()
    if user_explicit_sop_decision(normalized) is None:
        raise InvalidSopSkillError(f"无效的 sop_skill_id: {normalized}")
    return normalized


def list_discoverable_sop_skills() -> list[dict[str, str]]:
    _ensure_skill_runtime_ready()
    items: list[dict[str, str]] = []
    for skill in get_skill_registry().discoverable_sop_skills():
        items.append(
            {
                "name": skill.name,
                "official_name": str(skill.official_name or ""),
                "description": str(skill.description or ""),
                "execution_mode": registry_execution_policy_for_skill(skill.name),
            }
        )
    return items


async def _load_memory_context_for_chat(
    db: AsyncSession,
    user_id: str,
    user_message: str,
) -> tuple[dict, str]:
    memory_profile = {}
    memory_system_prompt = ""
    if not settings.enable_memory or not user_id:
        with trace_span(
            "memory_read",
            stage="memory",
            data={
                "memory_enabled": bool(settings.enable_memory),
                "enqueue_skipped_reason": "memory_disabled" if not settings.enable_memory else "missing_user_id",
                "user_message_summary": _trace_query_summary(user_message, limit=80),
            },
        ):
            pass
        return memory_profile, memory_system_prompt

    started = time.perf_counter()
    with trace_span(
        "memory_read",
        stage="memory",
        data={
            "memory_enabled": True,
            "user_message_summary": _trace_query_summary(user_message, limit=80),
        },
    ):
        try:
            ctx = await asyncio.wait_for(
                _memory_svc.get_memory_context_for_chat(user_id, user_message, db),
                timeout=max(1, int(settings.memory_context_timeout_sec)),
            )
            memory_profile = ctx.get("profile", {})
            semantic_memories = ctx.get("semantic_memories", [])
            memory_system_prompt = _build_memory_system_prompt(memory_profile, semantic_memories)
            if memory_system_prompt:
                print(f"[LTM-chat] 注入用户画像到对话上下文 (user={user_id[:8]}...)")
                logger.info(
                    f"[LTM-chat] 注入 memory_context: user={user_id}, len={len(memory_system_prompt)}"
                )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            if elapsed_ms >= 1500:
                logger.warning(
                    "[LTM-chat] memory_context slow: user=%s elapsed_ms=%s",
                    user_id,
                    elapsed_ms,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "[LTM-chat] memory_context timeout: user=%s timeout_sec=%s",
                user_id,
                settings.memory_context_timeout_sec,
            )
        except Exception as exc:
            logger.warning(f"[LTM-chat] 读取画像失败（不影响对话）: {exc}")
    return memory_profile, memory_system_prompt


async def _build_skill_route_context(
    db: AsyncSession,
    session: Session,
    *,
    exclude_message_id: int | None = None,
    route_slice_text: str = "",
) -> str:
    """构建路由"对话快照"：route slice + 最近对话原文。

    用户消息保留全文，助手消息截断到 _ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE 字符。
    route slice 只承担主语补全、指代消解、follow-up 实体继承，不再注入全文摘要。
    """
    parts: list[str] = []

    if settings.enable_stm and route_slice_text:
        parts.append(route_slice_text)

    if settings.enable_stm:
        stmt = select(Message).where(
            Message.session_id == session.id,
            Message.is_compressed == False,  # noqa: E712
        )
    else:
        stmt = select(Message).where(Message.session_id == session.id)

    if exclude_message_id is not None:
        stmt = stmt.where(Message.id != exclude_message_id)

    stmt = stmt.order_by(Message.created_at.desc()).limit(_RECENT_MSG_LIMIT + 1)
    history_result = await db.execute(stmt)
    recent_messages = list(reversed(history_result.scalars().all()))

    if recent_messages:
        dialogue_lines = []
        truncate_len = _ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE
        for msg in recent_messages:
            role = "用户" if msg.role == "user" else "助手"
            content = (msg.content or "").strip()
            if msg.role == "assistant" and len(content) > truncate_len:
                content = content[:truncate_len] + "…"
            dialogue_lines.append(f"{role}: {content}")
        parts.append("【最近对话记录】\n" + "\n".join(dialogue_lines))

    return "\n\n".join(parts)


def _resolve_session_summary_contexts(session: Session) -> tuple[dict[str, Any], str, str]:
    if not settings.enable_stm:
        return {}, "", ""
    payload = resolve_session_rolling_payload(session)
    route_slice_text = format_route_active_entities_context(payload)
    answer_policy_context = format_answer_policy_context(payload)
    return payload, route_slice_text, answer_policy_context


def _resolver_hint_to_prompt_block(resolver_hint: dict[str, Any] | None) -> str:
    hint = dict(resolver_hint or {})
    if not hint:
        return ""
    display_name = str(hint.get("display_name") or "").strip() or "unknown"
    asset_type = str(hint.get("asset_type") or "").strip() or "unknown"
    symbol = str(hint.get("symbol") or "").strip() or "unknown"
    confidence = float(hint.get("confidence") or 0.0)
    stage = str(hint.get("resolver_stage") or "").strip() or "unknown"
    return (
        "【已解析实体提示】\n"
        f"display_name={display_name}\n"
        f"asset_type={asset_type}\n"
        f"symbol={symbol}\n"
        f"confidence={confidence:.4f}\n"
        f"resolver_stage={stage}"
    )


def _resolver_hint_payload(resolution: Any) -> dict[str, Any] | None:
    if resolution is None or not getattr(resolution, "ok", False):
        return None
    confidence = float(getattr(resolution, "confidence", 0.0) or 0.0)
    if confidence < 0.75:
        return None
    payload = {
        "display_name": str(getattr(resolution, "display_name", "") or "").strip(),
        "asset_type": str(getattr(resolution, "asset_type", "") or "").strip(),
        "symbol": str(getattr(resolution, "symbol", "") or "").strip(),
        "confidence": confidence,
        "resolver_stage": str(getattr(resolution, "resolver_stage", "") or "").strip(),
        "resolver_source": str(getattr(resolution, "resolver_source", "") or "").strip(),
    }
    if not payload["display_name"] and not payload["symbol"]:
        return None
    return payload


async def _resolve_entity_hint_for_route(session: Session, user_message: str) -> dict[str, Any] | None:
    runtime_state = get_runtime_route_state(session.id)
    summary_active_symbols: list[str] | None = None
    if runtime_state is None and settings.enable_stm:
        payload = resolve_session_rolling_payload(session)
        runtime_state = seed_route_runtime_from_summary_payload(payload, runtime_state)
        route_slice = payload.get("active_entities") if isinstance(payload, dict) else None
        if isinstance(route_slice, list):
            summary_active_symbols = [
                str(item.get("canonical_id") or "").strip()
                for item in route_slice
                if isinstance(item, dict) and str(item.get("canonical_id") or "").strip()
            ] or None
    session_symbols: list[str] | None = None
    if runtime_state is not None and str(runtime_state.active_entity_id or "").strip():
        session_symbols = [str(runtime_state.active_entity_id or "").strip()]
    try:
        resolution = await resolve_entity(
            user_message,
            session_symbols=session_symbols,
            summary_active_symbols=summary_active_symbols,
        )
    except Exception as exc:
        logger.warning("[chat-skill] resolve_entity hint failed (non-fatal): %s", exc)
        return None
    return _resolver_hint_payload(resolution)


def _executor_qualifies_for_evidence_retry(executor_trace: dict | None) -> bool:
    if not executor_trace:
        return False
    if executor_trace.get("evidence_ok"):
        return False
    if str(executor_trace.get("reply_mode") or "") != "evidence-missing":
        return False
    if str(executor_trace.get("failure_code") or "") == "skill_disabled":
        return False
    return True


_EXPLICIT_SKILL_INTENT_RE = re.compile(
    r"(使用\s*skills?|用\s*skills?|走\s*skills?|调用\s*skills?|"
    r"请\s*用\s*技能|使用\s*技能|必须\s*用\s*技能|financial[-\s]?sop|"
    r"工具\s*分析|结构化\s*技能|走\s*工具)",
    re.IGNORECASE,
)


def _user_explicit_skill_intent(user_message: str) -> bool:
    """用户明确要求走技能/工具链路（与路由是否命中无关）。"""
    return bool(_EXPLICIT_SKILL_INTENT_RE.search(user_message or ""))


def _build_broad_skill_confirm_options() -> list[dict[str, Any]]:
    """fallback 或未命中时，列出可选 SOP 技能 + tushare + 纯对话。"""
    opts: list[dict[str, Any]] = []
    skills = get_skill_registry().discoverable_sop_skills()
    for i, s in enumerate(skills[:14]):
        label = (s.official_name or s.name or "").strip() or s.name
        desc = (s.description or "")[:48]
        if desc:
            label = f"{label} — {desc}"
        opts.append(
            {
                "key": s.name,
                "label": label,
                "recommended": i == 0,
            }
        )
    opts.append(
        {
            "key": "tushare-data",
            "label": "实时行情 / Tushare 数据拉取",
            "recommended": False,
        }
    )
    opts.append(
        {
            "key": "fallback",
            "label": "不要技能链路，直接 AI 回答",
            "recommended": False,
        }
    )
    return opts


def _should_offer_skill_hitl(route: Any) -> bool:
    if not settings.enable_skill_route_hitl:
        return False
    thr = float(settings.skill_route_hitl_confidence_threshold)
    if float(route.confidence or 0.0) >= thr:
        return False
    if str(route.selected_skill or "") == "fallback":
        return False
    return True


def _sop_execution_policy_for_name(skill_name: str) -> str:
    return registry_execution_policy_for_skill(skill_name)


def _resolve_sop_skill_id(route_trace: dict[str, Any], decision: Any) -> str:
    """Concrete SOP skill id (e.g. stock-first-pass), not skill family (financial-sop)."""
    skill_name = str((route_trace or {}).get("skill_name") or "").strip()
    if skill_name:
        return skill_name
    return str(getattr(decision, "skill_id", None) or "").strip()


def _build_skill_confirm_options(route: Any) -> list[dict[str, Any]]:
    opts: list[dict[str, Any]] = []
    fam = str(route.selected_skill_family or "")
    if fam == "financial-sop" and route.skill_name:
        opts.append(
            {
                "key": str(route.skill_name),
                "label": f"按推荐执行技能：{route.skill_name}",
                "recommended": True,
            }
        )
    elif str(route.selected_skill) == "tushare-data":
        opts.append(
            {
                "key": "tushare-data",
                "label": "使用实时金融数据（Tushare）",
                "recommended": True,
            }
        )
    else:
        sk = str(route.selected_skill or "")
        if sk and sk != "fallback":
            opts.append({"key": sk, "label": f"继续：{sk}", "recommended": True})
    opts.append(
        {
            "key": "fallback",
            "label": "直接由 AI 回答（不强制工具链路）",
            "recommended": False,
        }
    )
    return opts


def _build_skill_confirm_options_from_trace(route_trace: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [str(item) for item in (route_trace.get("confirm_candidates") or []) if str(item).strip()]
    if not candidates and route_trace.get("skill_name"):
        candidates = [str(route_trace["skill_name"])]
    opts: list[dict[str, Any]] = []
    sop_names = {s.name for s in get_skill_registry().discoverable_sop_skills()}
    for idx, key in enumerate(candidates):
        if key in sop_names:
            opts.append({"key": key, "label": f"按推荐执行技能：{key}", "recommended": idx == 0})
        elif key == "tushare-data":
            opts.append({"key": key, "label": "使用实时金融数据（Tushare）", "recommended": idx == 0})
    if not any(item.get("key") == "fallback" for item in opts):
        opts.append({"key": "fallback", "label": "直接由 AI 回答（不强制工具链路）", "recommended": False})
    return opts


def _apply_hitl_choice_to_route_dict(route_dict: dict[str, Any], choice: str) -> dict[str, Any]:
    import copy

    out = copy.deepcopy(route_dict)
    choice = (choice or "").strip()
    args = dict(out.get("arguments") or {})
    sop_names = {s.name for s in get_skill_registry().discoverable_sop_skills()}

    if choice == "fallback":
        out["selected_skill"] = "fallback"
        out["selected_skill_family"] = "fallback"
        out["skill_name"] = None
        out["route_kind"] = "fallback"
        out["grounding_policy"] = "none"
        out["claim_policy"] = "full"
        out["execution_policy"] = "agentic"
        out["analysis_mode"] = "general_chat"
        out["needs_realtime_data"] = False
        out["needs_professional_analysis"] = False
        out["confidence"] = 1.0
        out["skill_contract"] = ""
        out["arguments"] = args
        return out

    if choice in sop_names:
        out["selected_skill"] = "financial-sop"
        out["selected_skill_family"] = "financial-sop"
        out["skill_name"] = choice
        out["route_kind"] = "financial_sop"
        out["grounding_policy"] = "preferred"
        out["claim_policy"] = "cautious"
        out["execution_policy"] = _sop_execution_policy_for_name(choice)
        out["skill_contract"] = choice
        out["needs_realtime_data"] = True
        out["needs_professional_analysis"] = True
        out["confidence"] = 1.0
        out["analysis_mode"] = str(out.get("analysis_mode") or "")
        out["arguments"] = args
        return out

    if choice == "tushare-data":
        out["selected_skill"] = "tushare-data"
        out["selected_skill_family"] = "tushare-data"
        out["skill_name"] = None
        out["route_kind"] = "tushare_data"
        out["grounding_policy"] = "required"
        out["claim_policy"] = "cautious"
        out["execution_policy"] = "deterministic"
        out["skill_contract"] = ""
        out["needs_realtime_data"] = True
        out["needs_professional_analysis"] = False
        out["confidence"] = 1.0
        if not str(out.get("analysis_mode") or "").strip():
            out["analysis_mode"] = "general_chat"
        out["arguments"] = args
        return out

    return out


async def _apply_skill_query_rewrite(
    route: Any,
    route_context: str,
    *,
    error_feedback: str = "",
) -> None:
    try:
        rewritten = await rewrite_query_for_skill(
            route,
            conversation_context=route_context,
            error_feedback=error_feedback or "",
        )
        if rewritten is None:
            return
        args = dict(route.arguments or {})
        args["effective_query"] = rewritten.query
        args["detected_entities"] = [{"value": e.value, "type": e.type} for e in rewritten.entities]
        if rewritten.tool_hints:
            args["tool_hints"] = rewritten.tool_hints
        route.arguments = args
        logger.info(
            "[chat-skill] query rewrite%s: entities=%d",
            " (retry)" if error_feedback else "",
            len(rewritten.entities),
        )
    except Exception as exc:
        logger.warning("[chat-skill] query rewrite failed (non-fatal): %s", exc)


def _serialize_prompt_payload(payload: Any, *, max_chars: int = 24000) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = str(payload)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>..."


def _extract_model_text(response: Any) -> str:
    if response is None:
        return ""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    chunks.append(str(text))
            elif isinstance(item, str):
                chunks.append(item)
        return "\n".join(chunks).strip()
    return str(content).strip()


async def summarize_sop_reply(
    *,
    effective_query: str,
    tool_data: dict[str, Any],
    answer_policy_context: str,
    ltm_full: str,
    skill_id: str,
    session_id: str,
    user_id: str,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    sections = _load_skill_doc_sections(skill_id)
    if settings.enable_synthesis_v2:
        prompt = build_sop_synthesis_prompt(
            effective_query=effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_full=ltm_full,
            skill_id=skill_id,
            output_template=sections.get("output_template") or "",
            fallbacks=sections.get("fallbacks") or "",
            decision_rules=sections.get("decision_rules") or "",
        )
    else:
        answer_policy_block = answer_policy_context or "【回答策略上下文】\n无"
        prompt = (
            "[角色]\n你是A股投研助手总结器，请依据证据回答。\n\n"
            "[SKILL 输出合同]\n"
            f"Output Template:\n{sections.get('output_template') or '无'}\n\n"
            f"Fallbacks:\n{sections.get('fallbacks') or '无'}\n\n"
            f"Decision Rules:\n{sections.get('decision_rules') or '无'}\n\n"
            f"[证据包 tool_data]\n{_serialize_prompt_payload(tool_data)}\n\n"
            f"[effective_query]\n{effective_query}\n\n"
            f"{answer_policy_block}\n\n"
            f"[全量 LTM]\n{ltm_full or '无'}\n\n"
            "[禁止项]\n"
            "- 不得编造证据包中不存在的数值\n"
            "- 若证据不足，按 Fallbacks 保守回答\n"
        )
    llm = _get_llm()
    log_model_stage(
        stage="summarize",
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        execution_path="sop",
        session_id=session_id,
        user_id=user_id,
    )
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是金融问答总结器。"),
                HumanMessage(content=prompt),
            ]
        )
        reply = _extract_model_text(response) or "我已完成这次分析，但当前暂无可复述内容。"
    except Exception as exc:
        logger.warning("[chat-skill] summarize_sop_reply failed: %s", exc, exc_info=True)
        log_degrade_transition(from_stage="summarize", reason=f"sop_summarize_failed: {exc}")
        reply = "我已完成工具执行，但总结阶段异常。你可以继续追问我具体维度。"

    log_reply_completed(
        mode="sop",
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="financial-sop",
        selected_skill="financial-sop",
        skill_name=skill_id,
        used_tools=bool((tool_data or {}).get("results") or (tool_data or {}).get("executor_trace")),
    )
    return reply


async def summarize_tushare_reply(
    *,
    effective_query: str,
    tool_data: dict[str, Any],
    answer_policy_context: str,
    ltm_full: str,
    session_id: str,
    user_id: str,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    if settings.enable_synthesis_v2:
        prompt = build_tushare_synthesis_prompt(
            effective_query=effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_full=ltm_full,
        )
    else:
        answer_policy_block = answer_policy_context or "【回答策略上下文】\n无"
        prompt = (
            "[角色]\n你是A股投研助手总结器，请依据证据回答。\n\n"
            f"[证据包 tool_data]\n{_serialize_prompt_payload(tool_data)}\n\n"
            f"[effective_query]\n{effective_query}\n\n"
            f"{answer_policy_block}\n\n"
            f"[全量 LTM]\n{ltm_full or '无'}\n\n"
            "[禁止项]\n"
            "- 不得编造证据包中不存在的数值\n"
        )
    llm = _get_llm()
    log_model_stage(
        stage="summarize",
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        execution_path="tushare",
        session_id=session_id,
        user_id=user_id,
    )
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是金融问答总结器。"),
                HumanMessage(content=prompt),
            ]
        )
        reply = _extract_model_text(response) or "已完成实时数据检索，但暂无可复述内容。"
    except Exception as exc:
        logger.warning("[chat-skill] summarize_tushare_reply failed: %s", exc, exc_info=True)
        log_degrade_transition(from_stage="summarize", reason=f"tushare_summarize_failed: {exc}")
        reply = "我已执行实时数据工具，但总结阶段异常。你可以继续追问具体指标。"

    log_reply_completed(
        mode="tushare",
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="tushare-data",
        selected_skill="tushare-data",
        used_tools=bool((tool_data or {}).get("results")),
    )
    return reply


async def summarize_fallback_reply(
    *,
    effective_query: str,
    answer_policy_context: str,
    ltm_full: str,
    session_id: str,
    user_id: str,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    if settings.enable_synthesis_v2:
        prompt = build_fallback_synthesis_prompt(
            effective_query=effective_query,
            answer_policy_context=answer_policy_context,
            ltm_full=ltm_full,
        )
    else:
        answer_policy_block = answer_policy_context or "【回答策略上下文】\n无"
        prompt = (
            "[角色]\n你是通用问答总结器。\n\n"
            f"[effective_query]\n{effective_query}\n\n"
            f"{answer_policy_block}\n\n"
            f"[LTM 全量]\n{ltm_full or '无'}\n\n"
            "[要求]\n结合上下文给出直接回答，尽量简洁。"
        )
    llm = _get_llm()
    log_model_stage(
        stage="summarize",
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        execution_path="fallback",
        session_id=session_id,
        user_id=user_id,
    )
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是对话助手。"),
                HumanMessage(content=prompt),
            ]
        )
        reply = _extract_model_text(response) or "我理解了你的问题，但暂时无法给出完整回答。"
    except Exception as exc:
        logger.warning("[chat-skill] summarize_fallback_reply failed: %s", exc, exc_info=True)
        log_degrade_transition(from_stage="summarize", reason=f"fallback_summarize_failed: {exc}")
        reply = "我暂时没能完成回答生成，请换一种问法再试。"

    log_reply_completed(
        mode="fallback",
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="fallback",
        selected_skill="fallback",
        used_tools=False,
    )
    return reply


async def _run_post_rewrite_extractors_if_enabled(
    *,
    db: AsyncSession,
    session: Session,
    route: str,
    skill_id: str | None,
    user_message: str,
    resolver_hint: dict[str, Any] | None,
    rewrite_result: Any,
    message_id: int | None,
) -> None:
    if not settings.enable_post_rewrite_extractors:
        return
    ctx = RewriteContextPacket(
        route=route,  # type: ignore[arg-type]
        skill_id=skill_id,
        user_query=user_message,
        active_entity=resolver_hint,
        candidate_entities=list((resolver_hint or {}).get("candidate_entities") or []),
        resolution_status=str((resolver_hint or {}).get("resolution_status") or "no_entity"),
        working_state_prev=get_working_state(session),
    )
    try:
        constraints_result, pref_result = await asyncio.gather(
            extract_constraints(ctx, rewrite_result),
            extract_reply_preference(ctx, rewrite_result),
        )
        if constraints_result.operation != "no_update":
            from backend.services.working_state import upsert_constraints

            await upsert_constraints(
                db,
                session,
                constraints_result.constraints,
                message_id=message_id,
                confidence=constraints_result.confidence,
            )
        if pref_result.operation != "no_update":
            from backend.services.working_state import upsert_reply_preference

            await upsert_reply_preference(
                db,
                session,
                pref_result.reply_preference_hint,
                message_id=message_id,
                confidence=pref_result.confidence,
            )
    except Exception as exc:
        logger.warning("[chat-skill] post rewrite extractors failed (non-fatal): %s", exc, exc_info=True)


def _trace_plan_artifacts(trace: dict[str, Any]) -> tuple[dict | None, dict | None, dict | None, str | None]:
    executor = trace.get("executor") if isinstance(trace.get("executor"), dict) else {}
    plan_artifact = None
    if executor.get("plan_id") or executor.get("plan_preview"):
        plan_artifact = {
            "plan_id": executor.get("plan_id"),
            "discovery_trace_id": executor.get("discovery_trace_id"),
            "plan_preview": executor.get("plan_preview") or [],
        }
    skill_artifact = None
    if executor.get("skill_loader_artifacts"):
        skill_artifact = {
            "skill_loader_artifacts": executor.get("skill_loader_artifacts") or [],
            "skill_version": executor.get("skill_version") or "",
            "spec_hash": executor.get("spec_hash") or "",
            "registry_version": executor.get("registry_version") or "",
        }
    verification = executor.get("verification") if isinstance(executor.get("verification"), dict) else None
    allowed = None
    if verification:
        allowed = str(verification.get("allowed_claim_level") or "") or None
    allowed = allowed or str(executor.get("allowed_claim_level") or executor.get("evidence_allowed_claim_level") or "") or None
    return plan_artifact, skill_artifact, verification, allowed


async def _run_skill_chat_if_enabled(
    *,
    db: AsyncSession,
    session: Session,
    user_id: str,
    user_message: str,
    sop_skill_id: str | None = None,
    exclude_message_id: int | None = None,
    preloaded_memory_profile: dict | None = None,
    preloaded_memory_system_prompt: str | None = None,
) -> tuple[str | None, dict, dict, str]:
    if not settings.enable_chat_skills:
        return None, dict(preloaded_memory_profile or {}), {}, preloaded_memory_system_prompt or ""

    _ensure_skill_runtime_ready()
    if preloaded_memory_profile is None or preloaded_memory_system_prompt is None:
        memory_profile, memory_system_prompt = await _load_memory_context_for_chat(db, user_id, user_message)
    else:
        memory_profile = dict(preloaded_memory_profile)
        memory_system_prompt = preloaded_memory_system_prompt
    route_ltm_summary = _profile_to_route_summary(memory_profile)
    _, route_context_slice_text, answer_policy_context = _resolve_session_summary_contexts(session)
    route_context = await _build_skill_route_context(
        db,
        session,
        exclude_message_id=exclude_message_id,
        route_slice_text=route_context_slice_text,
    )
    resolver_hint = None
    if settings.enable_entity_resolver_v2:
        previous_active = get_working_state(session).get("active_entity")
        with trace_span("entity_resolution_v2", stage="entity_resolution_v2", data={"enabled": True}):
            entity_v2 = await resolve_authoritative_entity(
                user_message,
                allowed_asset_types={"stock", "fund", "sector", "index"},
                previous_active_entity=previous_active if isinstance(previous_active, dict) else None,
                source_message_id=exclude_message_id,
            )
        entity_payload = entity_v2.model_dump() if hasattr(entity_v2, "model_dump") else entity_v2.dict()
        if entity_v2.primary_entity is not None:
            primary = entity_v2.primary_entity
            resolver_hint = {
                "display_name": primary.display_name,
                "asset_type": primary.entity_type,
                "symbol": primary.canonical_id,
                "confidence": entity_v2.confidence,
                "resolver_stage": primary.resolver_path,
                "resolver_source": "entity_resolver_v2",
                "resolution_status": entity_v2.resolution_status,
                "candidate_entities": [item.model_dump() for item in entity_v2.candidate_entities],
            }
            await upsert_active_entity(
                db,
                session,
                {**resolver_hint, "entity_type": primary.entity_type, "canonical_id": primary.canonical_id},
                message_id=exclude_message_id,
                confidence=entity_v2.confidence,
            )
        if entity_v2.need_clarification:
            await upsert_active_entity(
                db,
                session,
                {"resolution_status": entity_v2.resolution_status, "candidate_entities": entity_payload.get("candidate_entities", [])},
                message_id=exclude_message_id,
                confidence=entity_v2.confidence,
            )
            return (
                entity_v2.clarification_question or "我需要先确认一下你说的是哪个标的？",
                memory_profile,
                {
                    "selected_skill_family": "clarification",
                    "selected_skill": "entity-clarification",
                    "skill_name": None,
                    "analysis_mode": "entity_resolution",
                    "execution_policy": "deterministic",
                    "entity_resolution": entity_payload,
                    "executor": {"reply_mode": "clarification", "used_tools": False},
                },
                memory_system_prompt,
            )
    else:
        resolver_hint = await _resolve_entity_hint_for_route(session, user_message)
    resolver_hint_block = _resolver_hint_to_prompt_block(resolver_hint)
    if resolver_hint_block:
        route_context = f"{resolver_hint_block}\n\n{route_context}" if route_context else resolver_hint_block
    normalized_sop_skill_id = normalize_requested_sop_skill_id(sop_skill_id)
    skipped_llm_router = normalized_sop_skill_id is not None
    route_source = "user_explicit" if skipped_llm_router else "llm"
    with trace_span(
        "route",
        stage="route",
        data={
            "user_query_summary": _trace_query_summary(user_message),
            "profile_summary_used": bool(route_ltm_summary),
            "user_sop_skill_id": normalized_sop_skill_id,
            "skipped_llm_router": skipped_llm_router,
        },
    ):
        if normalized_sop_skill_id is not None:
            decision = user_explicit_sop_decision(normalized_sop_skill_id)
            if decision is None:
                raise InvalidSopSkillError(f"无效的 sop_skill_id: {normalized_sop_skill_id}")
        else:
            decision = await route_chat_skill(
                user_message,
                conversation_context=route_context,
                profile_summary=route_ltm_summary,
                enable_route_v2=settings.enable_route_v2,
                active_entity=resolver_hint,
            )
    route_trace = _build_executor_route_trace(decision, user_message)
    if skipped_llm_router:
        route_trace["confidence"] = 1.0
    log_model_stage(
        stage="router",
        model=None,
        execution_path="routing",
        session_id=session.id,
        user_id=user_id,
        route_source=route_source,
        skipped_llm_router=skipped_llm_router,
    )
    log_router_decision(
        route=decision.route,
        skill_id=decision.skill_id,
        execution_policy=decision.execution_policy,
        session_id=session.id,
        user_id=user_id,
        route_source=route_source,
        route_confidence=1.0 if skipped_llm_router else None,
    )
    logger.info(
        "[chat-skill] route=%s skill_id=%s execution_policy=%s selected_skill=%s route_source=%s",
        decision.route,
        decision.skill_id or "",
        decision.execution_policy,
        route_trace.get("selected_skill"),
        route_source,
    )

    if bool(route_trace.get("need_confirm")) and settings.enable_skill_route_hitl:
        options = _build_skill_confirm_options_from_trace(route_trace)
        payload = {
            "session_id": session.id,
            "user_id": user_id,
            "user_message": user_message,
            "route_context": route_context,
            "route_dict": route_trace,
            "options": options,
            "reasoning": str((route_trace.get("route_stage1") or {}).get("reasoning_brief") or "需要确认是否进入技能链路"),
            "resolved_query": user_message,
            "confidence": float(route_trace.get("confidence") or 0.0),
        }
        set_pending_skill_confirm(session.id, payload)
        return (
            "",
            memory_profile,
            {
                **route_trace,
                "hitl_pending": True,
                "skill_confirm": {
                    "options": options,
                    "reasoning": payload["reasoning"],
                    "resolved_query": user_message,
                    "confidence": payload["confidence"],
                },
            },
            memory_system_prompt,
        )

    if decision.route == "sop":
        rewrite_result = await rewrite_for_sop(
            decision,
            user_message,
            stm_snapshot=route_context,
            ltm_summary=route_ltm_summary,
            resolver_hint=resolver_hint,
        )
        await _run_post_rewrite_extractors_if_enabled(
            db=db,
            session=session,
            route="financial-sop",
            skill_id=decision.skill_id,
            user_message=user_message,
            resolver_hint=resolver_hint,
            rewrite_result=rewrite_result,
            message_id=exclude_message_id,
        )

        args = dict(route_trace.get("arguments") or {})
        args["effective_query"] = rewrite_result.effective_query
        args["skill_params"] = dict(rewrite_result.skill_params or {})
        if resolver_hint:
            args["resolved_entity_hint"] = dict(resolver_hint)
            args["inherited_entity"] = str(resolver_hint.get("display_name") or "")
            args["inherited_entity_id"] = str(resolver_hint.get("symbol") or "")
        args["candidate_entities"] = [item.display_name for item in rewrite_result.entities]
        args["entities"] = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in rewrite_result.entities
        ]
        route_trace["arguments"] = args

        _exec_data = {
            "selected_skill": route_trace.get("selected_skill"),
            "skill_name": route_trace.get("skill_name"),
            "analysis_mode": route_trace.get("analysis_mode"),
            "execution_policy": route_trace.get("execution_policy"),
        }
        if settings.enable_sop_v2:
            sop_skill_id = _resolve_sop_skill_id(route_trace, decision)
            skill_spec = get_skill_registry().load_skill_spec(sop_skill_id)
            if not skill_spec:
                raise ValueError(f"SOP v2 缺少 skill_spec.yaml: {sop_skill_id or decision.skill_id}")
            with trace_span("executor_v2", stage="executor", data={**_exec_data, "version": "v2"}):
                v2_result = await run_sop_v2_pipeline(
                    skill_name=sop_skill_id,
                    skill_spec=skill_spec,
                    user_message=user_message,
                    rewrite_result=rewrite_result,
                    active_entity=resolver_hint,
                    trace_id=session.id,
                    config=settings,
                )
            result_trace = v2_result.tool_data().get("executor_trace") or {}
            tool_data = v2_result.tool_data()
            log_tool_plan(
                planner_type="sop_v2",
                analysis_mode=str(route_trace.get("analysis_mode") or "general_chat"),
                planned_tools=list(result_trace.get("planned_tools") or []),
                plan_preview=list(result_trace.get("plan_preview") or []),
                execution_path=str(route_trace.get("execution_policy") or "deterministic"),
                skill_name=sop_skill_id,
                plan_id=result_trace.get("plan_id"),
            )
        else:
            with trace_span("executor", stage="executor", data=_exec_data):
                result = await execute_skill(
                    selected_skill=str(route_trace.get("selected_skill") or "fallback"),
                    user_message=user_message,
                    memory_context=memory_system_prompt,
                    answer_policy_context=answer_policy_context,
                    profile_summary=_profile_to_summary(memory_profile),
                    session_id=session.id,
                    user_id=user_id,
                    route_trace=route_trace,
                    enable_tushare_skills=settings.enable_tushare_skills,
                    enable_tushare_planner=settings.enable_tushare_planner,
                    enable_tushare_market_tools=settings.enable_tushare_market_tools,
                    enable_tushare_index_tools=settings.enable_tushare_index_tools,
                    enable_tushare_sector_tools=settings.enable_tushare_sector_tools,
                    enable_fundamental_analysis=settings.enable_fundamental_analysis,
                    enable_sector_analysis=settings.enable_sector_analysis,
                    enable_stock_selection=settings.enable_stock_selection,
                    enable_deterministic_skill_execution=settings.enable_deterministic_skill_execution,
                    enable_tool_prefetch_concurrency=settings.enable_tool_prefetch_concurrency,
                )
            result_trace = result.trace
            tool_data = {"executor_trace": result.trace, "route_arguments": args}
        reply = await summarize_sop_reply(
            effective_query=rewrite_result.effective_query,
            tool_data={**tool_data, "route_arguments": args},
            answer_policy_context=answer_policy_context,
            ltm_full=memory_system_prompt,
            skill_id=str(decision.skill_id or ""),
            session_id=session.id,
            user_id=user_id,
        )
        trace = dict(route_trace)
        trace["executor"] = result_trace
        return reply, memory_profile, trace, memory_system_prompt

    if decision.route == "tushare":
        use_tushare_v2_pipeline = (
            settings.enable_tushare_v2
            and settings.enable_planner_v2
            and settings.enable_executor_v2
        )
        if use_tushare_v2_pipeline:
            rewrite_ctx = RewriteContextPacket(
                route="tushare-data",
                user_query=user_message,
                active_entity=resolver_hint,
                working_state_prev=get_working_state(session),
            )
            rewrite_result = await rewrite_for_tushare_v2(rewrite_ctx)
        else:
            rewrite_result = await rewrite_for_tushare(
                decision,
                user_message,
                stm_snapshot=route_context,
                ltm_summary=route_ltm_summary,
                resolver_hint=resolver_hint,
            )
        await _run_post_rewrite_extractors_if_enabled(
            db=db,
            session=session,
            route="tushare-data",
            skill_id=None,
            user_message=user_message,
            resolver_hint=resolver_hint,
            rewrite_result=rewrite_result,
            message_id=exclude_message_id,
        )
        args = dict(route_trace.get("arguments") or {})
        args["effective_query"] = rewrite_result.effective_query
        if resolver_hint:
            args["resolved_entity_hint"] = dict(resolver_hint)
            args["inherited_entity"] = str(resolver_hint.get("display_name") or "")
            args["inherited_entity_id"] = str(resolver_hint.get("symbol") or "")
        args["entities"] = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in rewrite_result.entities
        ]
        if hasattr(rewrite_result, "tool_plan"):
            args["tool_plan"] = [
                item.model_dump() if hasattr(item, "model_dump") else item.dict()
                for item in rewrite_result.tool_plan
            ]
        route_trace["arguments"] = args
        planned_tool_names = [step.tool_name for step in getattr(rewrite_result, "tool_plan", [])]
        log_tool_plan(
            planner_type="rewrite_tushare_v2" if use_tushare_v2_pipeline else "rewrite_tushare",
            analysis_mode="general_chat",
            planned_tools=planned_tool_names,
            execution_path="deterministic",
            tool_batch_size=len(planned_tool_names),
        )
        if use_tushare_v2_pipeline:
            with trace_span(
                "executor_v2",
                stage="executor",
                data={"selected_skill": "tushare-data", "analysis_mode": "general_chat", "version": "v2"},
            ):
                v2_result = await run_tushare_v2_pipeline(
                    rewrite_result=rewrite_result,
                    active_entity=resolver_hint,
                    trace_id=session.id,
                    config=settings,
                )
            tool_data = v2_result.tool_data()
        else:
            with trace_span(
                "executor",
                stage="executor",
                data={"selected_skill": "tushare-data", "analysis_mode": "general_chat"},
            ):
                tool_data = await execute_tushare_plan(
                    rewrite_result.tool_plan,
                    rewrite_result.entities,
                    session_id=session.id,
                    user_id=user_id,
                    decision=decision,
                    user_message=rewrite_result.effective_query,
                    stm_snapshot=route_context,
                    ltm_summary=route_ltm_summary,
                )
        reply = await summarize_tushare_reply(
            effective_query=rewrite_result.effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_full=memory_system_prompt,
            session_id=session.id,
            user_id=user_id,
        )
        trace = dict(route_trace)
        trace["executor"] = dict(tool_data.get("executor_trace") or {})
        return reply, memory_profile, trace, memory_system_prompt

    rewrite_result = await rewrite_for_fallback(
        user_message,
        stm_snapshot=route_context,
        ltm_summary=route_ltm_summary,
        resolver_hint=resolver_hint,
    )
    await _run_post_rewrite_extractors_if_enabled(
        db=db,
        session=session,
        route="fallback",
        skill_id=None,
        user_message=user_message,
        resolver_hint=resolver_hint,
        rewrite_result=rewrite_result,
        message_id=exclude_message_id,
    )
    args = dict(route_trace.get("arguments") or {})
    args["effective_query"] = rewrite_result.effective_query
    if resolver_hint:
        args["resolved_entity_hint"] = dict(resolver_hint)
        args["inherited_entity"] = str(resolver_hint.get("display_name") or "")
        args["inherited_entity_id"] = str(resolver_hint.get("symbol") or "")
    route_trace["arguments"] = args
    reply = await summarize_fallback_reply(
        effective_query=rewrite_result.effective_query,
        answer_policy_context=answer_policy_context,
        ltm_full=memory_system_prompt,
        session_id=session.id,
        user_id=user_id,
    )
    route_trace["executor"] = {
        "selected_skill_family": "fallback",
        "selected_skill": "fallback",
        "skill_name": None,
        "analysis_mode": "general_chat",
        "execution_policy": "deterministic",
        "reply_mode": "fallback",
        "used_tools": False,
        "planned_tools": [],
        "prefetched_tool_names": [],
        "evidence_ok": False,
        "missing_evidence_reasons": [],
        "failure_code": "",
    }
    return reply, memory_profile, route_trace, memory_system_prompt


async def confirm_skill_route(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    user_choice: str,
) -> tuple[str, dict, object, dict | None]:
    """
    Resume a low-confidence route after user confirms skill choice (HITL).
    Consumes one pending record from chat_hitl_pending.
    """
    pending = pop_pending_skill_confirm(session_id)
    if not pending or pending.get("user_id") != user_id:
        raise ValueError("没有待确认的路由，或已过期。请重新发送消息。")

    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise ValueError("会话不存在")

    user_message = str(pending.get("user_message") or "")
    route_dict = _apply_hitl_choice_to_route_dict(pending.get("route_dict") or {}, user_choice)
    route_trace = dict(route_dict)

    memory_profile, memory_system_prompt = await _load_memory_context_for_chat(db, user_id, user_message)
    _, _, answer_policy_context = _resolve_session_summary_contexts(session)
    turn_trace: dict = dict(route_trace)

    if str(route_trace.get("selected_skill") or "") == "fallback":
        llm = _get_llm()
        lc_messages = await _build_fallback_chat_messages(
            db,
            session,
            memory_system_prompt=memory_system_prompt,
        )
        try:
            response = await llm.ainvoke(lc_messages)
        except Exception as exc:
            if not _is_context_overflow_error(exc):
                raise
            recovered = await _force_overflow_recovery_compaction(
                db,
                session,
                user_message=user_message,
                exc=exc,
            )
            if not recovered:
                raise
            lc_messages = await _build_fallback_chat_messages(
                db,
                session,
                memory_system_prompt=memory_system_prompt,
            )
            response = await llm.ainvoke(lc_messages)
        reply_text = response.content if hasattr(response, "content") else str(response)
        log_reply_completed(
            mode="fallback-hitl-confirm",
            session_id=session.id,
            user_id=user_id,
            selected_skill_family="fallback",
            selected_skill="fallback",
            analysis_mode="general_chat",
            execution_policy="agentic",
        )
    else:
        _exec_data = {
            "selected_skill_family": route_trace.get("selected_skill_family"),
            "selected_skill": route_trace.get("selected_skill"),
            "skill_name": route_trace.get("skill_name"),
            "analysis_mode": route_trace.get("analysis_mode"),
            "execution_policy": route_trace.get("execution_policy"),
        }
        with trace_span("executor", stage="executor", data=_exec_data):
            result = await execute_skill(
                selected_skill=str(route_trace.get("selected_skill") or "fallback"),
                user_message=user_message,
                memory_context=memory_system_prompt,
                answer_policy_context=answer_policy_context,
                profile_summary=_profile_to_summary(memory_profile),
                session_id=session.id,
                user_id=user_id,
                route_trace=route_trace,
                enable_tushare_skills=settings.enable_tushare_skills,
                enable_tushare_planner=settings.enable_tushare_planner,
                enable_tushare_market_tools=settings.enable_tushare_market_tools,
                enable_tushare_index_tools=settings.enable_tushare_index_tools,
                enable_tushare_sector_tools=settings.enable_tushare_sector_tools,
                enable_fundamental_analysis=settings.enable_fundamental_analysis,
                enable_sector_analysis=settings.enable_sector_analysis,
                enable_stock_selection=settings.enable_stock_selection,
                enable_deterministic_skill_execution=settings.enable_deterministic_skill_execution,
                enable_tool_prefetch_concurrency=settings.enable_tool_prefetch_concurrency,
            )
        if _executor_qualifies_for_evidence_retry(result.trace):
            reasons = (result.trace or {}).get("missing_evidence_reasons") or []
            fb = "; ".join(str(x) for x in reasons[:8])
            with trace_span("executor_retry", stage="executor", data={**_exec_data, "retry": True}):
                result = await execute_skill(
                    selected_skill=str(route_trace.get("selected_skill") or "fallback"),
                    user_message=user_message,
                    memory_context=memory_system_prompt,
                    answer_policy_context=answer_policy_context,
                    profile_summary=_profile_to_summary(memory_profile),
                    session_id=session.id,
                    user_id=user_id,
                    route_trace=route_trace,
                    enable_tushare_skills=settings.enable_tushare_skills,
                    enable_tushare_planner=settings.enable_tushare_planner,
                    enable_tushare_market_tools=settings.enable_tushare_market_tools,
                    enable_tushare_index_tools=settings.enable_tushare_index_tools,
                    enable_tushare_sector_tools=settings.enable_tushare_sector_tools,
                    enable_fundamental_analysis=settings.enable_fundamental_analysis,
                    enable_sector_analysis=settings.enable_sector_analysis,
                    enable_stock_selection=settings.enable_stock_selection,
                    enable_deterministic_skill_execution=settings.enable_deterministic_skill_execution,
                    enable_tool_prefetch_concurrency=settings.enable_tool_prefetch_concurrency,
                )
        reply_text = result.reply_text
        turn_trace = dict(route_trace)
        turn_trace["executor"] = result.trace
        log_reply_completed(
            mode="skill-hitl-confirm",
            session_id=session.id,
            user_id=user_id,
            selected_skill_family=turn_trace.get("selected_skill_family"),
            selected_skill=turn_trace.get("selected_skill"),
            skill_name=turn_trace.get("skill_name"),
            analysis_mode=turn_trace.get("analysis_mode"),
            execution_policy=turn_trace.get("execution_policy"),
        )

    if settings.enable_memory and user_id:
        reply_text = await _prepare_reply_for_user(reply_text, user_id=user_id, db=db)

    _record_route_runtime_with_log(
        session_id=session.id,
        user_message=user_message,
        route_trace=turn_trace,
        reply_text=reply_text,
    )
    route_summary = _build_route_summary(turn_trace)

    ai_msg = Message(
        session_id=session.id,
        role="assistant",
        content=str(reply_text or ""),
        token_count=count_message_tokens("assistant", str(reply_text or ""))[0],
        route_summary_json=_persistable_route_summary(route_summary),
    )
    db.add(ai_msg)
    session.turn_count = (session.turn_count or 0) + 1
    session.updated_at = datetime.utcnow()
    await db.flush()
    user_msg_id_result = await db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.role == "user")
        .order_by(Message.id.desc())
        .limit(1)
    )
    latest_user_msg_id = user_msg_id_result.scalar_one_or_none()
    await _apply_route_entities_to_stm_with_log(
        db=db,
        session=session,
        user_message=user_message,
        route_trace=turn_trace,
    )
    if latest_user_msg_id is not None:
        logger.info(
            "[STM-chat] 旧异步 STM 链路已停用: session=%s user_msg=%s assistant_msg=%s",
            session.id,
            latest_user_msg_id,
            ai_msg.id,
        )
    context_window = await refresh_session_context_metrics(db, session)
    context_window = enrich_context_window(context_window, session.id)
    await db.commit()

    if settings.enable_memory and user_id:
        asyncio.create_task(maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))
        log_memory_enqueue(
            session_id=session.id,
            user_id=user_id,
            queued=True,
            turn_index=session.turn_count,
        )

    return reply_text, memory_profile, context_window, route_summary


def _chunk_text(text: str, chunk_size: int = _CHAT_STREAM_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def _context_window_to_payload(context_window) -> dict:
    if context_window is None:
        return {}
    if hasattr(context_window, "model_dump"):
        return context_window.model_dump(mode="json")
    if hasattr(context_window, "dict"):
        return context_window.dict()
    return dict(context_window)


def _unique_strings(values: list[object], *, limit: int = 6) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _route_summary_skill_label(
    *,
    skill_contract: str,
    skill_name: str | None,
    selected_skill_family: str,
    selected_skill: str,
) -> str:
    """用户可见技能名：优先 SOP 注册表 official_name，其次 skill id，避免只显示 tushare-data。"""
    sid = (skill_contract or (skill_name or "")).strip()
    if sid:
        meta = get_skill_registry().get_skill(sid)
        if meta:
            on = (meta.official_name or "").strip()
            if on and on != sid:
                return on
        return sid
    if selected_skill == "fallback":
        return "普通对话"
    if selected_skill_family == "tushare-data" or selected_skill == "tushare-data":
        return "实时数据（Tushare）"
    return selected_skill_family or selected_skill


def _build_route_summary(skill_trace: dict | None) -> dict | None:
    trace = skill_trace or {}
    if not trace:
        return None
    executor = trace.get("executor") if isinstance(trace.get("executor"), dict) else {}
    accepted_evidences = executor.get("accepted_evidences") if isinstance(executor.get("accepted_evidences"), list) else []
    evidence_tools = [
        item.get("tool_name")
        for item in accepted_evidences
        if isinstance(item, dict) and item.get("tool_name")
    ]
    attempted_tools = executor.get("prefetched_tool_names") if isinstance(executor.get("prefetched_tool_names"), list) else []
    planned_tools = executor.get("planned_tools") if isinstance(executor.get("planned_tools"), list) else []
    notes = executor.get("missing_evidence_reasons") if isinstance(executor.get("missing_evidence_reasons"), list) else []

    selected_skill_family = str(trace.get("selected_skill_family") or executor.get("selected_skill_family") or "fallback")
    selected_skill = str(trace.get("selected_skill") or executor.get("selected_skill") or selected_skill_family or "fallback")
    if selected_skill_family == "fallback" and selected_skill == "fallback" and executor:
        selected_skill_family = str(executor.get("selected_skill_family") or selected_skill_family)

    route_kind = str(trace.get("route_kind") or executor.get("route_kind") or "")
    grounding_policy = str(trace.get("grounding_policy") or executor.get("grounding_policy") or "")
    claim_policy = str(trace.get("claim_policy") or executor.get("claim_policy") or "")
    skill_contract = str(trace.get("skill_contract") or executor.get("skill_contract") or "")
    failure_code = str(executor.get("failure_code") or "")
    sn = str(trace.get("skill_name") or executor.get("skill_name") or "").strip() or None
    verification = executor.get("verification") if isinstance(executor.get("verification"), dict) else {}
    verification_status = str(verification.get("status") or "")
    evidence_status = "ok" if bool(executor.get("evidence_ok")) else "missing"
    if verification_status == "partial":
        evidence_status = "partial"
    elif verification_status == "insufficient":
        evidence_status = "missing"

    user_facing = {
        "skill_label": _route_summary_skill_label(
            skill_contract=skill_contract,
            skill_name=sn,
            selected_skill_family=selected_skill_family,
            selected_skill=selected_skill,
        ),
        "analysis_mode": str(trace.get("analysis_mode") or executor.get("analysis_mode") or "general_chat"),
        "evidence_status": evidence_status,
        "failure_hint": failure_code if failure_code else "",
    }
    debug = {
        "route_kind": route_kind,
        "grounding_policy": grounding_policy,
        "claim_policy": claim_policy,
        "skill_contract": skill_contract,
        "evidence_tier": str(executor.get("evidence_tier") or ""),
        "evidence_missing_dimensions": list(executor.get("evidence_missing_dimensions") or verification.get("missing_dimensions") or []),
        "evidence_allowed_claim_level": str(executor.get("evidence_allowed_claim_level") or verification.get("allowed_claim_level") or ""),
        "failure_code": failure_code,
    }

    return {
        "selected_skill_family": selected_skill_family or "fallback",
        "selected_skill": selected_skill or "fallback",
        "skill_name": sn,
        "analysis_mode": str(trace.get("analysis_mode") or executor.get("analysis_mode") or "general_chat"),
        "execution_policy": str(trace.get("execution_policy") or executor.get("execution_policy") or "agentic"),
        "reply_mode": str(executor.get("reply_mode") or ("fallback" if selected_skill == "fallback" else "skill")),
        "route_confidence": round(float(trace.get("confidence") or 0.0), 4),
        "used_tools": bool(executor.get("used_tools") or evidence_tools or attempted_tools),
        "evidence_ok": bool(executor.get("evidence_ok")),
        "tools_used": _unique_strings(evidence_tools),
        "tools_attempted": _unique_strings(list(attempted_tools) + list(planned_tools)),
        "notes": _unique_strings(notes, limit=3),
        "route_kind": route_kind,
        "grounding_policy": grounding_policy,
        "claim_policy": claim_policy,
        "skill_contract": skill_contract,
        "failure_code": failure_code,
        "user_facing": user_facing,
        "debug": debug,
        # FIX-3: entity info from executor
        "resolved_company": str(executor.get("resolved_company") or ""),
        "resolved_symbol": str(executor.get("resolved_symbol") or ""),
    }


def _persistable_route_summary(route_summary: dict | None) -> dict | None:
    """Extract the user-facing portion of route_summary for persistence.

    Debug information is deliberately excluded from stored messages
    to keep history payloads lean and avoid leaking internal details.
    """
    if not route_summary:
        return None
    kept_keys = {
        "selected_skill_family", "selected_skill", "skill_name",
        "analysis_mode", "execution_policy", "reply_mode",
        "route_confidence", "used_tools", "evidence_ok",
        "tools_used", "tools_attempted", "notes",
        "user_facing", "resolved_company", "resolved_symbol",
    }
    return {k: v for k, v in route_summary.items() if k in kept_keys}


def _record_route_runtime_with_log(
    *,
    session_id: str,
    user_message: str,
    route_trace: dict | None,
    reply_text: str,
) -> Any | None:
    if not route_trace:
        return None
    state = record_route_runtime_state(
        session_id=session_id,
        user_message=user_message,
        route_trace=route_trace,
        reply_text=reply_text,
    )
    logger.info(
        "[chat-route-state] session=%s entity=%s mode=%s tool_status=%s fail_streak=%s followup_dim=%s",
        session_id,
        state.last_active_entity or "",
        state.last_analysis_mode or "",
        state.last_tool_status or "",
        int(state.inherited_fail_streak or 0),
        state.last_followup_dimension or "",
    )
    return state


def _route_trace_to_summary_entities(route_trace: dict | None) -> list[dict[str, Any]]:
    if not isinstance(route_trace, dict):
        return []
    executor = route_trace.get("executor") if isinstance(route_trace.get("executor"), dict) else {}
    if str(route_trace.get("selected_skill") or "") == "fallback":
        return []
    if executor and executor.get("evidence_ok") is False:
        return []

    args = route_trace.get("arguments") if isinstance(route_trace.get("arguments"), dict) else {}
    candidates: list[dict[str, Any]] = []

    def _append_entity(raw: dict[str, Any] | None, *, source: str) -> None:
        if not isinstance(raw, dict):
            return
        canonical_id = str(
            raw.get("canonical_id")
            or raw.get("symbol")
            or raw.get("inherited_entity_id")
            or ""
        ).strip()
        display_name = str(
            raw.get("display_name")
            or raw.get("company_name")
            or raw.get("name")
            or raw.get("inherited_entity")
            or ""
        ).strip()
        entity_type = str(raw.get("entity_type") or raw.get("asset_type") or "stock").strip() or "stock"
        if not canonical_id and not display_name:
            return
        candidate = {
            "canonical_id": canonical_id,
            "display_name": display_name,
            "entity_type": entity_type,
            "status": "active",
            "confidence": "high",
            "source": source,
            "evidence_text": display_name or canonical_id,
        }
        if candidate not in candidates:
            candidates.append(candidate)

    _append_entity(args.get("resolved_entity_hint"), source="resolver_hint")
    for item in list(args.get("entities") or []):
        _append_entity(item, source="route_trace_entities")
    _append_entity(
        {
            "canonical_id": executor.get("resolved_symbol"),
            "display_name": executor.get("resolved_company"),
            "entity_type": "stock",
        },
        source="executor_trace",
    )
    return candidates


async def _apply_route_entities_to_stm_with_log(
    *,
    db: AsyncSession,
    session: Session,
    user_message: str,
    route_trace: dict | None,
) -> list[str]:
    if not settings.enable_stm or not route_trace:
        return []
    candidate_entities = _route_trace_to_summary_entities(route_trace)
    if not candidate_entities:
        return []
    _, updated_fields = await apply_route_entity_hot_update(
        session,
        user_message=user_message,
        candidate_entities=candidate_entities,
    )
    if not updated_fields:
        return []
    await db.flush()
    logger.info(
        "event=route_entities_synced_to_stm session=%s updated_fields=%s entities=%s",
        session.id,
        ",".join(updated_fields),
        ",".join(
            str(item.get("canonical_id") or item.get("display_name") or "").strip()
            for item in candidate_entities
            if isinstance(item, dict)
        ),
    )
    return updated_fields


def _strip_profile_actions_from_reply(reply_text: str) -> str:
    cleaned = (reply_text or "").strip()
    if not cleaned:
        return ""

    # 清理规范的 <action>...</action> 标签
    cleaned = re.sub(r"<action>.*?</action>", "", cleaned, flags=re.DOTALL).strip()

    # 清理模型裸输出的画像动作 JSON，例如 {"action":"sectors","value":["半导体"]}
    cleaned = re.sub(
        r'^\s*\{[\s\S]*?"action"\s*:\s*"(?:update_profile|risk_level|sectors|investment_horizon|response_pref)"[\s\S]*?\}\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r'\n?\s*\{[\s\S]*?"action"\s*:\s*"(?:update_profile|risk_level|sectors|investment_horizon|response_pref)"[\s\S]*?\}\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    return cleaned


async def _prepare_reply_for_user(
    reply_text: str,
    *,
    user_id: str,
    db: AsyncSession,
) -> str:
    processed = (reply_text or "").strip()
    if not processed:
        return ""
    if settings.enable_memory and user_id:
        await _handle_profile_action_in_reply(processed, user_id, db)
    return _strip_profile_actions_from_reply(processed)


# ─────────────────────────────────────────────────────────────
# 会话管理（Phase 1 原有功能，不改动）
# ─────────────────────────────────────────────────────────────
async def get_or_create_session(
    db: AsyncSession, user_id: str, session_id: Optional[str]
) -> Session:
    """获取已有会话或为用户创建新会话。"""
    if session_id:
        result = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    session = Session(user_id=user_id, mode="chat")
    db.add(session)
    await db.flush()
    return session


async def get_sessions(db: AsyncSession, user_id: str) -> list[Session]:
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id, Session.mode == "chat")
        .order_by(Session.updated_at.desc())
    )
    sessions = list(result.scalars().all())
    metrics_changed = False
    for session in sessions:
        if session.context_updated_at is None:
            await refresh_session_context_metrics(db, session)
            metrics_changed = True
    if metrics_changed:
        await db.commit()
    return sessions


async def get_session_messages(
    db: AsyncSession, session_id: str, user_id: str
) -> list[Message]:
    """获取会话完整消息历史（含已压缩消息，用于前端"查看完整历史"）。"""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return []
    if session.context_updated_at is None:
        await refresh_session_context_metrics(db, session)
        await db.commit()
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, session_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return False
    await db.delete(session)
    await db.commit()
    return True


async def rename_session(
    db: AsyncSession, session_id: str, user_id: str, title: str
) -> bool:
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return False
    session.title = title
    await db.commit()
    return True


# ─────────────────────────────────────────────────────────────
# Phase 2 STM：compress_if_needed
# ─────────────────────────────────────────────────────────────
async def compress_if_needed(
    db: AsyncSession,
    session_id: str,
    *,
    trigger: str = "fallback_sync_compaction",
    force: bool = False,
) -> Optional[dict]:
    """
    Legacy STM 同步压缩入口。

    当前默认主链路已经切到：
      refresh metrics -> pre_compaction 判定 -> 同步 compaction / fallback

    本函数保留给以下场景使用：
      1. overflow fallback（上下文超限时的应急压缩）
      2. admin/debug repair
      3. emergency compaction

    Phase 2 起，本函数不再自己拼摘要 prompt，而是复用统一的
    `stm_summary_runtime.run_summary_compaction(...)`。
    """
    if not settings.enable_stm:
        return None  # ENABLE_STM=false 时跳过

    session_result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        return None

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.is_compressed == False)  # noqa: E712
        .order_by(Message.created_at)
    )
    uncompressed = list(result.scalars().all())

    if not force and len(uncompressed) < _STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES:
        return None  # 未达阈值，不压缩

    print(
        f"\n[STM-chat] 会话 {session_id[:8]}... 未压缩消息数={len(uncompressed)}，"
        f"触发压缩（fallback 条数阈值={_STM_FALLBACK_MIN_UNCOMPRESSED_MESSAGES} force={force}）"
    )
    logger.info(
        "[STM-chat] 触发压缩: session=%s uncompressed_count=%s force=%s trigger=%s",
        session_id,
        len(uncompressed),
        force,
        trigger,
    )

    # Legacy fallback 模式也必须保住最新消息，避免应急压缩后丢掉当前用户问题。
    keep_recent = max(1, int(settings.stm_keep_recent or 0))
    if len(uncompressed) > keep_recent:
        msgs_to_compress = uncompressed[:-keep_recent]
    else:
        msgs_to_compress = uncompressed[:-1]
    if not msgs_to_compress:
        logger.warning(
            "[STM-fallback] 无安全可压缩消息，跳过同步应急压缩: session=%s uncompressed=%s",
            session_id,
            len(uncompressed),
        )
        return None

    try:
        timeout_sec = max(1, int(settings.stm_fallback_compaction_timeout_sec))
        compaction_result = await asyncio.wait_for(
            run_summary_compaction(
                db=db,
                session=session,
                source_rows=msgs_to_compress,
                cutoff_message_id=msgs_to_compress[-1].id if msgs_to_compress else None,
                trigger=trigger,
            ),
            timeout=float(timeout_sec),
        )
    except Exception as exc:
        logger.error(f"[STM-chat] 压缩失败（不影响主流程）: {exc}", exc_info=True)
        print(f"[STM-chat] 压缩失败（不影响主流程）: {exc}")
        return None

    if not compaction_result.compacted:
        logger.warning(
            "[STM-chat] 统一压缩 runtime 未落盘: session=%s reason=%s",
            session_id,
            compaction_result.reason,
        )
        return None

    await db.refresh(session)
    print(
        f"[STM-chat] 压缩完成：{compaction_result.compressed_message_count} 条消息 → "
        f"摘要 {len(compaction_result.summary_text or '')} 字"
    )
    logger.info(
        "[STM-chat] 压缩完成: session=%s compressed=%s/%s summary_len=%s strategy=%s summary_version=%s",
        session_id,
        compaction_result.compressed_message_count,
        compaction_result.total_message_count,
        len(compaction_result.summary_text or ""),
        compaction_result.final_strategy,
        compaction_result.summary_version_after,
    )
    percent = (
        int(round((compaction_result.compressed_message_count / compaction_result.total_message_count) * 100))
        if compaction_result.total_message_count
        else 100
    )
    return {
        "session_id": session_id,
        "summary": compaction_result.summary_text,
        "snapshot_id": None,
        "compressed_message_count": compaction_result.compressed_message_count,
        "total_message_count": compaction_result.total_message_count,
        "percent": max(0, min(100, percent)),
        "reason": compaction_result.reason,
        "final_strategy": compaction_result.final_strategy,
    }


async def get_session_summaries(db: AsyncSession, session_id: str, user_id: str) -> list[SessionSummary]:
    """获取会话的摘要历史（仅返回属于该 user 的会话）。"""
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    if not session_result.scalar_one_or_none():
        return []
    result = await db.execute(
        select(SessionSummary)
        .where(SessionSummary.session_id == session_id)
        .order_by(SessionSummary.created_at.desc())
    )
    return list(result.scalars().all())


def _is_context_overflow_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(pattern in message for pattern in _STM_OVERFLOW_ERROR_PATTERNS)


async def _build_fallback_chat_messages(
    db: AsyncSession,
    session: Session,
    *,
    memory_system_prompt: str = "",
):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc_messages = [SystemMessage(content=_CHAT_SYSTEM_PROMPT)]

    if memory_system_prompt:
        lc_messages.append(SystemMessage(content=memory_system_prompt))
        logger.info(
            "[LTM-chat] 注入 memory_context: session=%s len=%s",
            session.id[:8],
            len(memory_system_prompt),
        )

    _, _, answer_policy_context = _resolve_session_summary_contexts(session)
    if settings.enable_stm and answer_policy_context:
        lc_messages.append(SystemMessage(content=answer_policy_context))
        logger.info(
            "[STM-chat] 注入 answer_policy_context: session=%s summary_len=%s",
            session.id[:8],
            len(answer_policy_context),
        )

    if settings.enable_stm:
        history_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id, Message.is_compressed == False)  # noqa: E712
            .order_by(Message.created_at.desc())
            .limit(_RECENT_MSG_LIMIT + 1)
        )
    else:
        history_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at.desc())
            .limit(_RECENT_MSG_LIMIT + 1)
        )
    recent_messages = list(reversed(history_result.scalars().all()))

    for msg in recent_messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            lc_messages.append(AIMessage(content=msg.content))

    return lc_messages


async def _force_overflow_recovery_compaction(
    db: AsyncSession,
    session: Session,
    *,
    user_message: str,
    exc: Exception,
) -> bool:
    if not settings.enable_stm:
        return False

    logger.warning(
        "[STM-fallback] 检测到上下文超限，开始同步应急压缩: session=%s user_len=%s error=%s",
        session.id,
        len(user_message or ""),
        str(exc)[:300],
    )
    print(f"[STM-fallback] session={session.id[:8]} 检测到上下文超限，开始同步应急压缩")

    compressed = await compress_if_needed(
        db,
        session.id,
        trigger="overflow_fallback_compaction",
        force=True,
    )
    if not compressed:
        try:
            await refresh_session_context_metrics(db, session)
            await db.commit()
        except Exception:
            await db.rollback()
        logger.warning(
            "[STM-fallback] 应急压缩未执行或无可压缩内容: session=%s",
            session.id,
        )
        return False

    await db.refresh(session)
    await refresh_session_context_metrics(db, session)
    await db.commit()
    logger.warning(
        "[STM-fallback] 应急压缩完成，准备重试: session=%s compressed=%s strategy=%s",
        session.id,
        compressed.get("compressed_message_count"),
        compressed.get("final_strategy"),
    )
    print(f"[STM-fallback] session={session.id[:8]} 应急压缩完成，准备重试")
    return True


# ─────────────────────────────────────────────────────────────
# Phase 1 保留：chat_single_turn（同步返回，无流式）
# ─────────────────────────────────────────────────────────────
async def chat_single_turn(
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: Optional[str] = None,
    sop_skill_id: str | None = None,
) -> tuple[str, str, dict, object, dict | None, dict | None, dict | None]:
    """
    执行单轮对话，返回 (
        reply, session_id, memory_profile, context_window, route_summary, skill_confirm, reserved
    )。
    skill_confirm 非空时表示 HITL，reply 为空，需调 confirm-skill。
    """
    session = await get_or_create_session(db, user_id, session_id)
    trace_id = new_trace_id()
    trace_started = time.perf_counter()
    final_selected_skill_family = "fallback"
    final_selected_skill = "fallback"
    final_skill_name = None
    final_analysis_mode = "general_chat"
    final_execution_policy = "agentic"
    final_status = "ok"
    turn_trace: dict = {}

    with skill_trace_context(
        trace_id=trace_id,
        group_id=session.id,
        session_id=session.id,
        user_id=user_id,
        workflow_name="chat-skill-turn",
        policy_version="trace-v1",
        trace_schema_version="2026-04-02.1",
        turn_index=(session.turn_count or 0) + 1,
    ):
        log_trace_started(user_query_summary=_trace_query_summary(user_message))
        try:
            normalized_sop_skill_id = None
            if settings.enable_chat_skills:
                normalized_sop_skill_id = validate_requested_sop_skill_id(sop_skill_id)

            # Phase 3：支持用户直接发送 JSON action（而非由 LLM 输出 <action>）
            # 例如：{"action":"update_profile","field":"sectors","value":[...]}后面跟自然语言
            if settings.enable_memory and user_id:
                user_message = await _handle_profile_action_in_user_message(db, user_id, user_message)

            # 保存用户消息
            user_msg = Message(
                session_id=session.id,
                role="user",
                content=user_message,
                token_count=count_message_tokens("user", user_message)[0],
            )
            db.add(user_msg)
            await db.flush()

            # 更新会话标题（取第一条用户消息前 30 字）
            if not session.title:
                session.title = user_message[:30]
                await db.flush()

            memory_profile, memory_system_prompt = await _prepare_chat_preflight_inputs(
                db,
                session,
                user_id=user_id,
                user_message=user_message,
            )
            await _run_chat_preflight_compaction(
                db,
                session,
                user_message=user_message,
                user_message_id=int(user_msg.id),
                memory_system_prompt=memory_system_prompt,
                trigger="preflight_budget_sync_chat",
            )

            skill_reply_text, memory_profile, skill_trace, memory_system_prompt = await _run_skill_chat_if_enabled(
                db=db,
                session=session,
                user_id=user_id,
                user_message=user_message,
                sop_skill_id=normalized_sop_skill_id,
                exclude_message_id=user_msg.id,
                preloaded_memory_profile=memory_profile,
                preloaded_memory_system_prompt=memory_system_prompt,
            )
            turn_trace = skill_trace or {}
            final_selected_skill_family = str(
                skill_trace.get("selected_skill_family") or final_selected_skill_family
            )
            final_selected_skill = str(skill_trace.get("selected_skill") or final_selected_skill)
            final_skill_name = skill_trace.get("skill_name") or final_skill_name
            final_analysis_mode = str(skill_trace.get("analysis_mode") or final_analysis_mode)
            final_execution_policy = str(
                skill_trace.get("execution_policy") or final_execution_policy
            )

            if skill_trace.get("hitl_pending"):
                context_window = await refresh_session_context_metrics(db, session)
                context_window = enrich_context_window(context_window, session.id)
                await db.commit()
                sc = skill_trace.get("skill_confirm") or {}
                skill_confirm_payload = {
                    "session_id": session.id,
                    "options": sc.get("options", []),
                    "reasoning": sc.get("reasoning", ""),
                    "resolved_query": sc.get("resolved_query", ""),
                    "confidence": sc.get("confidence", 0),
                }
                return (
                    "",
                    session.id,
                    memory_profile,
                    context_window,
                    None,
                    skill_confirm_payload,
                    None,
                )

            reply_prepared = False
            if skill_reply_text is not None:
                reply_text = await _prepare_reply_for_user(skill_reply_text, user_id=user_id, db=db)
                reply_prepared = True
                logger.info(
                    "[chat-skill] sync executed: session=%s skill=%s mode=%s",
                    session.id,
                    skill_trace.get("selected_skill"),
                    "skill",
                )
                log_reply_completed(
                    mode="skill",
                    session_id=session.id,
                    user_id=user_id,
                    selected_skill_family=skill_trace.get("selected_skill_family"),
                    selected_skill=skill_trace.get("selected_skill"),
                    skill_name=skill_trace.get("skill_name"),
                    analysis_mode=skill_trace.get("analysis_mode"),
                    execution_policy=skill_trace.get("execution_policy"),
                )
            else:
                llm = _get_llm()
                lc_messages = await _build_fallback_chat_messages(
                    db,
                    session,
                    memory_system_prompt=memory_system_prompt,
                )
                try:
                    response = await llm.ainvoke(lc_messages)
                except Exception as exc:
                    if not _is_context_overflow_error(exc):
                        raise
                    recovered = await _force_overflow_recovery_compaction(
                        db,
                        session,
                        user_message=user_message,
                        exc=exc,
                    )
                    if not recovered:
                        raise
                    lc_messages = await _build_fallback_chat_messages(
                        db,
                        session,
                        memory_system_prompt=memory_system_prompt,
                    )
                    response = await llm.ainvoke(lc_messages)
                reply_text = response.content
                final_selected_skill = "fallback"
                final_analysis_mode = "general_chat"
                log_reply_completed(
                    mode="fallback",
                    session_id=session.id,
                    user_id=user_id,
                    selected_skill_family="fallback",
                    selected_skill="fallback",
                    analysis_mode="general_chat",
                    execution_policy="agentic",
                )

            # ── Phase 3 LTM：解析 LLM 回复中的显式 profile update action ──
            if settings.enable_memory and not reply_prepared:
                reply_text = await _prepare_reply_for_user(reply_text, user_id=user_id, db=db)

            _record_route_runtime_with_log(
                session_id=session.id,
                user_message=user_message,
                route_trace=turn_trace,
                reply_text=reply_text,
            )

            route_summary = _build_route_summary(turn_trace)
            plan_artifact, skill_artifact, verification_artifact, allowed_claim_level = _trace_plan_artifacts(turn_trace)

            # 保存 assistant 消息（FIX-8: persist user-facing route summary）
            ai_msg = Message(
                session_id=session.id,
                role="assistant",
                content=reply_text,
                token_count=count_message_tokens("assistant", reply_text)[0],
                route_summary_json=_persistable_route_summary(route_summary),
                plan_artifact_json=plan_artifact,
                skill_artifact_json=skill_artifact,
                verification_json=verification_artifact,
                allowed_claim_level=allowed_claim_level,
            )
            db.add(ai_msg)

            # 更新会话统计
            session.turn_count = (session.turn_count or 0) + 1
            session.updated_at = datetime.utcnow()
            await db.flush()
            await _apply_route_entities_to_stm_with_log(
                db=db,
                session=session,
                user_message=user_message,
                route_trace=turn_trace,
            )
            logger.info(
                "[STM-chat] 旧异步 STM 链路已停用: session=%s user_msg=%s assistant_msg=%s",
                session.id,
                int(user_msg.id),
                int(ai_msg.id),
            )
            context_window = await refresh_session_context_metrics(db, session)
            context_window = enrich_context_window(context_window, session.id)
            await db.commit()

            logger.info(
                f"[chat] session={session.id} turn={session.turn_count} "
                f"user_len={len(user_message)} reply_len={len(reply_text)}"
            )
            print(
                f"[chat] session={session.id[:8]} turn={session.turn_count} "
                f"user={len(user_message)}字 reply={len(reply_text)}字"
            )

            # Phase 3 LTM：非阻塞触发 LTM 更新（asyncio.create_task 后台执行）
            if settings.enable_memory and user_id:
                with trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={"memory_enabled": True, "session_id": session.id, "turn_index": session.turn_count},
                ):
                    asyncio.create_task(
                        maybe_update_ltm_from_chat(session.id, user_id, session.turn_count)
                    )
                    log_memory_enqueue(
                        session_id=session.id,
                        user_id=user_id,
                        queued=True,
                        turn_index=session.turn_count,
                    )
            else:
                with trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={
                        "memory_enabled": bool(settings.enable_memory),
                        "session_id": session.id,
                        "turn_index": session.turn_count,
                        "enqueue_skipped_reason": "memory_disabled" if not settings.enable_memory else "missing_user_id",
                    },
                ):
                    log_memory_enqueue(
                        session_id=session.id,
                        user_id=user_id,
                        queued=False,
                        turn_index=session.turn_count,
                        enqueue_skipped_reason="memory_disabled" if not settings.enable_memory else "missing_user_id",
                    )

            return (
                reply_text,
                session.id,
                memory_profile,
                context_window,
                route_summary,
                None,
                {
                    "plan_artifact": plan_artifact,
                    "skill_artifact": skill_artifact,
                    "verification": verification_artifact,
                    "allowed_claim_level": allowed_claim_level,
                },
            )
        except Exception:
            final_status = "error"
            raise
        finally:
            log_trace_finished(
                status=final_status,
                duration_ms=round((time.perf_counter() - trace_started) * 1000, 2),
                metrics=_trace_root_metrics(turn_trace),
                refs=_trace_root_refs(turn_trace),
                **_trace_root_payload(
                    final_status=final_status,
                    selected_skill_family=final_selected_skill_family,
                    selected_skill=final_selected_skill,
                    skill_name=final_skill_name,
                    analysis_mode=final_analysis_mode,
                    execution_policy=final_execution_policy,
                    skill_trace=turn_trace,
                ),
            )


# ─────────────────────────────────────────────────────────────
# Phase 2 新增：stream_chat_single_turn（流式生成器）
# ─────────────────────────────────────────────────────────────
async def stream_chat_single_turn(
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: Optional[str] = None,
    sop_skill_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    流式对话生成器：逐 token yield 内容，供 WebSocket 路由使用。

    协议（与前端 useChat.ts 对应）：
    - 正常 token：直接 yield 文本片段
    - 会话 ID 通知：yield JSON {"type": "session_id", "session_id": "..."}
    - 完成信号：yield JSON {"type": "done", "session_id": "..."}
    - 错误：yield JSON {"type": "error", "message": "..."}
    """
    import json

    session = await get_or_create_session(db, user_id, session_id)
    trace_id = new_trace_id()
    trace_started = time.perf_counter()
    final_selected_skill_family = "fallback"
    final_selected_skill = "fallback"
    final_skill_name = None
    final_analysis_mode = "general_chat"
    final_execution_policy = "agentic"
    final_status = "ok"
    turn_trace: dict = {}

    with skill_trace_context(
        trace_id=trace_id,
        group_id=session.id,
        session_id=session.id,
        user_id=user_id,
        workflow_name="chat-skill-turn",
        policy_version="trace-v1",
        trace_schema_version="2026-04-02.1",
        turn_index=(session.turn_count or 0) + 1,
    ):
        log_trace_started(user_query_summary=_trace_query_summary(user_message))
        try:
            normalized_sop_skill_id = None
            if settings.enable_chat_skills:
                normalized_sop_skill_id = validate_requested_sop_skill_id(sop_skill_id)

            # Phase 3：流式模式同样支持用户直接发送 JSON action
            if settings.enable_memory and user_id:
                user_message = await _handle_profile_action_in_user_message(db, user_id, user_message)

            # 保存用户消息
            user_msg = Message(
                session_id=session.id,
                role="user",
                content=user_message,
                token_count=count_message_tokens("user", user_message)[0],
            )
            db.add(user_msg)
            await db.flush()

            if not session.title:
                session.title = user_message[:30]
                await db.flush()

            # 通知前端会话 ID（新建会话时前端需要更新 currentSessionId）
            yield json.dumps({"type": "session_id", "session_id": session.id}, ensure_ascii=False)

            memory_profile, memory_system_prompt = await _prepare_chat_preflight_inputs(
                db,
                session,
                user_id=user_id,
                user_message=user_message,
            )
            preflight_decision = None
            if settings.enable_stm and settings.stm_summary_preflight_enabled:
                preflight_context_window = await refresh_session_context_metrics(db, session)
                preflight_decision = should_run_preflight_summary_compaction(
                    session,
                    user_message,
                    system_prompt_text=_CHAT_SYSTEM_PROMPT,
                    memory_prompt_text=memory_system_prompt,
                )
                if preflight_decision.should_compact:
                    yield json.dumps(
                        {
                            "type": "task_status_running",
                            "session_id": session.id,
                            "task_kind": "pre_compaction",
                            "context_window": _context_window_to_payload(preflight_context_window),
                        },
                        ensure_ascii=False,
                    )

                preflight_result = await maybe_run_preflight_summary_compaction(
                    db=db,
                    session=session,
                    pending_user_message=user_message,
                    system_prompt_text=_CHAT_SYSTEM_PROMPT,
                    memory_prompt_text=memory_system_prompt,
                    exclude_message_ids={int(user_msg.id)},
                    trigger="preflight_budget_stream_chat",
                )
                await db.refresh(session)
                if preflight_decision.should_compact:
                    refreshed_preflight_window = await refresh_session_context_metrics(db, session)
                    yield json.dumps(
                        {
                            "type": "task_status_done" if preflight_result.compacted else "task_status_failed",
                            "session_id": session.id,
                            "task_kind": "pre_compaction",
                            "context_window": _context_window_to_payload(refreshed_preflight_window),
                            **(
                                {"message": preflight_result.reason}
                                if not preflight_result.compacted
                                else {}
                            ),
                        },
                        ensure_ascii=False,
                    )

            skill_reply_text, _, skill_trace, memory_system_prompt = await _run_skill_chat_if_enabled(
                db=db,
                session=session,
                user_id=user_id,
                user_message=user_message,
                sop_skill_id=normalized_sop_skill_id,
                exclude_message_id=user_msg.id,
                preloaded_memory_profile=memory_profile,
                preloaded_memory_system_prompt=memory_system_prompt,
            )
            turn_trace = skill_trace or {}
            final_selected_skill_family = str(
                skill_trace.get("selected_skill_family") or final_selected_skill_family
            )
            final_selected_skill = str(skill_trace.get("selected_skill") or final_selected_skill)
            final_skill_name = skill_trace.get("skill_name") or final_skill_name
            final_analysis_mode = str(skill_trace.get("analysis_mode") or final_analysis_mode)
            final_execution_policy = str(
                skill_trace.get("execution_policy") or final_execution_policy
            )

            if skill_trace.get("hitl_pending"):
                context_window = await refresh_session_context_metrics(db, session)
                context_window = enrich_context_window(context_window, session.id)
                await db.commit()
                sc = skill_trace.get("skill_confirm") or {}
                yield json.dumps(
                    {
                        "type": "skill_confirm",
                        "session_id": session.id,
                        "options": sc.get("options", []),
                        "reasoning": sc.get("reasoning", ""),
                        "resolved_query": sc.get("resolved_query", ""),
                        "confidence": sc.get("confidence", 0),
                    },
                    ensure_ascii=False,
                )
                yield json.dumps(
                    {
                        "type": "done",
                        "session_id": session.id,
                        "awaiting_skill_confirm": True,
                        "running_summary": session.running_summary or "",
                        "running_summary_mode": session.running_summary_mode or "",
                        "context_window": _context_window_to_payload(context_window),
                    },
                    ensure_ascii=False,
                )
                return

            if skill_reply_text is not None:
                skill_reply_text = await _prepare_reply_for_user(skill_reply_text, user_id=user_id, db=db)
                logger.info(
                    "[chat-skill] stream executed: session=%s skill=%s mode=%s",
                    session.id,
                    skill_trace.get("selected_skill"),
                    "skill-stream",
                )
                log_reply_completed(
                    mode="skill-stream",
                    session_id=session.id,
                    user_id=user_id,
                    selected_skill_family=skill_trace.get("selected_skill_family"),
                    selected_skill=skill_trace.get("selected_skill"),
                    skill_name=skill_trace.get("skill_name"),
                    analysis_mode=skill_trace.get("analysis_mode"),
                    execution_policy=skill_trace.get("execution_policy"),
                )
                if settings.expose_plan_preview_to_user:
                    executor_events = []
                    executor_payload = skill_trace.get("executor") if isinstance(skill_trace.get("executor"), dict) else {}
                    if isinstance(executor_payload, dict):
                        executor_events = list(executor_payload.get("step_status_events") or [])
                    for event in executor_events:
                        if not isinstance(event, dict):
                            continue
                        frame_type = event.get("type")
                        if frame_type == "plan_preview":
                            yield json.dumps(
                                {
                                    "type": "plan_preview",
                                    "session_id": session.id,
                                    "plan_id": event.get("plan_id") or "",
                                    "items": event.get("items") or [],
                                },
                                ensure_ascii=False,
                            )
                        elif frame_type == "step_status":
                            yield json.dumps(
                                {
                                    "type": "step_status",
                                    "session_id": session.id,
                                    "plan_id": event.get("plan_id") or "",
                                    "step_id": event.get("step_id") or "",
                                    "tool_name": event.get("tool_name") or "",
                                    "status": event.get("status") or "",
                                },
                                ensure_ascii=False,
                            )
                        elif frame_type == "verification_summary":
                            verification = event.get("verification") if isinstance(event.get("verification"), dict) else {}
                            yield json.dumps(
                                {
                                    "type": "verification_summary",
                                    "session_id": session.id,
                                    "plan_id": event.get("plan_id") or "",
                                    "status": verification.get("status") or "",
                                    "evidence_score": verification.get("evidence_score") or 0,
                                    "allowed_claim_level": verification.get("allowed_claim_level") or "",
                                    "missing_dimensions": verification.get("missing_dimensions") or [],
                                },
                                ensure_ascii=False,
                            )
                for chunk in _chunk_text(skill_reply_text):
                    yield chunk

                _record_route_runtime_with_log(
                    session_id=session.id,
                    user_message=user_message,
                    route_trace=turn_trace,
                    reply_text=skill_reply_text,
                )
                _skill_route_summary = _build_route_summary(turn_trace)
                plan_artifact, skill_artifact, verification_artifact, allowed_claim_level = _trace_plan_artifacts(turn_trace)
                ai_msg = Message(
                    session_id=session.id,
                    role="assistant",
                    content=skill_reply_text,
                    token_count=count_message_tokens("assistant", skill_reply_text)[0],
                    route_summary_json=_persistable_route_summary(_skill_route_summary),
                    plan_artifact_json=plan_artifact,
                    skill_artifact_json=skill_artifact,
                    verification_json=verification_artifact,
                    allowed_claim_level=allowed_claim_level,
                )
                db.add(ai_msg)
                session.turn_count = (session.turn_count or 0) + 1
                session.updated_at = datetime.utcnow()
                await db.flush()
                await _apply_route_entities_to_stm_with_log(
                    db=db,
                    session=session,
                    user_message=user_message,
                    route_trace=turn_trace,
                )
                logger.info(
                    "[STM-chat] 旧异步 STM 链路已停用: session=%s user_msg=%s assistant_msg=%s",
                    session.id,
                    int(user_msg.id),
                    int(ai_msg.id),
                )
                context_window = await refresh_session_context_metrics(db, session)
                context_window = enrich_context_window(context_window, session.id)
                await db.commit()

                if settings.enable_memory and user_id:
                    with trace_span(
                        "memory_write_enqueue",
                        stage="memory",
                        data={"memory_enabled": True, "session_id": session.id, "turn_index": session.turn_count},
                    ):
                        asyncio.create_task(maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))
                        log_memory_enqueue(
                            session_id=session.id,
                            user_id=user_id,
                            queued=True,
                            turn_index=session.turn_count,
                        )
                else:
                    with trace_span(
                        "memory_write_enqueue",
                        stage="memory",
                        data={
                            "memory_enabled": bool(settings.enable_memory),
                            "session_id": session.id,
                            "turn_index": session.turn_count,
                            "enqueue_skipped_reason": "memory_disabled" if not settings.enable_memory else "missing_user_id",
                        },
                    ):
                        log_memory_enqueue(
                            session_id=session.id,
                            user_id=user_id,
                            queued=False,
                            turn_index=session.turn_count,
                            enqueue_skipped_reason="memory_disabled" if not settings.enable_memory else "missing_user_id",
                        )

                yield json.dumps(
                    {
                        "type": "context_update",
                        "session_id": session.id,
                        "context_window": _context_window_to_payload(context_window),
                    },
                    ensure_ascii=False,
                )
                if _skill_route_summary:
                    yield json.dumps(
                        {
                            "type": "trace_summary",
                            "session_id": session.id,
                            "route_summary": _skill_route_summary,
                        },
                        ensure_ascii=False,
                    )

                yield json.dumps({
                    "type": "done",
                    "session_id": session.id,
                    "running_summary": session.running_summary or "",
                    "running_summary_mode": session.running_summary_mode or "",
                    "context_window": _context_window_to_payload(context_window),
                }, ensure_ascii=False)
                return

            # Phase 3：对话流式模式也注入 LTM 用户画像
            # 流式调用 LLM
            llm = _get_llm()
            reply_chunks = []

            print(f"[chat-stream] session={session.id[:8]} 开始流式输出...")
            logger.info(f"[chat-stream] 开始流式输出: session={session.id}")

            stream_attempted_fallback = False
            while True:
                lc_messages = await _build_fallback_chat_messages(
                    db,
                    session,
                    memory_system_prompt=memory_system_prompt,
                )
                try:
                    async for chunk in llm.astream(lc_messages):
                        token = chunk.content if hasattr(chunk, "content") else str(chunk)
                        if token:
                            reply_chunks.append(token)
                            yield token
                    break
                except Exception as exc:
                    # 流式一旦已经向客户端发送过内容，就不能安全重试，只能原样抛出。
                    if reply_chunks or stream_attempted_fallback or not _is_context_overflow_error(exc):
                        raise
                    recovered = await _force_overflow_recovery_compaction(
                        db,
                        session,
                        user_message=user_message,
                        exc=exc,
                    )
                    if not recovered:
                        raise
                    stream_attempted_fallback = True
                    reply_chunks = []
                    continue

            reply_text = "".join(reply_chunks)
            final_selected_skill = "fallback"
            final_analysis_mode = "general_chat"
            log_reply_completed(
                mode="fallback-stream",
                session_id=session.id,
                user_id=user_id,
                selected_skill_family="fallback",
                selected_skill="fallback",
                analysis_mode="general_chat",
                execution_policy="agentic",
            )

            # Phase 3: 流式模式也要解析 LLM 回复中的 <action> 并更新画像
            if settings.enable_memory and user_id:
                reply_text = await _prepare_reply_for_user(reply_text, user_id=user_id, db=db)

            _record_route_runtime_with_log(
                session_id=session.id,
                user_message=user_message,
                route_trace=turn_trace,
                reply_text=reply_text,
            )

            route_summary = _build_route_summary(turn_trace)

            # 保存 assistant 消息（FIX-8: persist user-facing route summary）
            ai_msg = Message(
                session_id=session.id,
                role="assistant",
                content=reply_text,
                token_count=count_message_tokens("assistant", reply_text)[0],
                route_summary_json=_persistable_route_summary(route_summary),
            )
            db.add(ai_msg)
            session.turn_count = (session.turn_count or 0) + 1
            session.updated_at = datetime.utcnow()
            await db.flush()
            await _apply_route_entities_to_stm_with_log(
                db=db,
                session=session,
                user_message=user_message,
                route_trace=turn_trace,
            )
            logger.info(
                "[STM-chat] 旧异步 STM 链路已停用: session=%s user_msg=%s assistant_msg=%s",
                session.id,
                int(user_msg.id),
                int(ai_msg.id),
            )

            print(
                f"[chat-stream] 流式完成: session={session.id[:8]} "
                f"turn={session.turn_count} reply={len(reply_text)}字"
            )
            logger.info(
                f"[chat-stream] 完成: session={session.id}, "
                f"turn={session.turn_count}, reply_len={len(reply_text)}"
            )

            context_window = await refresh_session_context_metrics(db, session)
            context_window = enrich_context_window(context_window, session.id)
            await db.commit()

            if settings.enable_memory and user_id:
                with trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={"memory_enabled": True, "session_id": session.id, "turn_index": session.turn_count},
                ):
                    asyncio.create_task(maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))
                    log_memory_enqueue(
                        session_id=session.id,
                        user_id=user_id,
                        queued=True,
                        turn_index=session.turn_count,
                    )
            else:
                with trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={
                        "memory_enabled": bool(settings.enable_memory),
                        "session_id": session.id,
                        "turn_index": session.turn_count,
                        "enqueue_skipped_reason": "memory_disabled" if not settings.enable_memory else "missing_user_id",
                    },
                ):
                    log_memory_enqueue(
                        session_id=session.id,
                        user_id=user_id,
                        queued=False,
                        turn_index=session.turn_count,
                        enqueue_skipped_reason="memory_disabled" if not settings.enable_memory else "missing_user_id",
                    )

            yield json.dumps(
                {
                    "type": "context_update",
                    "session_id": session.id,
                    "context_window": _context_window_to_payload(context_window),
                },
                ensure_ascii=False,
            )
            if route_summary:
                yield json.dumps(
                    {
                        "type": "trace_summary",
                        "session_id": session.id,
                        "route_summary": route_summary,
                        },
                        ensure_ascii=False,
                    )

            yield json.dumps({
                "type": "done",
                "session_id": session.id,
                "running_summary": session.running_summary or "",
                "running_summary_mode": session.running_summary_mode or "",
                "context_window": _context_window_to_payload(context_window),
            }, ensure_ascii=False)

        except Exception as exc:
            final_status = "error"
            logger.error(f"[chat-stream] 流式输出失败: {exc}", exc_info=True)
            print(f"[chat-stream] 流式输出失败: {exc}")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
        finally:
            log_trace_finished(
                status=final_status,
                duration_ms=round((time.perf_counter() - trace_started) * 1000, 2),
                metrics=_trace_root_metrics(turn_trace),
                refs=_trace_root_refs(turn_trace),
                **_trace_root_payload(
                    final_status=final_status,
                    selected_skill_family=final_selected_skill_family,
                    selected_skill=final_selected_skill,
                    skill_name=final_skill_name,
                    analysis_mode=final_analysis_mode,
                    execution_policy=final_execution_policy,
                    skill_trace=turn_trace,
                ),
            )


# ─────────────────────────────────────────────────────────────
# Phase 3 LTM 辅助函数
# ─────────────────────────────────────────────────────────────

def _build_memory_system_prompt(profile: dict, semantic_memories: list) -> str:
    """
    将 memory_context 构建为对话模式的 system prompt 注入段。
    与 summary_agent._build_memory_context_prompt 格式保持一致。
    """
    if not profile and not semantic_memories:
        return ""

    has_profile = any(
        v is not None and v != [] and v != {}
        for v in profile.values()
    )
    if not has_profile and not semantic_memories:
        return ""

    profile_lines = []

    risk_map = {
        "conservative": "保守", "moderate": "稳健", "balanced": "平衡",
        "aggressive": "进取", "speculative": "激进",
    }
    horizon_map = {
        "ultra_short": "超短线", "short": "短线", "swing": "波段", "long": "中长线",
    }

    rl = profile.get("risk_level")
    if rl:
        profile_lines.append(f"风险偏好：{risk_map.get(rl, rl)}")

    hz = profile.get("investment_horizon")
    if hz:
        profile_lines.append(f"持有周期：{horizon_map.get(hz, hz)}")

    ret_min = profile.get("expected_return_min")
    ret_max = profile.get("expected_return_max")
    if ret_min is not None:
        if ret_max is not None:
            profile_lines.append(f"期望收益：{ret_min}%~{ret_max}%")
        else:
            profile_lines.append(f"期望收益：≥{ret_min}%")

    sectors = profile.get("sectors", [])
    if sectors:
        profile_lines.append(f"关注板块：{', '.join(sectors[:5])}")

    constraints = profile.get("constraints", [])
    if constraints:
        profile_lines.append(f"约束：{', '.join(constraints[:3])}")

    if not profile_lines and not semantic_memories:
        return ""

    parts = ["【用户投资画像（参考，不覆盖实时数据）】"]
    parts.extend(profile_lines)

    if semantic_memories:
        semantic_texts = [m.get("text", "") for m in semantic_memories if m.get("text")]
        if semantic_texts:
            parts.append(f"历史偏好线索：{'; '.join(semantic_texts[:2])}")

    return "\n".join(parts)


async def maybe_update_ltm_from_chat(
    session_id: str,
    user_id: str,
    turn_count: int,
) -> None:
    """
    对话后台 LTM 更新函数（非阻塞，由 asyncio.create_task 调用）。

    触发条件（满足任一）：
    1. 未处理的 user 消息 >= _LTM_TRIGGER_MSG_COUNT，且距上次写入超过 MIN_LTM_INTERVAL
    2. turn_count 是 STM 压缩轮次（turn_count % 10 == 0），摘要质量最高

    P3 重构逻辑：
    1. 入队前先调用 profile_extractor 做画像要素抽取（A 类结构化 + B 类回复风格事实）
    2. 只在 has_profile_signal=True 时才入队 Mem0
    3. 对抽取到的结构化字段，直接更新 user_invest_profiles（快速生效）
    4. 入队 Mem0 的为 build_fact_messages 生成的高维度事实字符串（非原始对话），metadata 含 extracted_fields / mem0_infer=False
    """
    if not settings.enable_memory:
        return
    if not bool(settings.enable_chat_ltm_extract):
        logger.debug(
            "[LTM-chat] skip: ENABLE_CHAT_LTM_EXTRACT=false session=%s turn=%s",
            session_id,
            turn_count,
        )
        return

    try:
        from src.memory.memory_service import MemoryService
        from backend.services.profile_extractor import extract_profile_updates
        from backend.db.database import AsyncSessionFactory

        async with AsyncSessionFactory() as db:
            # 查找未处理的 user/assistant 消息
            result = await db.execute(
                select(Message)
                .where(
                    Message.session_id == session_id,
                    Message.used_for_ltm == False,  # noqa: E712
                    Message.role.in_(["user", "assistant"]),
                )
                .order_by(Message.created_at)
                .limit(10)
            )
            pending_msgs = list(result.scalars().all())

            user_msgs_count = sum(1 for m in pending_msgs if m.role == "user")

            # 触发条件判断
            trigger_by_count = user_msgs_count >= _LTM_TRIGGER_MSG_COUNT
            trigger_by_compress = (turn_count > 0 and turn_count % 10 == 0)

            if not trigger_by_count and not trigger_by_compress:
                logger.debug(
                    f"[LTM-chat] 未触发更新: user_msgs={user_msgs_count}, "
                    f"turn_count={turn_count}"
                )
                return

            # 检查 MIN_LTM_INTERVAL（仅对 trigger_by_count 路径生效）
            if trigger_by_count and not trigger_by_compress:
                from sqlalchemy import text
                last_ltm = await db.execute(
                    text(
                        "SELECT MAX(created_at) FROM ltm_write_tasks "
                        "WHERE user_id = :uid AND task_type = 'add_conversation'"
                    ),
                    {"uid": user_id},
                )
                last_ltm_time = last_ltm.scalar()
                if last_ltm_time:
                    try:
                        if isinstance(last_ltm_time, str):
                            from datetime import datetime as _dt
                            last_ltm_dt = _dt.fromisoformat(last_ltm_time)
                        else:
                            last_ltm_dt = last_ltm_time
                        elapsed = (datetime.utcnow() - last_ltm_dt).total_seconds()
                        if elapsed < _MIN_LTM_INTERVAL_SEC:
                            logger.debug(
                                f"[LTM-chat] 距上次写入仅 {elapsed:.0f}s < {_MIN_LTM_INTERVAL_SEC}s，跳过"
                            )
                            return
                    except Exception:
                        pass  # 时间解析失败，继续触发

            # ── 获取 running_summary ─────────────────────────────
            session_result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session_obj = session_result.scalar_one_or_none()
            running_summary = (session_obj.running_summary or "") if session_obj else ""

            # ── P3 新增：画像要素抽取 ────────────────────────────
            messages_for_extract = [
                {"role": m.role, "content": m.content[:800]}
                for m in pending_msgs
            ]
            extraction = await extract_profile_updates(
                messages=messages_for_extract,
                running_summary=running_summary,
            )

            # ── 结构化字段直写 DB（快速生效） ────────────────────
            if extraction.get("has_profile_signal") and extraction.get("updates"):
                for update in extraction["updates"]:
                    field = update.get("field")
                    value = update.get("value")
                    if field and value is not None:
                        try:
                            await MemoryService.update_profile_field(
                                user_id=user_id,
                                field=field,
                                value=value,
                                source="chat_inferred",
                                db_session=db,
                            )
                            logger.info(
                                f"[LTM-chat] 画像直写: {field}={value} "
                                f"(evidence: {update.get('evidence', '')[:60]})"
                            )
                        except Exception as uf_exc:
                            logger.warning(f"[LTM-chat] 画像字段写入失败: {field}: {uf_exc}")

            # ── 语义增强入队（Mem0）：只在有画像信号时入队 ────────
            # 发给 Mem0 的是【高维度事实字符串】，包含：
            #   A 类：结构化投资画像事实（来自 extraction["updates"]）
            #   B 类：回复风格偏好事实（来自 extraction["style_facts"]）
            if extraction.get("has_profile_signal"):
                from backend.services.profile_extractor import build_fact_messages
                fact_messages = build_fact_messages(
                    extraction.get("updates", []),
                    extraction.get("style_facts", []),
                )

                if fact_messages:
                    msg_ids = [str(m.id) for m in pending_msgs]
                    extracted_fields = [u["field"] for u in extraction.get("updates", [])]
                    style_count = len(extraction.get("style_facts", []))
                    metadata = {
                        "source": "chat_inferred",
                        "session_id": session_id,
                        "evidence_ref": ",".join(msg_ids),
                        "active": True,
                        "updated_by": "llm",
                        "confidence": 0.7,
                        "mem0_infer": False,
                        "extracted_fields": extracted_fields,
                    }

                    await MemoryService.enqueue_add_conversation(
                        user_id=user_id,
                        messages=fact_messages,
                        metadata=metadata,
                        db_session=db,
                    )

                    trigger_reason = "count阈值" if trigger_by_count else "compress轮次"
                    print(
                        f"[LTM-chat] 事实入队: session={session_id[:8]}..., "
                        f"A类fields={extracted_fields}, B类style={style_count}条, "
                        f"总facts={len(fact_messages)}, 触发={trigger_reason}"
                    )
                    logger.info(
                        f"[LTM-chat] 入队高维度事实: session={session_id}, user={user_id}, "
                        f"facts={len(fact_messages)}, A={extracted_fields}, "
                        f"B={extraction.get('style_facts', [])}, trigger={trigger_reason}"
                    )
            else:
                logger.debug(
                    f"[LTM-chat] 对话无画像信号，跳过 Mem0 入队: session={session_id[:8]}..."
                )
                print(
                    f"[LTM-chat] 对话无画像信号，跳过 Mem0 入队: session={session_id[:8]}..."
                )

            # 批量标记 used_for_ltm=True（无论是否有信号，都标记避免重复处理）
            for msg in pending_msgs:
                msg.used_for_ltm = True
            await db.commit()

    except Exception as exc:
        logger.error(f"[LTM-chat] maybe_update_ltm_from_chat 异常（不影响主流程）: {exc}", exc_info=True)
        print(f"[LTM-chat] LTM 更新异常（不影响主流程）: {exc}")


async def _extract_from_summary(session_id: str, user_id: str, summary: str) -> None:
    """
    P3 新增：从 STM 压缩摘要中提取画像要素（非阻塞后台任务）。

    摘要质量远高于原始对话，是提取画像的最佳时机。
    仅在 ENABLE_MEMORY=true 且摘要非空时执行。
    同时将高维度事实字符串入队 Mem0，保持语义增强层与 DB 一致。
    """
    if not settings.enable_memory:
        return
    if not bool(settings.enable_summary_ltm_extract):
        logger.debug(
            "[LTM-summary] skip: ENABLE_SUMMARY_LTM_EXTRACT=false session=%s",
            session_id,
        )
        return
    if not summary or not user_id:
        return
    try:
        from backend.services.profile_extractor import extract_profile_updates, build_fact_messages
        from src.memory.memory_service import MemoryService
        from backend.db.database import AsyncSessionFactory

        extraction = await extract_profile_updates(
            messages=[{"role": "system", "content": summary}],
            running_summary="",
        )

        if not extraction.get("has_profile_signal"):
            logger.debug(f"[LTM-summary] 摘要中无画像信号: session={session_id[:8]}...")
            return

        updates = extraction.get("updates") or []
        style_facts = extraction.get("style_facts") or []
        fact_messages = build_fact_messages(updates, style_facts)

        async with AsyncSessionFactory() as db:
            # A 类：写入结构化字段到 DB（可无，仅 B 类 style_facts 时跳过）
            for update in updates:
                field = update.get("field")
                value = update.get("value")
                if field and value is not None:
                    await MemoryService.update_profile_field(
                        user_id=user_id,
                        field=field,
                        value=value,
                        source="chat_inferred",
                        db_session=db,
                    )

            # A+B 类事实入队 Mem0（含仅有「用户偏好：…」的 B 类）
            if fact_messages:
                metadata = {
                    "source": "chat_inferred",
                    "session_id": session_id,
                    "active": True,
                    "updated_by": "llm",
                    "confidence": 0.75,
                    "mem0_infer": False,
                    "extracted_fields": [u["field"] for u in updates],
                }
                await MemoryService.enqueue_add_conversation(
                    user_id=user_id,
                    messages=fact_messages,
                    metadata=metadata,
                    db_session=db,
                )

            await db.commit()

        extracted_fields = [u["field"] for u in updates]
        logger.info(
            f"[LTM-summary] 从摘要中抽取画像: session={session_id[:8]}..., "
            f"fields={extracted_fields}, style_facts={len(style_facts)}, facts={len(fact_messages)}"
        )
        print(
            f"[LTM-summary] 摘要画像抽取: session={session_id[:8]}..., "
            f"fields={extracted_fields}, B类={len(style_facts)}, facts={len(fact_messages)}"
        )

    except Exception as exc:
        logger.warning(f"[LTM-summary] 摘要画像抽取失败（不影响主流程）: {exc}")


async def _handle_profile_action_in_reply(reply_text: str, user_id: str, db) -> None:
    """
    解析 LLM 回复中的 <action>...</action> 标签，提取结构化 profile update 指令。
    调用 MemoryService.update_profile_and_enqueue（source=explicit_correction）。
    """
    import re
    import json as _json

    pattern = r'<action>(.*?)</action>'
    matches = re.findall(pattern, reply_text, re.DOTALL)

    for match in matches:
        try:
            action_data = _json.loads(match.strip())
            if action_data.get("action") != "update_profile":
                continue
            field = action_data.get("field", "")
            value = action_data.get("value")

            if not field or value is None:
                continue

            # 字段合法性校验
            allowed = {"risk_level", "sectors", "investment_horizon", "response_pref"}
            if field not in allowed:
                continue

            normalized = _normalize_profile_action(field, value)
            if not normalized:
                logger.info(
                    f"[LTM-chat] action 值不合法/无法映射，已忽略: user={user_id}, field={field}, value={value}"
                )
                continue
            field, value = normalized

            from src.memory.memory_service import MemoryService
            from src.memory.mem0_schema import MemorySource

            await MemoryService.update_profile_and_enqueue(
                user_id=user_id,
                field=field,
                value=value,
                source=MemorySource.EXPLICIT_CORR,
                db_session=db,
            )
            print(
                f"[LTM-chat] 检测到用户主动纠正，更新画像: "
                f"field={field}, value={value}, source=explicit_correction"
            )
            logger.info(
                f"[LTM-chat] explicit_correction: user={user_id}, field={field}, value={value}"
            )

        except Exception as exc:
            logger.debug(f"[LTM-chat] _handle_profile_action 解析失败: {exc}")


async def _handle_profile_action_in_user_message(db: AsyncSession, user_id: str, user_message: str) -> str:
    """
    支持用户直接发送 JSON action 来更新画像（用于“我已经按格式贴了 action，但前端没点亮”的场景）。

    输入示例：
      {"action":"update_profile","field":"sectors","value":["科技/半导体"]} 前端并没有点亮

    行为：
    - 若识别到 action，先更新画像（source=explicit_correction），再从 user_message 中剔除该 JSON 块，
      返回剩余文本继续走正常对话（避免 LLM 被 JSON 干扰）。
    - 若未识别到，原样返回。
    """
    import json as _json

    def _extract_json_candidates(text: str) -> list[str]:
        # 简易花括号配对提取，支持 message 中夹杂中文/空格
        out: list[str] = []
        stack = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if stack == 0:
                    start = i
                stack += 1
            elif ch == "}":
                if stack > 0:
                    stack -= 1
                    if stack == 0 and start != -1:
                        out.append(text[start : i + 1])
                        start = -1
        return out

    candidates = _extract_json_candidates(user_message)
    if not candidates:
        return user_message

    for blob in candidates:
        try:
            data = _json.loads(blob)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("action") != "update_profile":
            continue
        field = data.get("field")
        value = data.get("value")
        if not field:
            continue

        normalized = _normalize_profile_action(str(field), value)
        if not normalized:
            logger.info(
                f"[LTM-chat] user_action 值不合法/无法映射，已忽略: user={user_id}, field={field}, value={value}"
            )
            continue
        field, value = normalized

        try:
            await MemoryService.update_profile_and_enqueue(
                user_id=user_id,
                field=str(field),
                value=value,
                source=MemorySource.EXPLICIT_CORRECTION,
                db_session=db,
            )
            logger.info(f"[LTM-chat] user_action 更新画像: user={user_id}, field={field}")
            print(f"[LTM-chat] user_action 更新画像: user={user_id[:8]}..., field={field}")
        except Exception as exc:
            logger.warning(f"[LTM-chat] user_action 更新画像失败（不影响对话）: {exc}")
            return user_message

        # 剔除该 JSON 块（只去掉一次），保留剩余自然语言
        cleaned = user_message.replace(blob, "").strip()
        return cleaned

    return user_message
