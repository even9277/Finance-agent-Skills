from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agents.structured_io import extract_json_object, validate_model
from src.utils.logging_config import setup_logger

logger = setup_logger("route_stage2")


class Stage2Result(BaseModel):
    final_route: Literal["tushare-data", "fallback"] = "fallback"
    requires_current_facts: bool = False
    fact_dimensions: list[str] = Field(default_factory=list)
    reasoning_brief: str = ""


def heuristic_stage2(user_message: str, *, active_entity: dict[str, Any] | None = None) -> Stage2Result:
    text = (user_message or "").lower()
    current_tokens = (
        "今天", "今日", "最近", "最新", "现在", "当前", "收盘", "盘中", "行情",
        "涨跌", "走势", "估值", "pe", "pb", "净值", "资金流", "财报", "财务",
    )
    static_tokens = ("是什么", "区别", "为什么要", "概念", "原理", "方法", "怎么理解")
    if any(token in text for token in static_tokens) and not any(token in text for token in ("今天", "最新", "现在")):
        return Stage2Result(final_route="fallback", reasoning_brief="静态解释不依赖近期事实")
    if any(token in text for token in current_tokens) or active_entity:
        dims = []
        if any(token in text for token in ("行情", "走势", "涨", "跌", "收盘")):
            dims.append("market_snapshot")
        if any(token in text for token in ("估值", "pe", "pb", "财报", "财务")):
            dims.append("fundamental_or_valuation")
        if any(token in text for token in ("净值", "基金", "etf")):
            dims.append("fund_nav_or_market")
        return Stage2Result(
            final_route="tushare-data",
            requires_current_facts=True,
            fact_dimensions=dims or ["current_financial_facts"],
            reasoning_brief="高质量回答依赖当前或近期金融事实",
        )
    return Stage2Result(final_route="fallback", reasoning_brief="未发现必须查询近期事实的需求")


async def route_stage2(
    user_message: str,
    *,
    active_entity: dict[str, Any] | None = None,
    model_name: str = "",
    api_key: str = "",
    base_url: str = "",
) -> Stage2Result:
    if not (api_key and base_url and model_name):
        return heuristic_stage2(user_message, active_entity=active_entity)

    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
    except Exception:
        return heuristic_stage2(user_message, active_entity=active_entity)

    prompt = (
        "你是金融对话路由器第二阶段。判断本轮高质量回答是否必须建立在当前或近期可核对金融事实之上。\n"
        "是则 final_route=tushare-data，否则 final_route=fallback。仅输出 JSON。\n\n"
        f"[当前用户问题]\n{user_message}\n\n"
        f"[active_entity]\n{json.dumps(active_entity or {}, ensure_ascii=False)}"
    )
    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=320,
    )
    try:
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        payload = extract_json_object(getattr(result, "content", ""))
        return validate_model(Stage2Result, payload)
    except Exception as exc:
        logger.warning("[route_stage2] llm failed, fallback heuristic: %s", exc, exc_info=True)
        return heuristic_stage2(user_message, active_entity=active_entity)


def default_model_env() -> dict[str, str]:
    return {
        "model_name": os.getenv("CHAT_ROUTER_MODEL") or os.getenv("OPENAI_COMPATIBLE_MODEL") or "",
        "api_key": os.getenv("OPENAI_COMPATIBLE_API_KEY") or "",
        "base_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL") or "",
    }


__all__ = ["Stage2Result", "heuristic_stage2", "route_stage2"]
