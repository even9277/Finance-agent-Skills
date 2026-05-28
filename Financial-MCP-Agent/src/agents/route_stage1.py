from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agents.structured_io import extract_json_object, validate_model
from src.skills.route_metadata import RouteMetadata, RouteMetadataIndex
from src.utils.logging_config import setup_logger

logger = setup_logger("route_stage1")

Stage1Outcome = Literal["sop_hit_high", "sop_hit_low", "sop_miss"]


class Stage1Result(BaseModel):
    outcome: Stage1Outcome = "sop_miss"
    skill_id: str | None = None
    confidence: float = 0.0
    shortlist: list[str] = Field(default_factory=list)
    reasoning_brief: str = ""


def heuristic_stage1(
    user_message: str,
    index: RouteMetadataIndex,
    *,
    confidence_high: float = 0.85,
    confidence_low: float = 0.65,
) -> Stage1Result:
    shortlist = index.shortlist(user_message, limit=5)
    query = (user_message or "").lower()
    selected: RouteMetadata | None = None
    confidence = 0.0

    rules = [
        ("fund-compare", ("比较", "哪个适合", "哪只更", "费率", "对比")),
        ("etf-screen", ("筛", "筛选", "推荐几只", "找几只", "配置")),
        ("market-move-explain", ("为什么", "异动", "突然", "上涨", "下跌", "拉了", "跌了")),
        ("sector-hotspot-brief", ("板块热点", "热点", "行业机会", "板块简报")),
        ("stock-first-pass", ("怎么看", "能买吗", "值不值得", "估值", "基本面")),
    ]
    by_id = {item.skill_id: item for item in shortlist}
    for skill_id, tokens in rules:
        if skill_id in by_id and any(token in query for token in tokens):
            selected = by_id[skill_id]
            confidence = 0.88 if skill_id in {"fund-compare", "market-move-explain"} else 0.78
            break

    if selected is None:
        return Stage1Result(
            outcome="sop_miss",
            shortlist=[item.skill_id for item in shortlist],
            reasoning_brief="未稳定命中 SOP",
        )

    return Stage1Result(
        outcome="sop_hit_high" if confidence >= confidence_high else "sop_hit_low",
        skill_id=selected.skill_id,
        confidence=confidence,
        shortlist=[item.skill_id for item in shortlist],
        reasoning_brief=f"命中 {selected.skill_id} 的任务触发词",
    )


async def route_stage1(
    user_message: str,
    *,
    active_entity: dict[str, Any] | None,
    index: RouteMetadataIndex,
    model_name: str = "",
    api_key: str = "",
    base_url: str = "",
    confidence_high: float = 0.85,
) -> Stage1Result:
    shortlist = index.shortlist(user_message, limit=5)
    if not shortlist:
        return Stage1Result(outcome="sop_miss")
    if not (api_key and base_url and model_name):
        return heuristic_stage1(user_message, index, confidence_high=confidence_high)

    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
    except Exception:
        return heuristic_stage1(user_message, index, confidence_high=confidence_high)

    prompt = _build_prompt(user_message, active_entity, shortlist, confidence_high)
    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=400,
    )
    try:
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        payload = extract_json_object(getattr(result, "content", ""))
        parsed = validate_model(Stage1Result, payload)
    except Exception as exc:
        logger.warning("[route_stage1] llm failed, fallback heuristic: %s", exc, exc_info=True)
        return heuristic_stage1(user_message, index, confidence_high=confidence_high)

    allowed = {item.skill_id for item in shortlist}
    if parsed.skill_id and parsed.skill_id not in allowed:
        parsed.skill_id = None
        parsed.outcome = "sop_miss"
        parsed.confidence = 0.0
    parsed.shortlist = [item.skill_id for item in shortlist]
    if parsed.outcome == "sop_hit_high" and parsed.confidence < confidence_high:
        parsed.outcome = "sop_hit_low"
    return parsed


def _build_prompt(
    user_message: str,
    active_entity: dict[str, Any] | None,
    shortlist: list[RouteMetadata],
    confidence_high: float,
) -> str:
    return (
        "你是金融对话路由器第一阶段，只判断是否命中某个金融 SOP Skill。\n"
        "仅输出 JSON，字段：outcome, skill_id, confidence, reasoning_brief。\n"
        f"outcome=sop_hit_high 表示 confidence >= {confidence_high}; "
        "outcome=sop_hit_low 表示像某技能但需要用户确认；outcome=sop_miss 表示未命中。\n\n"
        f"[当前用户问题]\n{user_message}\n\n"
        f"[active_entity]\n{json.dumps(active_entity or {}, ensure_ascii=False)}\n\n"
        "[候选 Skill metadata]\n"
        f"{json.dumps([item.prompt_summary() for item in shortlist], ensure_ascii=False)}"
    )


def default_model_env() -> dict[str, str]:
    return {
        "model_name": os.getenv("CHAT_ROUTER_MODEL") or os.getenv("OPENAI_COMPATIBLE_MODEL") or "",
        "api_key": os.getenv("OPENAI_COMPATIBLE_API_KEY") or "",
        "base_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL") or "",
    }


__all__ = ["Stage1Result", "heuristic_stage1", "route_stage1"]
