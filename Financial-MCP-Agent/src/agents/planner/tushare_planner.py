from __future__ import annotations

from typing import Any
import uuid

from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2
from src.agents.tool_discovery.executable_registry import (
    ExecutableToolRegistry,
    ExecutableToolSpec,
    build_default_registry,
)
from src.tools.skill_trace import trace_span

_REQUIREMENT_TO_TOOLS = {
    "stock_basic": ("get_stock_basic_info",),
    "stock_daily": ("get_daily_bars",),
    "stock_market": ("get_market_bars", "get_daily_bars"),
    "market_bars": ("get_market_bars", "get_daily_bars"),
    "index_context": ("get_index_bars",),
    "index_daily": ("get_index_bars",),
    "sector_snapshot": ("get_sector_snapshot",),
    "sector_constituents": ("get_sector_constituents",),
    "fund_basic": ("get_fund_basic_info",),
    "fund_nav": ("get_fund_nav",),
    "fund_daily": ("get_fund_market_bars",),
    "fund_market_bars": ("get_fund_market_bars",),
    "fund_share": ("get_fund_share",),
    "financial_indicator": ("get_fina_indicator",),
    "income_statement": ("get_income",),
    "income": ("get_income",),
    "balance_sheet": ("get_balance_sheet",),
    "cashflow_statement": ("get_cashflow",),
    "cashflow": ("get_cashflow",),
    "web_news": ("search_web_news",),
}

_DEFAULT_LIMITS = {
    "get_stock_basic_info": 3,
    "get_daily_bars": 20,
    "get_market_bars": 30,
    "get_index_bars": 30,
    "get_sector_constituents": 20,
    "get_fund_basic_info": 10,
    "get_fund_nav": 10,
    "get_fund_market_bars": 20,
    "get_fund_share": 10,
    "get_fina_indicator": 4,
    "get_income": 2,
    "get_balance_sheet": 2,
    "get_cashflow": 2,
    "search_web_news": 5,
}


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _new_plan_id() -> str:
    return f"plan_{uuid.uuid4().hex}"


def _first_entity(payload: dict[str, Any], active_entity: Any) -> dict[str, Any] | None:
    entity = _model_dump(active_entity)
    if entity:
        return entity
    entities = payload.get("entities") or []
    if entities:
        return _model_dump(entities[0])
    return None


def _entity_symbol(entity: dict[str, Any] | None) -> str:
    if not entity:
        return ""
    return str(entity.get("symbol") or entity.get("canonical_id") or entity.get("ts_code") or "").strip()


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in out:
            out.append(item)
    return out


