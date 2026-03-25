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
import sys
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Message, Session, SessionSummary, User
from backend.config import settings
from backend.services import memory_service as _memory_svc

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.utils.logging_config import setup_logger  # noqa: E402
from src.agents.skill_executor_node import execute_skill  # noqa: E402
from src.agents.skill_router_node import route_chat_skill  # noqa: E402
from src.skills.skill_registry import get_skill_registry  # noqa: E402
from src.tools.skill_trace import log_model_stage, log_reply_completed, log_router_decision  # noqa: E402
from src.tools.tushare_client import TushareClient, configure_tushare_client_factory  # noqa: E402

logger = setup_logger("chat_service", log_dir=str(_AGENT_ROOT / "logs"))

# ─────────────────────────────────────────────────────────────
# 常量配置
# ─────────────────────────────────────────────────────────────
_RECENT_MSG_LIMIT = 12          # Phase 1/2 保留最近 N 条消息作为上下文
_STM_COMPRESS_THRESHOLD = 10    # 对话模式 STM 压缩触发阈值（未压缩消息数）
_CHAT_STREAM_CHUNK_SIZE = 48
_skill_runtime_checked = False

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

# STM 压缩 Prompt（金融专版，与 stm_nodes.py 中一致）
_SUMMARIZE_CONVERSATION_PROMPT = """
你是一个金融对话摘要助手。请将以下对话历史压缩成精炼摘要，
严格保留以下关键信息，不得遗漏：

必须保留：
- 用户提到的所有股票代码/公司名称
- 用户明确表达的投资偏好（风险偏好、持有期限、关注板块）
- 用户提出的具体投资问题和关键约束
- 已生成报告的核心结论（股票代码、买入/持有/卖出建议、关键数值）

可以省略：
- 打招呼、寒暄等无实质内容的对话
- 重复表达同一意思的内容
- analyst 分析过程的中间步骤（只保留最终结论）

输出格式：纯文字段落，300字以内，使用中文。
"""


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


async def _load_memory_context_for_chat(
    db: AsyncSession,
    user_id: str,
    user_message: str,
) -> tuple[dict, str]:
    memory_profile = {}
    memory_system_prompt = ""
    if settings.enable_memory and user_id:
        try:
            ctx = await _memory_svc.get_memory_context_for_chat(user_id, user_message, db)
            memory_profile = ctx.get("profile", {})
            semantic_memories = ctx.get("semantic_memories", [])
            memory_system_prompt = _build_memory_system_prompt(memory_profile, semantic_memories)
            if memory_system_prompt:
                print(f"[LTM-chat] 注入用户画像到对话上下文 (user={user_id[:8]}...)")
                logger.info(
                    f"[LTM-chat] 注入 memory_context: user={user_id}, len={len(memory_system_prompt)}"
                )
        except Exception as exc:
            logger.warning(f"[LTM-chat] 读取画像失败（不影响对话）: {exc}")
    return memory_profile, memory_system_prompt


async def _build_skill_route_context(db: AsyncSession, session: Session) -> str:
    parts: list[str] = []
    if settings.enable_stm and session.running_summary:
        parts.append(f"running_summary:\n{session.running_summary[:600]}")

    if settings.enable_stm:
        history_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id, Message.is_compressed == False)  # noqa: E712
            .order_by(Message.created_at.desc())
            .limit(6)
        )
    else:
        history_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at.desc())
            .limit(6)
        )

    recent_messages = list(reversed(history_result.scalars().all()))
    if recent_messages:
        dialogue_lines = []
        for msg in recent_messages:
            role = "用户" if msg.role == "user" else "助手"
            dialogue_lines.append(f"{role}: {msg.content[:240]}")
        parts.append("recent_messages:\n" + "\n".join(dialogue_lines))
    return "\n\n".join(parts)


