from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.skills.skill_registry import get_skill_registry

try:
    from dotenv import load_dotenv

    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / "backend" / ".env", override=False)
except Exception:
    pass

_STOCK_CODE_RE = re.compile(r"\b(?:sh|sz)?\.?\d{6}\b", re.IGNORECASE)

_REALTIME_HINTS = [
    "今天",
    "今日",
    "现在",
    "最新",
    "最近",
    "行情",
    "财报",
    "财务",
    "估值",
    "营收",
    "利润",
    "净利润",
    "现金流",
    "毛利率",
    "涨幅",
    "跌幅",
    "成交额",
    "北向资金",
]

_SECTOR_HINTS = ["板块", "行业", "指数", "概念", "资金流向"]
_SELECTION_HINTS = ["选股", "筛选", "推荐", "组合", "适合我", "候选"]
_FUNDAMENTAL_HINTS = ["基本面", "财务指标", "roe", "盈利能力", "报表", "估值"]
_FUND_HINTS = ["基金", "etf", "黄金etf", "黄金基金", "联接基金", "lof", "qdii"]
_COMPARE_HINTS = ["对比", "比较", "pk", "vs", "哪个好", "哪个更好", "二选一", "区别", "怎么选"]
_MOVE_HINTS = ["为什么涨", "为什么跌", "异动", "拉升", "跳水", "冲高回落", "大涨", "大跌", "突然涨", "突然跌"]
_ETF_SCREEN_HINTS = ["推荐", "筛选", "候选", "配置", "怎么买", "选哪个", "怎么选", "适合", "shortlist"]
_HOTSPOT_HINTS = ["热点", "热度", "强势", "弱势", "龙头", "还能追", "还能看", "轮动"]
_STOCK_FIRST_PASS_HINTS = ["值不值得", "还能买吗", "还能拿吗", "怎么看", "首轮判断", "跟踪", "财报怎么看", "能买吗"]
_FOLLOW_UP_HINTS = [
    "是",
    "好的",
    "好",
    "请查询",
    "继续",
    "查一下",
    "那就查",
    "请继续",
    "就这个",
    "重新回答",
    "请重新回答",
    "重答",
    "再回答",
    "再说一遍",
    "重来",
]
_FUND_ENTITY_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\-]{2,30}(?:ETF|etf|基金|联接|LOF|lof|QDII|qdii)")

_ROUTER_PROMPT = """你是 A 股对话路由器。请基于用户问题和可用技能摘要，决定：
1. 是否需要实时数据
2. 是否需要专业分析
3. 应进入哪个真实技能
4. 采用哪种分析模式
4. 如果不需要技能，是否直接 fallback 到普通 LLM

可用技能：
{skills}

规则：
- 普通闲聊、解释性知识、无需实时或专业金融数据：fallback
- 需要股票、财务、报表、估值、基础数据、指数、行业、板块等可核对数据：tushare-data
- 单股专业分析是 analysis_mode=single_stock_fundamental，不要伪造 skill 名
- 板块/行业/指数分析是 analysis_mode=sector_market
- 根据条件筛选股票是 analysis_mode=stock_selection
- 如果只是普通闲聊或知识解释，不要进入 tushare-data

只输出 JSON：
{{
  "selected_skill": "fallback|tushare-data",
  "analysis_mode": "general_chat|single_stock_data|single_stock_fundamental|sector_market|stock_selection",
  "needs_realtime_data": true,
  "needs_professional_analysis": false,
  "confidence": 0.0,
  "why": "..."
}}

用户问题：
{query}

用户画像摘要（仅辅助路由，没有则忽略）：
{profile_summary}

对话上下文（用于处理“继续”“是，请查询”这类跟进式消息，如果为空则忽略）：
{conversation_context}
"""


@dataclass(slots=True)
class SkillRouteDecision:
    selected_skill: str
    confidence: float
    arguments: dict[str, Any] = field(default_factory=dict)
    why: str = ""
    needs_realtime_data: bool = False
    needs_professional_analysis: bool = False
    analysis_mode: str = "general_chat"
    selected_skill_family: str = ""
    skill_name: str | None = None
    execution_policy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_skill_family": self.selected_skill_family,
            "selected_skill": self.selected_skill,
            "skill_name": self.skill_name,
            "confidence": self.confidence,
            "arguments": self.arguments,
            "why": self.why,
            "needs_realtime_data": self.needs_realtime_data,
            "needs_professional_analysis": self.needs_professional_analysis,
            "analysis_mode": self.analysis_mode,
            "execution_policy": self.execution_policy,
        }


