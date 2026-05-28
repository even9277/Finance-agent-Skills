from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.skills.skill_registry import get_skill_registry


@dataclass(slots=True)
class PlannedToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    required: bool = True


@dataclass(slots=True)
class TushareToolPlan:
    selected_skill: str
    analysis_mode: str
    planner_type: str = "fallback_planner"
    references: list[dict[str, str]] = field(default_factory=list)
    tool_calls: list[PlannedToolCall] = field(default_factory=list)


def _reference_titles(query: str) -> list[dict[str, str]]:
    registry = get_skill_registry()
    return registry.find_references("tushare-data", query, limit=5)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _is_fund_query(text: str) -> bool:
    return _contains_any(
        text,
        (
            "基金",
            "etf",
            "联接",
            "lof",
            "qdii",
            "黄金etf",
            "黄金基金",
            "货币基金",
        ),
    )


def build_tushare_tool_plan(
    *,
    user_message: str,
    analysis_mode: str,
    resolved_symbol: str | None,
    enable_market_tools: bool,
    enable_index_tools: bool,
    enable_sector_tools: bool,
) -> TushareToolPlan:
    refs = _reference_titles(user_message)
    query = (user_message or "").strip()
    has_symbol = bool((resolved_symbol or "").strip())
    wants_market = _contains_any(query, ("今天", "今日", "现在", "最新", "最近", "行情", "走势", "买入"))
    wants_financial = _contains_any(
        query,
        ("财务", "财报", "报表", "roe", "估值", "利润", "营收", "现金流", "基本面"),
    )
    wants_fund = _is_fund_query(query)

    tool_calls: list[PlannedToolCall] = []

    if analysis_mode == "single_stock_data":
        if has_symbol:
            if enable_market_tools and wants_market:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="get_market_bars",
                        arguments={"query": query, "limit": 30},
                        reason="single-stock market question prefers market bar data",
                    )
                )
            else:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="get_daily_bars",
                        arguments={"query": query, "limit": 20},
                        reason="single-stock data question uses daily bars as baseline",
                    )
                )
            if wants_financial:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="get_fina_indicator",
                        arguments={"query": query, "limit": 4},
                        reason="financial metrics requested",
                    )
                )
        tool_calls.append(
            PlannedToolCall(
                tool_name="get_stock_basic_info",
                arguments={"query": query},
                reason="need stock identity and industry metadata",
                required=False,
            )
        )

    elif analysis_mode == "single_stock_fundamental":
        if enable_market_tools:
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_market_bars",
                    arguments={"query": query, "limit": 60},
                    reason="today worth-buying analysis needs recent market context",
                )
            )
        else:
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_daily_bars",
                    arguments={"query": query, "limit": 30},
                    reason="fallback market context for fundamental analysis",
                )
            )
        tool_calls.extend(
            [
                PlannedToolCall(
                    tool_name="get_fina_indicator",
                    arguments={"query": query, "limit": 4},
                    reason="core profitability and valuation indicators",
                ),
                PlannedToolCall(
                    tool_name="get_income",
                    arguments={"query": query, "limit": 2},
                    reason="revenue and profit trend",
                ),
                PlannedToolCall(
                    tool_name="get_balance_sheet",
                    arguments={"query": query, "limit": 2},
                    reason="balance sheet quality",
                    required=False,
                ),
                PlannedToolCall(
                    tool_name="get_cashflow",
                    arguments={"query": query, "limit": 2},
                    reason="cash generation quality",
                    required=False,
                ),
                PlannedToolCall(
                    tool_name="get_stock_basic_info",
                    arguments={"query": query},
                    reason="identity and industry context",
                    required=False,
                ),
            ]
        )

    elif analysis_mode == "sector_market":
        if enable_sector_tools:
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_sector_snapshot",
                    arguments={"query": query},
                    reason="sector/industry question should use sector snapshot data",
                )
            )
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_sector_constituents",
                    arguments={"query": query, "limit": 20},
                    reason="sector analysis benefits from representative constituents",
                    required=False,
                )
            )
        elif enable_index_tools:
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_index_bars",
                    arguments={"query": query, "limit": 30},
                    reason="fallback to index bars when sector tools are unavailable",
                )
            )

    elif analysis_mode == "stock_selection":
        if wants_fund:
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_fund_basic_info",
                    arguments={"query": query, "limit": 12},
                    reason="fund/ETF recommendation should start from the fund universe",
                )
            )
            if enable_market_tools:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="get_fund_market_bars",
                        arguments={"query": query, "limit": 20},
                        reason="fund/ETF recommendation needs recent market performance",
                        required=False,
                    )
                )
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_fund_nav",
                    arguments={"query": query, "limit": 10},
                    reason="fund recommendation should consider recent NAV data",
                    required=False,
                )
            )
            tool_calls.append(
                PlannedToolCall(
                    tool_name="get_fund_share",
                    arguments={"query": query, "limit": 10},
                    reason="fund/ETF recommendation benefits from size and share change data",
                    required=False,
                )
            )
        else:
            if enable_sector_tools:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="get_sector_snapshot",
                        arguments={"query": query},
                        reason="selection request often starts from sector context",
                    )
                )
            if enable_market_tools:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="get_market_bars",
                        arguments={"query": query, "limit": 30},
                        reason="selection request benefits from recent market context",
                        required=False,
                    )
                )

    seen: set[str] = set()
    deduped: list[PlannedToolCall] = []
    for item in tool_calls:
        key = f"{item.tool_name}|{sorted(item.arguments.items())}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return TushareToolPlan(
        selected_skill="tushare-data",
        analysis_mode=analysis_mode,
        planner_type="fallback_planner",
        references=refs,
        tool_calls=deduped,
    )