async def _run_skill_chat_if_enabled(
    *,
    db: AsyncSession,
    session: Session,
    user_id: str,
    user_message: str,
) -> tuple[str | None, dict, dict]:
    if not settings.enable_chat_skills:
        return None, {}, {}

    _ensure_skill_runtime_ready()
    memory_profile, memory_system_prompt = await _load_memory_context_for_chat(db, user_id, user_message)
    route_context = await _build_skill_route_context(db, session)
    route = await route_chat_skill(user_message, conversation_context=route_context)
    log_model_stage(
        stage="router",
        model=(route.arguments or {}).get("router_model"),
        execution_path="routing",
        session_id=session.id,
        user_id=user_id,
    )
    log_router_decision(
        selected_skill=route.selected_skill,
        confidence=route.confidence,
        why=route.why,
        needs_realtime_data=route.needs_realtime_data,
        needs_professional_analysis=route.needs_professional_analysis,
        analysis_mode=route.analysis_mode,
        router_model=(route.arguments or {}).get("router_model"),
        session_id=session.id,
        user_id=user_id,
    )
    logger.info(
        "[chat-skill] route=%s confidence=%.2f why=%s realtime=%s professional=%s mode=%s follow_up=%s",
        route.selected_skill,
        route.confidence,
        route.why,
        route.needs_realtime_data,
        route.needs_professional_analysis,
        route.analysis_mode,
        bool((route.arguments or {}).get("is_follow_up")),
    )

    if route.selected_skill == "fallback":
        return None, memory_profile, route.to_dict()

    result = await execute_skill(
        selected_skill=route.selected_skill,
        user_message=user_message,
        memory_context=memory_system_prompt,
        running_summary=session.running_summary or "",
        profile_summary=_profile_to_summary(memory_profile),
        session_id=session.id,
        user_id=user_id,
        route_trace=route.to_dict(),
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
    trace = route.to_dict()
    trace["executor"] = result.trace
    return result.reply_text, memory_profile, trace


def _chunk_text(text: str, chunk_size: int = _CHAT_STREAM_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


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
    return list(result.scalars().all())


async def get_session_messages(
    db: AsyncSession, session_id: str, user_id: str
) -> list[Message]:
    """获取会话完整消息历史（含已压缩消息，用于前端"查看完整历史"）。"""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        return []
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
async def compress_if_needed(db: AsyncSession, session_id: str) -> Optional[dict]:
    """
    检查并在必要时压缩对话历史（对话模式 STM）。

    触发条件：DB 中该会话的未压缩消息数 >= _STM_COMPRESS_THRESHOLD（10）。
    压缩逻辑：
      1. 调用 LLM + _SUMMARIZE_CONVERSATION_PROMPT → 新 running_summary
      2. 更新 sessions.running_summary / last_compress_at
      3. 将已压缩的消息打上 is_compressed=True 标记（保留原文）
    返回压缩结果 dict（压缩后），或 None（未触发压缩）。

    注意：此函数不使用 ExecutionLogger，仅通过 logger（setup_logger）记录日志。
    """
    if not settings.enable_stm:
        return None  # ENABLE_STM=false 时跳过

    # 查找未压缩消息
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.is_compressed == False)  # noqa: E712
        .order_by(Message.created_at)
    )
    uncompressed = list(result.scalars().all())

    if len(uncompressed) < _STM_COMPRESS_THRESHOLD:
        return None  # 未达阈值，不压缩

    print(
        f"\n[STM-chat] 会话 {session_id[:8]}... 未压缩消息数={len(uncompressed)}，"
        f"触发压缩（阈值={_STM_COMPRESS_THRESHOLD}）"
    )
    logger.info(
        f"[STM-chat] 触发压缩: session={session_id}, "
        f"uncompressed_count={len(uncompressed)}"
    )

    # 获取当前会话的旧 running_summary
    session_result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    old_summary = (session.running_summary or "") if session else ""

    # 保留最近 4 条消息不压缩（同 LangGraph 节点的 STM_KEEP_RECENT）
    keep_recent = 4
    msgs_to_compress = uncompressed[:-keep_recent] if len(uncompressed) > keep_recent else uncompressed

    # 统计本次压缩的用户/助手消息条数 + 时间轴范围（便于前端直观展示）
    compressed_user_count = sum(1 for m in msgs_to_compress if m.role == "user")
    compressed_assistant_count = sum(1 for m in msgs_to_compress if m.role == "assistant")
    start_message_id = min((m.id for m in msgs_to_compress), default=None)
    end_message_id = max((m.id for m in msgs_to_compress), default=None)
    start_created_at = msgs_to_compress[0].created_at if msgs_to_compress else None
    end_created_at = msgs_to_compress[-1].created_at if msgs_to_compress else None

    # 构建压缩输入文本
    compress_parts = []
    if old_summary.strip():
        compress_parts.append(f"【已有摘要】\n{old_summary}")
    for msg in msgs_to_compress:
        compress_parts.append(f"[{msg.role}]: {msg.content[:800]}")

    compress_input = "\n".join(compress_parts)

    # 统计总消息数（用于百分比展示）
    total_count_result = await db.execute(
        select(func.count(Message.id)).where(Message.session_id == session_id)
    )
    total_message_count = int(total_count_result.scalar() or 0)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _get_llm()
        lc_messages = [
            SystemMessage(content=_SUMMARIZE_CONVERSATION_PROMPT),
            HumanMessage(content=f"请压缩以下对话历史：\n\n{compress_input}")
        ]
        response = await llm.ainvoke(lc_messages)
        new_summary = response.content.strip()

        # 更新 sessions.running_summary
        if session:
            session.running_summary = new_summary
            session.last_compress_at = datetime.utcnow()

        # 标记已压缩消息
        compress_ids = {m.id for m in msgs_to_compress}
        for msg in uncompressed:
            if msg.id in compress_ids:
                msg.is_compressed = True

        # 写入摘要历史快照（用于“查看摘要历史”）
        # 注意：若 PostgreSQL 表尚未完成增量迁移（缺少新列），这里会触发 UndefinedColumnError。
        # 为避免影响主链路与流式会话，这里做降级：缺列时仅写入旧字段，保证压缩功能可用。
        snapshot = SessionSummary(
            session_id=session_id,
            summary=new_summary,
            compressed_message_count=len(msgs_to_compress),
            total_message_count=total_message_count,
            compressed_user_count=compressed_user_count,
            compressed_assistant_count=compressed_assistant_count,
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            start_created_at=start_created_at,
            end_created_at=end_created_at,
        )
        db.add(snapshot)

        try:
            await db.commit()
        except Exception as commit_exc:
            # 事务已失败，先 rollback
            try:
                await db.rollback()
            except Exception:
                pass

            msg = str(commit_exc)
            # 常见：asyncpg.exceptions.UndefinedColumnError: column "compressed_user_count" does not exist
            if "UndefinedColumnError" in msg or "does not exist" in msg:
                try:
                    from sqlalchemy import text
                    # 降级插入：仅写入旧字段（兼容旧表结构）
                    await db.execute(
                        text(
                            "INSERT INTO session_summaries "
                            "(session_id, summary, compressed_message_count, total_message_count, created_at) "
                            "VALUES (:sid, :summary, :cmc, :tmc, :now)"
                        ),
                        {
                            "sid": session_id,
                            "summary": new_summary,
                            "cmc": len(msgs_to_compress),
                            "tmc": total_message_count,
                            "now": datetime.utcnow(),
                        },
                    )
                    await db.commit()
                    snapshot = None  # 降级路径无 ORM id
                    logger.warning(
                        f"[STM-chat] session_summaries 缺少新列，已降级仅写旧字段（建议重启/迁移补列）: session={session_id}"
                    )
                except Exception as fallback_exc:
                    logger.error(
                        f"[STM-chat] 降级写 session_summaries 仍失败（不影响主流程）: {fallback_exc}",
                        exc_info=True,
                    )
                    return None
            else:
                logger.error(f"[STM-chat] commit 失败（不影响主流程）: {commit_exc}", exc_info=True)
                return None

        print(
            f"[STM-chat] 压缩完成：{len(msgs_to_compress)} 条消息 → "
            f"摘要 {len(new_summary)} 字"
        )
        logger.info(
            f"[STM-chat] 压缩完成: session={session_id}, "
            f"compressed={len(msgs_to_compress)}, summary_len={len(new_summary)}"
        )
        percent = int(round((len(msgs_to_compress) / total_message_count) * 100)) if total_message_count else 100
        return {
            "session_id": session_id,
            "summary": new_summary,
            "snapshot_id": getattr(snapshot, "id", None),
            "compressed_message_count": len(msgs_to_compress),
            "total_message_count": total_message_count,
            "percent": max(0, min(100, percent)),
        }

    except Exception as exc:
        logger.error(f"[STM-chat] 压缩失败（不影响主流程）: {exc}", exc_info=True)
        print(f"[STM-chat] 压缩失败（不影响主流程）: {exc}")
        return None


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


