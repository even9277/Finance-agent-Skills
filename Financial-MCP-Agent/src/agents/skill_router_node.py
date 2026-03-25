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
_FOLLOW_UP_HINTS = ["是", "好的", "好", "请查询", "继续", "查一下", "那就查", "请继续", "就这个"]

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_skill": self.selected_skill,
            "confidence": self.confidence,
            "arguments": self.arguments,
            "why": self.why,
            "needs_realtime_data": self.needs_realtime_data,
            "needs_professional_analysis": self.needs_professional_analysis,
            "analysis_mode": self.analysis_mode,
        }


def _safe_getenv(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _router_model_name() -> str:
    return _safe_getenv("CHAT_ROUTER_MODEL") or _safe_getenv("OPENAI_COMPATIBLE_MODEL") or "kimi-k2.5"


def _available_skill_names() -> list[str]:
    return [skill.name for skill in get_skill_registry().list_skills()]


def _build_skill_summary() -> str:
    parts = []
    for item in get_skill_registry().matchable_descriptions():
        parts.append(
            f"- {item['name']}: {item['description']} (source={item.get('source','unknown')}, mode={item.get('execution_mode','agent')})"
        )
    return "\n".join(parts) if parts else "- fallback: 普通聊天"


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
    if len(clean) <= 10 and any(hint in clean for hint in _FOLLOW_UP_HINTS):
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


def _rule_based_route_with_context(user_message: str, conversation_context: str = "") -> SkillRouteDecision:
    effective_query = _effective_query(user_message, conversation_context)
    base = _rule_based_route(effective_query)
    base.arguments = {
        "query": (user_message or "").strip(),
        "effective_query": effective_query,
        "conversation_context": (conversation_context or "").strip(),
        "is_follow_up": _is_follow_up_message(user_message),
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
    return base


async def _llm_route_with_context(user_message: str, conversation_context: str = "") -> SkillRouteDecision | None:
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

    return SkillRouteDecision(
        selected_skill=selected_skill,
        confidence=max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
        arguments={
            "query": (user_message or "").strip(),
            "effective_query": effective_query,
            "conversation_context": (conversation_context or "").strip(),
            "is_follow_up": _is_follow_up_message(user_message),
            "router_model": model_name,
        },
        why=str(data.get("why") or "llm router"),
        needs_realtime_data=bool(data.get("needs_realtime_data")),
        needs_professional_analysis=bool(data.get("needs_professional_analysis")),
        analysis_mode=analysis_mode,
    )


async def route_chat_skill(user_message: str, conversation_context: str = "") -> SkillRouteDecision:
    try:
        decision = await _llm_route_with_context(user_message, conversation_context)
        if decision is not None:
            return decision
    except Exception:
        pass
    return _rule_based_route_with_context(user_message, conversation_context)
