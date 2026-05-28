from __future__ import annotations

from dataclasses import dataclass
import os
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, Field

FreshnessTier = Literal["realtime", "intraday", "daily", "weekly", "quarterly", "static"]
EntityType = Literal["stock", "fund", "sector", "index", "none"]
InputFieldType = Literal["string", "integer", "number", "boolean", "array", "object"]
InputFieldFormat = Literal["date_yyyymmdd", "symbol", "sector_name"]

OUTPUT_ENVELOPE_FIELDS = (
    "ok",
    "source",
    "source_api",
    "evidence_type",
    "symbol",
    "trade_date",
    "data_time",
    "payload",
    "error",
    "cache_hit",
    "retry_count",
    "fetch_ts",
    "api_family",
)


class InputFieldSpec(BaseModel):
    name: str
    type: InputFieldType
    required: bool = False
    pattern: str | None = None
    enum: list[str] | None = None
    format: InputFieldFormat | None = None

    def to_json_schema_property(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type}
        if self.pattern:
            schema["pattern"] = self.pattern
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.format:
            schema["format"] = self.format
        return schema


class ExecutableToolSpec(BaseModel):
    name: str
    namespace: str = "tushare"
    description: str
    supported_entity_types: list[EntityType]
    input_fields: list[InputFieldSpec]
    output_envelope_fields: list[str] = Field(default_factory=lambda: list(OUTPUT_ENVELOPE_FIELDS))
    evidence_type: str
    source_api: str
    api_family: str
    freshness_tier: FreshnessTier
    is_primary_evidence: bool
    read_only: bool = True
    planner_visible: bool = True
    can_retry: bool = True
    rate_limit_group: str
    timeout_ms: int = 8000
    retry_policy: dict[str, Any] = Field(default_factory=lambda: {"max": 1, "backoff_ms": 300})

    def input_schema(self) -> dict[str, Any]:
        properties = {field.name: field.to_json_schema_property() for field in self.input_fields}
        required = [field.name for field in self.input_fields if field.required]
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        return schema

    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {name: {} for name in self.output_envelope_fields},
            "required": ["ok", "source_api", "evidence_type", "payload", "error"],
            "additionalProperties": True,
        }


class ScriptToolSpec(ExecutableToolSpec):
    namespace: str = "script"
    disabled_by_default: bool = True
    sandbox: str = "local"


@dataclass(frozen=True, slots=True)
class RegisteredExecutableTool:
    handler: Any
    spec: ExecutableToolSpec


class ExecutableToolRegistry:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredExecutableTool] = {}

    def register(self, *, handler: Any, spec: ExecutableToolSpec) -> None:
        if spec.name in self._items:
            raise ValueError(f"duplicate executable tool: {spec.name}")
        self._items[spec.name] = RegisteredExecutableTool(handler=handler, spec=spec)

    def register_script_tool(self, *, handler: Any, spec: ScriptToolSpec) -> None:
        if spec.disabled_by_default:
            update = {"planner_visible": False}
            spec = spec.model_copy(update=update) if hasattr(spec, "model_copy") else spec.copy(update=update)
        self.register(handler=handler, spec=spec)

    def get(self, name: str) -> RegisteredExecutableTool:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown executable tool: {name}") from exc

    def spec(self, name: str) -> ExecutableToolSpec:
        return self.get(name).spec

    def handler(self, name: str) -> Any:
        return self.get(name).handler

    def names(self, *, planner_visible_only: bool = False) -> list[str]:
        names = []
        for name, item in self._items.items():
            if planner_visible_only and not item.spec.planner_visible:
                continue
            names.append(name)
        return names

    def specs(self, *, planner_visible_only: bool = False) -> list[ExecutableToolSpec]:
        return [self.spec(name) for name in self.names(planner_visible_only=planner_visible_only)]

    def snapshot(self) -> MappingProxyType[str, RegisteredExecutableTool]:
        return MappingProxyType(dict(self._items))


def _field(
    name: str,
    type_: InputFieldType,
    *,
    required: bool = False,
    pattern: str | None = None,
    format: InputFieldFormat | None = None,
) -> InputFieldSpec:
    return InputFieldSpec(name=name, type=type_, required=required, pattern=pattern, format=format)