# ─────────────────────────────────────────────────────────────
# Phase 1 保留：chat_single_turn（同步返回，无流式）
# ─────────────────────────────────────────────────────────────
async def chat_single_turn(
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: Optional[str] = None,
) -> tuple[str, str, dict]:
    """
    执行单轮对话，返回 (reply, session_id, memory_profile)。
    Phase 2：STM 模式下加载 running_summary 前置上下文。
    Phase 3：LTM 模式下注入用户画像，并在回复后触发异步 LTM 更新。
    """
    session = await get_or_create_session(db, user_id, session_id)

    # Phase 3：支持用户直接发送 JSON action（而非由 LLM 输出 <action>）
    # 例如：{"action":"update_profile","field":"sectors","value":[...]}后面跟自然语言
    if settings.enable_memory and user_id:
        user_message = await _handle_profile_action_in_user_message(db, user_id, user_message)

    # 保存用户消息
    user_msg = Message(
        session_id=session.id,
        role="user",
        content=user_message,
    )
    db.add(user_msg)
    await db.flush()

    # 更新会话标题（取第一条用户消息前 30 字）
    if not session.title:
        session.title = user_message[:30]
        await db.flush()

    skill_reply_text, memory_profile, skill_trace = await _run_skill_chat_if_enabled(
        db=db,
        session=session,
        user_id=user_id,
        user_message=user_message,
    )

    reply_prepared = False
    if skill_reply_text is not None:
        reply_text = await _prepare_reply_for_user(skill_reply_text, user_id=user_id, db=db)
        reply_prepared = True
        logger.info(
            "[chat-skill] sync executed: session=%s skill=%s",
            session.id,
            skill_trace.get("selected_skill"),
        )
        log_reply_completed(
            mode="skill",
            session_id=session.id,
            user_id=user_id,
            selected_skill=skill_trace.get("selected_skill"),
            analysis_mode=skill_trace.get("analysis_mode"),
        )
    else:
        # ── Phase 3 LTM：读取用户画像，构建个性化 system prompt ─────
        memory_profile, memory_system_prompt = await _load_memory_context_for_chat(
            db, user_id, user_message
        )

        # 构建 LLM messages 上下文
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        lc_messages = [SystemMessage(content=_CHAT_SYSTEM_PROMPT)]

        # 注入 LTM 画像（ENABLE_MEMORY=true 且有实质内容时）
        if memory_system_prompt:
            lc_messages.append(SystemMessage(content=memory_system_prompt))

        # Phase 2 STM：若有 running_summary，前置注入
        if settings.enable_stm and session.running_summary:
            stm_hint = (
                f"【对话历史摘要（已压缩 {session.turn_count} 轮早期对话）】\n"
                f"{session.running_summary}\n\n以下是最近的对话记录："
            )
            lc_messages.append(SystemMessage(content=stm_hint))
            print(f"[STM-chat] 注入 running_summary（{len(session.running_summary)} 字）到上下文")
            logger.info(
                f"[STM-chat] 注入 running_summary: session={session.id[:8]}, "
                f"summary_len={len(session.running_summary)}"
            )

        # 加载最近消息（STM 模式只取未压缩的；非 STM 模式取最近 N 条）
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

        # 调用 LLM（同步返回）
        llm = _get_llm()
        response = await llm.ainvoke(lc_messages)
        reply_text = response.content
        log_reply_completed(
            mode="fallback",
            session_id=session.id,
            user_id=user_id,
            selected_skill="fallback",
            analysis_mode="general_chat",
        )

    # ── Phase 3 LTM：解析 LLM 回复中的显式 profile update action ──
    if settings.enable_memory and not reply_prepared:
        reply_text = await _prepare_reply_for_user(reply_text, user_id=user_id, db=db)

    # 保存 assistant 消息
    ai_msg = Message(
        session_id=session.id,
        role="assistant",
        content=reply_text,
    )
    db.add(ai_msg)

    # 更新会话统计
    session.turn_count = (session.turn_count or 0) + 1
    session.updated_at = datetime.utcnow()
    await db.commit()

    logger.info(
        f"[chat] session={session.id} turn={session.turn_count} "
        f"user_len={len(user_message)} reply_len={len(reply_text)}"
    )
    print(
        f"[chat] session={session.id[:8]} turn={session.turn_count} "
        f"user={len(user_message)}字 reply={len(reply_text)}字"
    )

    # Phase 2 STM：检查是否需要压缩（不阻塞返回）
    if settings.enable_stm:
        compress_result = await compress_if_needed(db, session.id)
        # P3 钩子：压缩成功后从高质量摘要中提取画像
        if compress_result and settings.enable_memory and user_id:
            asyncio.create_task(
                _extract_from_summary(
                    session_id=session.id,
                    user_id=user_id,
                    summary=compress_result.get("summary", ""),
                )
            )

    # Phase 3 LTM：非阻塞触发 LTM 更新（asyncio.create_task 后台执行）
    if settings.enable_memory and user_id:
        asyncio.create_task(
            maybe_update_ltm_from_chat(session.id, user_id, session.turn_count)
        )

    return reply_text, session.id, memory_profile