def _safe_getenv(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _router_model_name() -> str:
    return _safe_getenv("CHAT_ROUTER_MODEL") or _safe_getenv("OPENAI_COMPATIBLE_MODEL") or "kimi-k2.5"


def _available_skill_names() -> list[str]:
    return [skill.name for skill in get_skill_registry().list_skills()]


def _available_sop_skills() -> list[dict[str, str]]:
    return [
        {
            "name": skill.name,
            "description": skill.description,
            "version": skill.version or "",
            "source": skill.source,
            "execution_mode": skill.execution_mode,
        }
        for skill in get_skill_registry().discoverable_sop_skills()
    ]


def _build_skill_summary() -> str:
    parts = []
    for item in get_skill_registry().matchable_descriptions():
        parts.append(
            f"- {item['name']}: {item['description']} (source={item.get('source','unknown')}, mode={item.get('execution_mode','agent')})"
        )
    return "\n".join(parts) if parts else "- fallback: 普通聊天"


def _build_sop_skill_summary() -> str:
    items = _available_sop_skills()
    if not items:
        return "- 无可用 financial-sop skills"
    return "\n".join(
        f"- {item['name']}: {item['description']} (source={item['source']}, version={item['version'] or 'unknown'}, mode={item['execution_mode']})"
        for item in items
    )


def _default_execution_policy(*, selected_skill: str, analysis_mode: str) -> str:
    if selected_skill == "fallback":
        return "agentic"
    if selected_skill == "financial-sop":
        return "deterministic"
    if analysis_mode in {"single_stock_data", "single_stock_fundamental", "sector_market", "stock_selection"}:
        return "deterministic"
    return "agentic"


def _apply_p0_defaults(decision: SkillRouteDecision) -> SkillRouteDecision:
    if not decision.selected_skill_family:
        if decision.selected_skill in {"fallback", "tushare-data"}:
            decision.selected_skill_family = decision.selected_skill
        else:
            decision.selected_skill_family = "financial-sop"
    if decision.skill_name == "":
        decision.skill_name = None
    if not decision.execution_policy:
        decision.execution_policy = _default_execution_policy(
            selected_skill=decision.selected_skill,
            analysis_mode=decision.analysis_mode,
        )
    return decision


def _rule_based_route(user_message: str) -> SkillRouteDecision:
    text = (user_message or "").strip()
    lowered = text.lower()
    has_stock_code = bool(_STOCK_CODE_RE.search(lowered))
    has_realtime_data = any(keyword in text for keyword in _REALTIME_HINTS) or has_stock_code
    is_sector = any(keyword in text for keyword in _SECTOR_HINTS)
    is_selection = any(keyword in text for keyword in _SELECTION_HINTS)
    is_fundamental = any(keyword.lower() in lowered for keyword in _FUNDAMENTAL_HINTS)
    has_stock_hint = any(token in text for token in ("股票", "茅台", "比亚迪", "宁德时代", "贵州茅台", "北方华创"))

    available = set(_available_skill_names())

    if is_selection:
        selected = "stock-selection" if "stock-selection" in available else "tushare-data"
        return SkillRouteDecision(
            selected_skill="tushare-data" if "tushare-data" in available else "fallback",
            confidence=0.9,
            arguments={"query": text},
            why="matched stock-selection rule",
            needs_realtime_data=True,
            needs_professional_analysis=True,
            analysis_mode="stock_selection",
        )

    if is_sector:
        return SkillRouteDecision(
            selected_skill="tushare-data" if "tushare-data" in available else "fallback",
            confidence=0.88,
            arguments={"query": text},
            why="matched sector-analysis rule",
            needs_realtime_data=True,
            needs_professional_analysis=True,
            analysis_mode="sector_market",
        )

    if is_fundamental and (has_stock_hint or has_stock_code):
        return SkillRouteDecision(
            selected_skill="tushare-data" if "tushare-data" in available else "fallback",
            confidence=0.9,
            arguments={"query": text},
            why="matched single-stock fundamental rule",
            needs_realtime_data=True,
            needs_professional_analysis=True,
            analysis_mode="single_stock_fundamental",
        )

    if has_realtime_data or has_stock_hint:
        return SkillRouteDecision(
            selected_skill="tushare-data" if "tushare-data" in available else "fallback",
            confidence=0.85,
            arguments={"query": text},
            why="matched realtime-data rule",
            needs_realtime_data=has_realtime_data,
            needs_professional_analysis=False,
            analysis_mode="single_stock_data" if (has_stock_hint or has_stock_code) else "general_chat",
        )

    return SkillRouteDecision(
        selected_skill="fallback",
        confidence=0.75,
        arguments={"query": text},
        why="no skill rule matched",
        needs_realtime_data=False,
        needs_professional_analysis=False,
        analysis_mode="general_chat",
    )


async def _llm_route(user_message: str) -> SkillRouteDecision | None:
    return await _llm_route_with_context(user_message, "")


def _is_follow_up_message(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if len(clean) <= 16 and any(hint in clean for hint in _FOLLOW_UP_HINTS):
        return True
    return clean in {"嗯", "好的", "是的", "行", "可以"}


def _effective_query(user_message: str, conversation_context: str) -> str:
    text = (user_message or "").strip()
    context = (conversation_context or "").strip()
    if not context:
        return text
    if _is_follow_up_message(text):
        return f"{context}\n当前用户补充：{text}"
    return text


def _contains_compare_hint(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in _COMPARE_HINTS)


def _normalize_fund_entity_candidate(text: str) -> str:
    candidate = (text or "").strip("，。！？,.!?：:；;()（）[]【】 ")
    if not candidate:
        return ""
    match = _FUND_ENTITY_RE.search(candidate)
    if match:
        candidate = match.group(0)
    candidate = re.sub(r"^(请|帮我|重新回答|请重新回答|比较|对比)+", "", candidate).strip()
    candidate = candidate.strip("，。！？,.!?：:；;()（）[]【】 ")
    return candidate


def _extract_fund_compare_entities(text: str) -> list[str]:
    raw_text = (text or "").strip()
    if not raw_text:
        return []

    entities: list[str] = []
    for match in _FUND_ENTITY_RE.findall(raw_text):
        candidate = _normalize_fund_entity_candidate(match)
        if any(token in candidate for token in ("和", "与", "对比", "比较", "vs", "VS", "pk", "PK")):
            continue
        if len(candidate) >= 2 and candidate not in entities:
            entities.append(candidate)

    cleaned = raw_text
    for token in ("帮我", "请", "比较", "对比", "一下", "分析", "看看", "哪个", "更适合我", "更适合"):
        cleaned = cleaned.replace(token, " ")
    parts = re.split(r"\s+|和|与|跟|及|,|，|/|对比|比较|vs|VS|pk|PK", cleaned)
    for part in parts:
        candidate = _normalize_fund_entity_candidate(part)
        if not candidate:
            continue
        if any(hint.lower() in candidate.lower() for hint in _FUND_HINTS) and candidate not in entities:
            entities.append(candidate)
    return entities[:4]


def _looks_like_fund_compare_query(text: str) -> bool:
    entities = _extract_fund_compare_entities(text)
    if len(entities) >= 2 and _contains_compare_hint(text):
        return True
    lowered = (text or "").lower()
    return _contains_compare_hint(text) and sum(1 for hint in _FUND_HINTS if hint.lower() in lowered) >= 2


def _looks_like_etf_screen_query(text: str) -> bool:
    lowered = (text or "").lower()
    if _looks_like_fund_compare_query(text):
        return False
    has_fund_context = any(hint.lower() in lowered for hint in _FUND_HINTS)
    has_screen_intent = any(hint.lower() in lowered for hint in _ETF_SCREEN_HINTS + _SELECTION_HINTS)
    has_theme_hint = any(token in text for token in ("宽基", "黄金", "红利", "证券", "科创", "芯片", "半导体", "创业板", "沪深300", "中证"))
    return has_fund_context and (has_screen_intent or has_theme_hint)


def _looks_like_market_move_explain_query(text: str) -> bool:
    lowered = (text or "").lower()
    has_move_intent = any(hint.lower() in lowered for hint in _MOVE_HINTS)
    has_market_object = (
        any(hint.lower() in lowered for hint in _FUND_HINTS)
        or any(token in text for token in _SECTOR_HINTS)
        or any(token in text for token in ("股票", "个股", "茅台", "比亚迪", "宁德时代", "贵州茅台", "北方华创"))
        or bool(_STOCK_CODE_RE.search(lowered))
    )
    return has_move_intent and has_market_object


def _looks_like_sector_hotspot_query(text: str) -> bool:
    lowered = (text or "").lower()
    has_sector_context = any(token in text for token in _SECTOR_HINTS)
    has_hotspot_intent = any(hint.lower() in lowered for hint in _HOTSPOT_HINTS + _SELECTION_HINTS)
    return has_sector_context and has_hotspot_intent and not _looks_like_market_move_explain_query(text)


def _looks_like_stock_first_pass_query(text: str) -> bool:
    lowered = (text or "").lower()
    if any(hint.lower() in lowered for hint in _FUND_HINTS):
        return False
    if any(token in text for token in _SECTOR_HINTS):
        return False
    has_stock_object = any(token in text for token in ("股票", "个股", "茅台", "比亚迪", "宁德时代", "贵州茅台", "北方华创")) or bool(_STOCK_CODE_RE.search(lowered))
    has_first_pass_intent = (
        any(hint.lower() in lowered for hint in _STOCK_FIRST_PASS_HINTS)
        or any(hint.lower() in lowered for hint in _FUNDAMENTAL_HINTS)
        or "财报" in text
    )
    return has_stock_object and has_first_pass_intent


def _looks_like_financial_sop_query(text: str) -> bool:
    return any(
        checker(text)
        for checker in (
            _looks_like_fund_compare_query,
            _looks_like_etf_screen_query,
            _looks_like_market_move_explain_query,
            _looks_like_sector_hotspot_query,
            _looks_like_stock_first_pass_query,
        )
    )


def _financial_sop_execution_policy(skill_name: str | None) -> str:
    if not skill_name:
        return "deterministic"
    meta = get_skill_registry().get_skill(skill_name)
    if meta and meta.execution_mode:
        return str(meta.execution_mode)
    return "deterministic"


def _rule_select_financial_sop_skill(query: str) -> str | None:
    available = {item["name"] for item in _available_sop_skills()}
    if "fund-compare" in available and _looks_like_fund_compare_query(query):
        return "fund-compare"
    if "etf-screen" in available and _looks_like_etf_screen_query(query):
        return "etf-screen"
    if "market-move-explain" in available and _looks_like_market_move_explain_query(query):
        return "market-move-explain"
    if "sector-hotspot-brief" in available and _looks_like_sector_hotspot_query(query):
        return "sector-hotspot-brief"
    if "stock-first-pass" in available and _looks_like_stock_first_pass_query(query):
        return "stock-first-pass"
    return None


async def _llm_select_financial_sop_skill(query: str) -> str | None:
    api_key = _safe_getenv("OPENAI_COMPATIBLE_API_KEY")
    base_url = _safe_getenv("OPENAI_COMPATIBLE_BASE_URL")
    model_name = _router_model_name()
    if not all([api_key, base_url, model_name]):
        return None

    skills_summary = _build_sop_skill_summary()
    if "无可用 financial-sop skills" in skills_summary:
        return None

    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
    except Exception:
        return None

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=120,
    )
    prompt = f"""你是金融 SOP skill discovery 路由器。只基于 skill metadata 选择最匹配的 skill。

可用 skills：
{skills_summary}

规则：
- 当用户明确要对比/比较两只或多只基金、ETF、LOF、联接基金时，优先选择 `fund-compare`
- 当用户要筛选、推荐、shortlist 某类 ETF 或场内基金，而不是比较两个已知产品时，选择 `etf-screen`
- 当用户问板块、行业、主题的热度、龙头、还能不能继续关注时，选择 `sector-hotspot-brief`
- 当用户问个股、ETF、指数、板块为什么涨跌或异动时，选择 `market-move-explain`
- 当用户围绕单只股票做首轮判断、财报快读、值不值得继续跟踪时，选择 `stock-first-pass`
- 如果不确定或不匹配，返回 null
- 不要臆造 skill 名

只输出 JSON：
{{
  "skill_name": "fund-compare|etf-screen|sector-hotspot-brief|market-move-explain|stock-first-pass|null",
  "why": "..."
}}

用户问题：
{query}
"""
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = (response.content or "").strip()
        if "{" not in text or "}" not in text:
            return None
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception:
        return None

    skill_name = str(data.get("skill_name") or "").strip()
    if not skill_name or skill_name.lower() == "null":
        return None
    if skill_name not in {item["name"] for item in _available_sop_skills()}:
        return None
    return skill_name


async def _route_financial_sop(
    user_message: str,
    conversation_context: str = "",
    profile_summary: str = "",
) -> SkillRouteDecision | None:
    effective_query = _effective_query(user_message, conversation_context)
    if not _looks_like_financial_sop_query(effective_query):
        return None

    skill_name = await _llm_select_financial_sop_skill(effective_query)
    router_model = _router_model_name() if skill_name else "rule-based"
    if not skill_name:
        skill_name = _rule_select_financial_sop_skill(effective_query)
    if not skill_name:
        return None
    analysis_mode = str(skill_name).replace("-", "_")

    return _apply_p0_defaults(
        SkillRouteDecision(
            selected_skill="financial-sop",
            confidence=0.9,
            arguments={
                "query": (user_message or "").strip(),
                "effective_query": effective_query,
                "conversation_context": (conversation_context or "").strip(),
                "is_follow_up": _is_follow_up_message(user_message),
                "profile_summary_used": bool((profile_summary or "").strip()),
                "router_model": f"metadata-discovery:{router_model}",
                "candidate_entities": _extract_fund_compare_entities(effective_query) if skill_name == "fund-compare" else [],
            },
            why=f"matched financial-sop query for {skill_name}",
            needs_realtime_data=True,
            needs_professional_analysis=True,
            analysis_mode=analysis_mode,
            selected_skill_family="financial-sop",
            skill_name=skill_name,
            execution_policy=_financial_sop_execution_policy(skill_name),
        )
    )


def _rule_based_route_with_context(
    user_message: str,
    conversation_context: str = "",
    profile_summary: str = "",
) -> SkillRouteDecision:
    effective_query = _effective_query(user_message, conversation_context)
    base = _rule_based_route(effective_query)
    base.arguments = {
        "query": (user_message or "").strip(),
        "effective_query": effective_query,
        "conversation_context": (conversation_context or "").strip(),
        "is_follow_up": _is_follow_up_message(user_message),
        "profile_summary_used": bool((profile_summary or "").strip()),
        "router_model": "rule-based",
    }
    if base.selected_skill == "fallback" and _is_follow_up_message(user_message) and conversation_context:
        context_text = conversation_context.strip()
        if any(token in context_text for token in (_REALTIME_HINTS + _SECTOR_HINTS + _SELECTION_HINTS + _FUND_HINTS)):
            base.selected_skill = "tushare-data" if "tushare-data" in _available_skill_names() else "fallback"
            base.analysis_mode = "stock_selection" if any(token in context_text for token in _SELECTION_HINTS + _FUND_HINTS) else "single_stock_data"
            base.needs_realtime_data = True
            base.confidence = max(base.confidence, 0.82)
            base.why = "follow-up message inherited prior finance/data context"
    return _apply_p0_defaults(base)


async def _llm_route_with_context(
    user_message: str,
    conversation_context: str = "",
    profile_summary: str = "",
) -> SkillRouteDecision | None:
    api_key = _safe_getenv("OPENAI_COMPATIBLE_API_KEY")
    base_url = _safe_getenv("OPENAI_COMPATIBLE_BASE_URL")
    model_name = _router_model_name()
    if not all([api_key, base_url, model_name]):
        return None

    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
    except Exception:
        return None

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=220,
    )
    effective_query = _effective_query(user_message, conversation_context)
    response = await llm.ainvoke(
        [HumanMessage(content=_ROUTER_PROMPT.format(
            skills=_build_skill_summary(),
            query=effective_query,
            profile_summary=profile_summary or "无",
            conversation_context=conversation_context or "无",
        ))]
    )
    text = (response.content or "").strip()
    if "{" not in text or "}" not in text:
        return None
    text = text[text.index("{"): text.rindex("}") + 1]
    data = json.loads(text)

    selected_skill = str(data.get("selected_skill") or "").strip()
    if selected_skill not in {"fallback", "tushare-data"}:
        return None

    analysis_mode = str(data.get("analysis_mode") or "general_chat").strip()
    if analysis_mode not in {
        "general_chat",
        "single_stock_data",
        "single_stock_fundamental",
        "sector_market",
        "stock_selection",
    }:
        return None

    return _apply_p0_defaults(SkillRouteDecision(
        selected_skill=selected_skill,
        confidence=max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
        arguments={
            "query": (user_message or "").strip(),
            "effective_query": effective_query,
            "conversation_context": (conversation_context or "").strip(),
            "is_follow_up": _is_follow_up_message(user_message),
            "profile_summary_used": bool((profile_summary or "").strip()),
            "router_model": model_name,
        },
        why=str(data.get("why") or "llm router"),
        needs_realtime_data=bool(data.get("needs_realtime_data")),
        needs_professional_analysis=bool(data.get("needs_professional_analysis")),
        analysis_mode=analysis_mode,
    ))


async def route_chat_skill(
    user_message: str,
    conversation_context: str = "",
    profile_summary: str = "",
) -> SkillRouteDecision:
    sop_decision = await _route_financial_sop(
        user_message,
        conversation_context,
        profile_summary,
    )
    if sop_decision is not None:
        return sop_decision
    try:
        decision = await _llm_route_with_context(
            user_message,
            conversation_context,
            profile_summary,
        )
        if decision is not None:
            return decision
    except Exception:
        pass
    return _rule_based_route_with_context(
        user_message,
        conversation_context,
        profile_summary,
    )