_STOCK_QUERY_FIELDS = (
    _field("symbol", "string", format="symbol"),
    _field("query", "string"),
)
_STOCK_QUERY_LIMIT_FIELDS = (
    *_STOCK_QUERY_FIELDS,
    _field("limit", "integer"),
)
_FUND_QUERY_LIMIT_FIELDS = (
    _field("symbol", "string", format="symbol"),
    _field("query", "string"),
    _field("limit", "integer"),
)

_DEFAULT_SPECS: dict[str, ExecutableToolSpec] = {
    "get_stock_basic_info": ExecutableToolSpec(
        name="get_stock_basic_info",
        description="Resolve stock identity, listing metadata, industry, and market board.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_FIELDS),
        evidence_type="stock_basic",
        source_api="stock_basic",
        api_family="stock_basic",
        freshness_tier="static",
        is_primary_evidence=True,
        rate_limit_group="stock_basic",
    ),
    "get_daily_bars": ExecutableToolSpec(
        name="get_daily_bars",
        description="Fetch recent stock daily bars from Tushare daily.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="stock_daily",
        source_api="daily",
        api_family="stock_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="stock_market",
    ),
    "get_market_bars": ExecutableToolSpec(
        name="get_market_bars",
        description="Fetch recent stock market bars from Tushare pro_bar.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="stock_market",
        source_api="pro_bar",
        api_family="stock_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="stock_market",
    ),
    "get_index_bars": ExecutableToolSpec(
        name="get_index_bars",
        description="Fetch index daily bars for common A-share indices.",
        supported_entity_types=["stock", "index", "sector", "none"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="index_daily",
        source_api="index_pro_bar",
        api_family="index_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="index_market",
    ),
    "get_sector_snapshot": ExecutableToolSpec(
        name="get_sector_snapshot",
        description="Fetch Shenwan sector snapshot data.",
        supported_entity_types=["sector", "none"],
        input_fields=[_field("query", "string"), _field("sector_name", "string", format="sector_name")],
        evidence_type="sector_snapshot",
        source_api="sw_daily",
        api_family="sector_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="sector_market",
    ),
    "get_sector_constituents": ExecutableToolSpec(
        name="get_sector_constituents",
        description="Fetch representative constituents for a sector index.",
        supported_entity_types=["sector", "none"],
        input_fields=[
            _field("query", "string"),
            _field("sector_name", "string", format="sector_name"),
            _field("limit", "integer"),
        ],
        evidence_type="sector_constituents",
        source_api="index_member",
        api_family="sector_market",
        freshness_tier="daily",
        is_primary_evidence=False,
        rate_limit_group="sector_market",
    ),
    "get_fund_basic_info": ExecutableToolSpec(
        name="get_fund_basic_info",
        description="Search public funds and ETFs using Tushare fund_basic.",
        supported_entity_types=["fund", "none"],
        input_fields=list(_FUND_QUERY_LIMIT_FIELDS),
        evidence_type="fund_basic",
        source_api="fund_basic",
        api_family="fund_basic",
        freshness_tier="static",
        is_primary_evidence=True,
        rate_limit_group="fund_basic",
    ),
    "get_fund_nav": ExecutableToolSpec(
        name="get_fund_nav",
        description="Fetch recent fund NAV data.",
        supported_entity_types=["fund"],
        input_fields=list(_FUND_QUERY_LIMIT_FIELDS),
        evidence_type="fund_nav",
        source_api="fund_nav",
        api_family="fund_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="fund_market",
    ),
    "get_fund_market_bars": ExecutableToolSpec(
        name="get_fund_market_bars",
        description="Fetch ETF market bars from Tushare fund_daily.",
        supported_entity_types=["fund"],
        input_fields=list(_FUND_QUERY_LIMIT_FIELDS),
        evidence_type="fund_daily",
        source_api="fund_daily",
        api_family="fund_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="fund_market",
    ),
    "get_fund_share": ExecutableToolSpec(
        name="get_fund_share",
        description="Fetch fund share and size data.",
        supported_entity_types=["fund"],
        input_fields=list(_FUND_QUERY_LIMIT_FIELDS),
        evidence_type="fund_share",
        source_api="fund_share",
        api_family="fund_market",
        freshness_tier="daily",
        is_primary_evidence=True,
        rate_limit_group="fund_market",
    ),
    "get_fina_indicator": ExecutableToolSpec(
        name="get_fina_indicator",
        description="Fetch recent financial indicators.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="financial_indicator",
        source_api="fina_indicator",
        api_family="stock_fundamental",
        freshness_tier="quarterly",
        is_primary_evidence=True,
        rate_limit_group="stock_fundamental",
    ),
    "get_income": ExecutableToolSpec(
        name="get_income",
        description="Fetch recent income statement rows.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="income_statement",
        source_api="income",
        api_family="stock_fundamental",
        freshness_tier="quarterly",
        is_primary_evidence=True,
        rate_limit_group="stock_fundamental",
    ),
    "get_balance_sheet": ExecutableToolSpec(
        name="get_balance_sheet",
        description="Fetch recent balance sheet rows.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="balance_sheet",
        source_api="balancesheet",
        api_family="stock_fundamental",
        freshness_tier="quarterly",
        is_primary_evidence=True,
        rate_limit_group="stock_fundamental",
    ),
    "get_cashflow": ExecutableToolSpec(
        name="get_cashflow",
        description="Fetch recent cashflow statement rows.",
        supported_entity_types=["stock"],
        input_fields=list(_STOCK_QUERY_LIMIT_FIELDS),
        evidence_type="cashflow_statement",
        source_api="cashflow",
        api_family="stock_fundamental",
        freshness_tier="quarterly",
        is_primary_evidence=True,
        rate_limit_group="stock_fundamental",
    ),
    "search_web_news": ExecutableToolSpec(
        name="search_web_news",
        namespace="web",
        description="Search recent finance web/news pages as supplementary catalyst evidence.",
        supported_entity_types=["stock", "fund", "sector", "index", "none"],
        input_fields=[
            _field("query", "string", required=True),
            _field("max_results", "integer"),
            _field("freshness_days", "integer"),
        ],
        evidence_type="web_news",
        source_api="ddgs_text",
        api_family="web_news",
        freshness_tier="realtime",
        is_primary_evidence=False,
        rate_limit_group="web_news",
        timeout_ms=10000,
        retry_policy={"max": 0, "backoff_ms": 0},
    ),
}


def default_tool_specs() -> dict[str, ExecutableToolSpec]:
    return dict(_DEFAULT_SPECS)


def build_default_registry() -> ExecutableToolRegistry:
    from src.tools.chat_tushare_tools import get_tushare_toolkit

    registry = ExecutableToolRegistry()
    specs = default_tool_specs()
    disabled_by_points_level = {
        item.strip()
        for item in os.getenv("TUSHARE_DISABLED_TOOLS", os.getenv("DISABLED_BY_POINTS_LEVEL", "")).split(",")
        if item.strip()
    }
    missing_specs: list[str] = []
    for tool in get_tushare_toolkit():
        name = str(getattr(tool, "name", getattr(tool, "__name__", "")) or "")
        spec = specs.get(name)
        if spec is None:
            missing_specs.append(name)
            continue
        if name in disabled_by_points_level or spec.source_api in disabled_by_points_level:
            update = {"planner_visible": False}
            if hasattr(spec, "model_copy"):
                spec = spec.model_copy(update=update)
            else:
                spec = spec.copy(update=update)
        registry.register(handler=tool, spec=spec)
    if missing_specs:
        raise ValueError(f"missing executable tool specs: {missing_specs}")
    return registry


__all__ = [
    "EntityType",
    "ExecutableToolRegistry",
    "ExecutableToolSpec",
    "FreshnessTier",
    "InputFieldSpec",
    "OUTPUT_ENVELOPE_FIELDS",
    "RegisteredExecutableTool",
    "ScriptToolSpec",
    "build_default_registry",
    "default_tool_specs",
]