# ─────────────────────────────────────────────────────────────
# Phase 2 新增：stream_chat_single_turn（流式生成器）
# ─────────────────────────────────────────────────────────────
async def stream_chat_single_turn(
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: Optional[str] = None,
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

    # Phase 3：流式模式同样支持用户直接发送 JSON action
    if settings.enable_memory and user_id:
        user_message = await _handle_profile_action_in_user_message(db, user_id, user_message)

    # 保存用户消息
    user_msg = Message(session_id=session.id, role="user", content=user_message)
    db.add(user_msg)
    await db.flush()

    if not session.title:
        session.title = user_message[:30]
        await db.flush()

    # 通知前端会话 ID（新建会话时前端需要更新 currentSessionId）
    yield json.dumps({"type": "session_id", "session_id": session.id}, ensure_ascii=False)

    skill_reply_text, _, skill_trace = await _run_skill_chat_if_enabled(
        db=db,
        session=session,
        user_id=user_id,
        user_message=user_message,
    )
    if skill_reply_text is not None:
        skill_reply_text = await _prepare_reply_for_user(skill_reply_text, user_id=user_id, db=db)
        logger.info(
            "[chat-skill] stream executed: session=%s skill=%s",
            session.id,
            skill_trace.get("selected_skill"),
        )
        for chunk in _chunk_text(skill_reply_text):
            yield chunk

        ai_msg = Message(session_id=session.id, role="assistant", content=skill_reply_text)
        db.add(ai_msg)
        session.turn_count = (session.turn_count or 0) + 1
        session.updated_at = datetime.utcnow()
        await db.commit()

        if settings.enable_memory and user_id:
            asyncio.create_task(maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))

        if settings.enable_stm:
            yield json.dumps(
                {
                    "type": "compress_start",
                    "session_id": session.id,
                    "progress": 0,
                    "eta_seconds": 8,
                },
                ensure_ascii=False,
            )
            compress_start = datetime.utcnow()
            result = await compress_if_needed(db, session.id)
            compress_elapsed = max(1, int((datetime.utcnow() - compress_start).total_seconds()))
            if result:
                yield json.dumps(
                    {
                        "type": "compress_done",
                        "session_id": session.id,
                        "progress": 100,
                        "eta_seconds": 0,
                        "elapsed_seconds": compress_elapsed,
                        "snapshot_id": result.get("snapshot_id"),
                        "compressed_message_count": result.get("compressed_message_count"),
                        "total_message_count": result.get("total_message_count"),
                        "percent": result.get("percent"),
                    },
                    ensure_ascii=False,
                )
            else:
                yield json.dumps(
                    {
                        "type": "compress_skip",
                        "session_id": session.id,
                        "progress": 100,
                        "eta_seconds": 0,
                    },
                    ensure_ascii=False,
                )

        yield json.dumps({"type": "done", "session_id": session.id}, ensure_ascii=False)
        return

    # 构建上下文（与 chat_single_turn 逻辑保持一致，包含 LTM 画像注入）
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc_messages = [SystemMessage(content=_CHAT_SYSTEM_PROMPT)]

    # Phase 3：对话流式模式也注入 LTM 用户画像
    memory_system_prompt = ""
    if settings.enable_memory and user_id:
        try:
            ctx = await _memory_svc.get_memory_context_for_chat(user_id, user_message, db)
            memory_profile = ctx.get("profile", {})
            semantic_memories = ctx.get("semantic_memories", [])
            memory_system_prompt = _build_memory_system_prompt(memory_profile, semantic_memories)
            if memory_system_prompt:
                lc_messages.append(SystemMessage(content=memory_system_prompt))
                print(f"[LTM-stream] 注入用户画像到对话上下文 (user={user_id[:8]}...)")
                logger.info(
                    f"[LTM-stream] 注入 memory_context: user={user_id}, len={len(memory_system_prompt)}"
                )
        except Exception as exc:
            logger.warning(f"[LTM-stream] 读取画像失败（不影响对话）: {exc}")

    if settings.enable_stm and session.running_summary:
        stm_hint = (
            f"【对话历史摘要（已压缩 {session.turn_count} 轮早期对话）】\n"
            f"{session.running_summary}\n\n以下是最近的对话记录："
        )
        lc_messages.append(SystemMessage(content=stm_hint))
        print(f"[STM-stream] 注入 running_summary（{len(session.running_summary)} 字）")
        logger.info(f"[STM-stream] 注入 running_summary: session={session.id[:8]}")

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

    # 流式调用 LLM
    llm = _get_llm()
    reply_chunks = []

    print(f"[chat-stream] session={session.id[:8]} 开始流式输出...")
    logger.info(f"[chat-stream] 开始流式输出: session={session.id}")

    try:
        async for chunk in llm.astream(lc_messages):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                reply_chunks.append(token)
                yield token

        reply_text = "".join(reply_chunks)
        log_reply_completed(
            mode="fallback-stream",
            session_id=session.id,
            user_id=user_id,
            selected_skill="fallback",
            analysis_mode="general_chat",
        )

        # 保存 assistant 消息
        ai_msg = Message(session_id=session.id, role="assistant", content=reply_text)
        db.add(ai_msg)
        session.turn_count = (session.turn_count or 0) + 1
        session.updated_at = datetime.utcnow()
        await db.commit()

        print(
            f"[chat-stream] 流式完成: session={session.id[:8]} "
            f"turn={session.turn_count} reply={len(reply_text)}字"
        )
        logger.info(
            f"[chat-stream] 完成: session={session.id}, "
            f"turn={session.turn_count}, reply_len={len(reply_text)}"
        )

        # Phase 3: 流式模式也要解析 LLM 回复中的 <action> 并更新画像
        if settings.enable_memory and user_id:
            reply_text = await _prepare_reply_for_user(reply_text, user_id=user_id, db=db)

        # Phase 3: 流式模式也要后台更新 LTM
        if settings.enable_memory and user_id:
            asyncio.create_task(maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))

        # Phase 2 STM 压缩（推送进度帧）
        if settings.enable_stm:
            # 开始压缩：先给出估算时间（经验值：3-10s）
            est_seconds = 8
            yield json.dumps(
                {
                    "type": "compress_start",
                    "session_id": session.id,
                    "progress": 0,
                    "eta_seconds": est_seconds,
                },
                ensure_ascii=False,
            )

            compress_start = datetime.utcnow()
            result = await compress_if_needed(db, session.id)
            compress_elapsed = max(1, int((datetime.utcnow() - compress_start).total_seconds()))

            if result:
                # 压缩完成
                yield json.dumps(
                    {
                        "type": "compress_done",
                        "session_id": session.id,
                        "progress": 100,
                        "eta_seconds": 0,
                        "elapsed_seconds": compress_elapsed,
                        "snapshot_id": result.get("snapshot_id"),
                        "compressed_message_count": result.get("compressed_message_count"),
                        "total_message_count": result.get("total_message_count"),
                        "percent": result.get("percent"),
                    },
                    ensure_ascii=False,
                )
                # P3 钩子：从高质量摘要中提取画像（非阻塞）
                if settings.enable_memory and user_id:
                    asyncio.create_task(
                        _extract_from_summary(
                            session_id=session.id,
                            user_id=user_id,
                            summary=result.get("summary", ""),
                        )
                    )
            else:
                # 未触发压缩：发送一个轻量结束帧，前端关闭进度条
                yield json.dumps(
                    {
                        "type": "compress_skip",
                        "session_id": session.id,
                        "progress": 100,
                        "eta_seconds": 0,
                    },
                    ensure_ascii=False,
                )

        yield json.dumps({"type": "done", "session_id": session.id}, ensure_ascii=False)

    except Exception as exc:
        logger.error(f"[chat-stream] 流式输出失败: {exc}", exc_info=True)
        print(f"[chat-stream] 流式输出失败: {exc}")
        yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)


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
