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
import os
import re
from datetime import datetime
import time
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Message, Session, User
from backend.config import settings
from backend.services import memory_service as _memory_svc
from backend.services.chat.artifacts import (
    _apply_route_entities_to_stm_with_log,
    _build_route_summary,
    _persistable_route_summary,
    _profile_to_route_summary,
    _profile_to_summary,
    _prepare_reply_for_user,
    _record_route_runtime_with_log,
    _route_summary_skill_label,
    _route_trace_to_summary_entities,
    _strip_profile_actions_from_reply,
    _trace_query_summary,
    _trace_root_metrics,
    _trace_root_payload,
    _trace_root_refs,
)
from backend.services.chat.constants import (
    InvalidSopSkillError,
    _ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE,
    _chunk_text,
    _context_window_to_payload,
    _is_context_overflow_error,
    _normalize_profile_action,
    _unique_strings,
)
from backend.services.chat.preflight import (
    _extract_model_text,
    _get_llm,
    _prepare_chat_preflight_inputs,
    _run_chat_preflight_compaction,
    _serialize_prompt_payload,
)
from backend.services.chat.memory_bridge import (
    _LTM_TRIGGER_MSG_COUNT,
    _MIN_LTM_INTERVAL_SEC,
    _build_memory_system_prompt,
    _extract_from_summary,
    _handle_profile_action_in_reply,
    _handle_profile_action_in_user_message,
    maybe_update_ltm_from_chat,
)
from backend.services.chat.orchestrator import chat_single_turn
from backend.services.chat.route_bridge import (
    _apply_hitl_choice_to_route_dict,
    _build_broad_skill_confirm_options,
    _build_skill_confirm_options,
    _build_skill_confirm_options_from_trace,
    _build_skill_route_context,
    _ensure_skill_runtime_ready,
    _load_memory_context_for_chat,
    _resolve_entity_hint_for_route,
    _resolver_hint_payload,
    _resolver_hint_to_prompt_block,
    _should_offer_skill_hitl,
    _sop_execution_policy_for_name,
    confirm_skill_route,
    list_discoverable_sop_skills,
    normalize_requested_sop_skill_id,
    validate_requested_sop_skill_id,
)
from backend.services.chat.session import (
    _RECENT_MSG_LIMIT,
    _build_fallback_chat_messages,
    _force_overflow_recovery_compaction,
    compress_if_needed,
    delete_session,
    get_or_create_session,
    get_session_messages,
    get_session_summaries,
    get_sessions,
    rename_session,
)
from backend.services.chat.skill_pipeline import (
    _apply_skill_query_rewrite,
    _executor_qualifies_for_evidence_retry,
    _resolve_sop_skill_id,
    _run_post_rewrite_extractors_if_enabled,
    _run_skill_chat_if_enabled,
    _trace_plan_artifacts,
    summarize_fallback_reply,
    summarize_sop_reply,
    summarize_tushare_reply,
)
from backend.services.chat.stream import stream_chat_single_turn
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
    should_run_preflight_summary_compaction,
)
from backend.services.token_counter import count_message_tokens
from backend.integrations.agent_runtime.chat_runtime import (
    MemoryService,
    MemorySource,
    RewriteContextPacket,
    TushareClient,
    _build_executor_route_trace,
    _load_skill_doc_sections,
    build_fallback_synthesis_prompt,
    build_sop_synthesis_prompt,
    build_tushare_synthesis_prompt,
    configure_tushare_client_factory,
    execute_skill,
    execute_tushare_plan,
    extract_constraints,
    extract_reply_preference,
    get_skill_registry,
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
    registry_execution_policy_for_skill,
    resolve_authoritative_entity,
    rewrite_for_fallback,
    rewrite_for_sop,
    rewrite_for_tushare,
    rewrite_for_tushare_v2,
    rewrite_query_for_skill,
    route_chat_skill,
    run_sop_v2_pipeline,
    run_tushare_v2_pipeline,
    skill_route_decision_from_dict,
    skill_trace_context,
    setup_logger,
    trace_span,
    user_explicit_sop_decision,
)
from backend.integrations.agent_runtime.env import agent_root

logger = setup_logger("chat_service", log_dir=str(agent_root() / "logs"))


def _get_memory_service_cls():
    return MemoryService


def _get_memory_source_cls():
    return MemorySource

# ─────────────────────────────────────────────────────────────
# 常量配置
# ─────────────────────────────────────────────────────────────
_skill_runtime_checked = False

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


def _resolve_session_summary_contexts(session: Session) -> tuple[dict[str, Any], str, str]:
    if not settings.enable_stm:
        return {}, "", ""
    payload = resolve_session_rolling_payload(session)
    route_slice_text = format_route_active_entities_context(payload)
    answer_policy_context = format_answer_policy_context(payload)
    return payload, route_slice_text, answer_policy_context


_EXPLICIT_SKILL_INTENT_RE = re.compile(
    r"(使用\s*skills?|用\s*skills?|走\s*skills?|调用\s*skills?|"
    r"请\s*用\s*技能|使用\s*技能|必须\s*用\s*技能|financial[-\s]?sop|"
    r"工具\s*分析|结构化\s*技能|走\s*工具)",
    re.IGNORECASE,
)


def _user_explicit_skill_intent(user_message: str) -> bool:
    """用户明确要求走技能/工具链路（与路由是否命中无关）。"""
    return bool(_EXPLICIT_SKILL_INTENT_RE.search(user_message or ""))