class TusharePlanner:
    def __init__(self, *, registry: ExecutableToolRegistry | None = None, prompt_version: str = "p5_tushare_planner_v1") -> None:
        self.registry = registry or build_default_registry()
        self.prompt_version = prompt_version

    def plan(
        self,
        *,
        rewrite_result: Any,
        discovery_result: Any,
        active_entity: Any = None,
        trace_id: str = "",
        constraints: list[str] | None = None,
    ) -> ToolPlanV2:
        with trace_span(
            "plan_generate",
            stage="planner",
            data={"planner_type": "tushare", "prompt_version": self.prompt_version},
        ):
            rewrite = _model_dump(rewrite_result)
            discovery = _model_dump(discovery_result)
            available_tools = set(discovery.get("available_tools") or [])
            entity = _first_entity(rewrite, active_entity)
            effective_query = str(rewrite.get("effective_query") or "").strip()
            selected_tools = self._select_tools(rewrite=rewrite, available_tools=available_tools)
            steps = [
                self._build_step(
                    index=index,
                    tool_name=tool_name,
                    spec=self.registry.spec(tool_name),
                    effective_query=effective_query,
                    entity=entity,
                )
                for index, tool_name in enumerate(selected_tools, start=1)
            ]
            result = ToolPlanV2(
                plan_id=_new_plan_id(),
                trace_id=trace_id,
                discovery_trace_id=str(discovery.get("discovery_trace_id") or ""),
                route="tushare-data",
                objective=effective_query or "tushare data retrieval",
                entity=entity,
                time_scope=dict(rewrite.get("time_scope") or {}),
                steps=steps,
                planner_model="deterministic",
                prompt_version=self.prompt_version,
            )
            return result

    def _select_tools(self, *, rewrite: dict[str, Any], available_tools: set[str]) -> list[str]:
        hinted = [
            str(name).strip()
            for name in (rewrite.get("candidate_tool_hints") or [])
            if str(name).strip() in available_tools and str(name).strip() in self.registry.names()
        ]
        mapped: list[str] = []
        for requirement in rewrite.get("data_requirements") or []:
            for tool_name in _REQUIREMENT_TO_TOOLS.get(str(requirement).strip(), ()):
                if tool_name in available_tools:
                    mapped.append(tool_name)
                    break
        selected = _dedupe(hinted + mapped)
        if selected:
            return selected

        primary_available = [
            name
            for name in self.registry.names(planner_visible_only=True)
            if name in available_tools and self.registry.spec(name).is_primary_evidence
        ]
        return primary_available[:1]

    def _build_step(
        self,
        *,
        index: int,
        tool_name: str,
        spec: ExecutableToolSpec,
        effective_query: str,
        entity: dict[str, Any] | None,
    ) -> ToolPlanStepV2:
        arguments = self._arguments_for_tool(tool_name=tool_name, spec=spec, effective_query=effective_query, entity=entity)
        return ToolPlanStepV2(
            step_id=f"s{index}",
            goal=self._goal_for_tool(tool_name=tool_name, spec=spec),
            tool_name=tool_name,
            arguments=arguments,
            depends_on=[],
            expected_observation=spec.evidence_type,
            required=spec.is_primary_evidence,
            evidence_type=spec.evidence_type,
        )

    @staticmethod
    def _goal_for_tool(*, tool_name: str, spec: ExecutableToolSpec) -> str:
        labels = {
            "get_stock_basic_info": "确认股票基础信息",
            "get_market_bars": "查询近期行情与成交事实",
            "get_daily_bars": "查询日线行情事实",
            "get_index_bars": "查询指数市场对照",
            "get_sector_snapshot": "查询板块快照",
            "get_sector_constituents": "查询板块成分股",
            "get_fund_basic_info": "查询基金基础信息",
            "get_fund_nav": "查询基金净值",
            "get_fund_market_bars": "查询基金交易行情",
            "get_fund_share": "查询基金份额与规模",
            "get_fina_indicator": "查询财务指标",
            "get_income": "查询利润表",
            "get_balance_sheet": "查询资产负债表",
            "get_cashflow": "查询现金流量表",
            "search_web_news": "搜索近期新闻线索",
        }
        return labels.get(tool_name, spec.description)

    @staticmethod
    def _arguments_for_tool(
        *,
        tool_name: str,
        spec: ExecutableToolSpec,
        effective_query: str,
        entity: dict[str, Any] | None,
    ) -> dict[str, Any]:
        field_names = {field.name for field in spec.input_fields}
        symbol = _entity_symbol(entity)
        arguments: dict[str, Any] = {}
        if "query" in field_names:
            arguments["query"] = effective_query
        if "symbol" in field_names and symbol and tool_name in {"get_index_bars"}:
            arguments["symbol"] = symbol
            arguments.pop("query", None)
        if "sector_name" in field_names and entity:
            sector_name = str(entity.get("display_name") or entity.get("name") or "").strip()
            if sector_name:
                arguments["sector_name"] = sector_name
        if "limit" in field_names and tool_name in _DEFAULT_LIMITS:
            arguments["limit"] = _DEFAULT_LIMITS[tool_name]
        if tool_name == "search_web_news":
            arguments["query"] = effective_query
            arguments["max_results"] = _DEFAULT_LIMITS[tool_name]
            arguments["freshness_days"] = 7
        return arguments


__all__ = ["TusharePlanner"]
