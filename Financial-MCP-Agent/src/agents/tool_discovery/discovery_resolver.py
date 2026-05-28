from __future__ import annotations

from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field

from src.agents.tool_discovery.capability_index import (
    TushareCapability,
    build_capability_index,
)
from src.agents.tool_discovery.executable_registry import (
    ExecutableToolRegistry,
    ExecutableToolSpec,
    build_default_registry,
)


class ToolDiscoveryResult(BaseModel):
    discovery_trace_id: str
    stage: Literal["pre_discover", "resolve"]
    available_tools: list[str]
    tool_schemas: dict[str, dict[str, Any]]
    selection_reason: dict[str, str]
    filtered_out_tools: dict[str, str] = Field(default_factory=dict)
    missing_capabilities: list[str] = Field(default_factory=list)
    reference_refs: list[str] = Field(default_factory=list)
    matched_capabilities: list[str] = Field(default_factory=list)


_REQUIREMENT_ALIASES = {
    "market_bars": "stock_market",
    "stock_daily": "stock_daily",
    "stock_market": "stock_market",
    "index_context": "index_daily",
    "financial_indicator": "financial_indicator",
    "income": "income_statement",
    "income_statement": "income_statement",
    "balance_sheet": "balance_sheet",
    "balancesheet": "balance_sheet",
    "cashflow": "cashflow_statement",
    "cashflow_statement": "cashflow_statement",
    "sector_snapshot": "sector_snapshot",
    "sector_constituents": "sector_constituents",
    "fund_basic": "fund_basic",
    "fund_nav": "fund_nav",
    "fund_market_bars": "fund_daily",
    "fund_daily": "fund_daily",
    "fund_share": "fund_share",
    "web_news": "web_news",
}

_TOPIC_KEYWORDS = {
    "stock": ("股票", "个股", "公司", "买入", "走势", "行情"),
    "market": ("行情", "走势", "涨", "跌", "成交", "量价", "今天", "最近"),
    "fundamental": ("财务", "财报", "估值", "roe", "利润", "营收", "现金流", "基本面"),
    "fund": ("基金", "etf", "lof", "qdii", "净值", "份额"),
    "sector": ("板块", "行业", "概念", "热点", "成分股"),
    "index": ("指数", "上证", "沪深", "创业板", "中证"),
    "news": ("新闻", "公告", "消息", "利好", "利空", "催化", "原因", "为什么"),
    "sop": ("比较", "筛选", "简报", "解释", "首轮", "研判"),
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


def _new_trace_id() -> str:
    return f"disc_{uuid.uuid4().hex}"


def _entity_type(active_entity: Any) -> str:
    payload = _model_dump(active_entity)
    raw = (
        payload.get("asset_type")
        or payload.get("entity_type")
        or payload.get("type")
        or payload.get("category")
        or ""
    )
    value = str(raw).strip().lower()
    if value in {"stock", "fund", "sector", "index"}:
        return value
    return "none"


def _normalize_requirement(value: str) -> str:
    text = str(value or "").strip()
    return _REQUIREMENT_ALIASES.get(text, text)


class ToolDiscoveryResolver:
    def __init__(
        self,
        *,
        registry: ExecutableToolRegistry | None = None,
        capabilities: list[TushareCapability] | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.capabilities = capabilities or build_capability_index()

    def pre_discover(
        self,
        *,
        active_entity: Any = None,
        final_route: str = "tushare-data",
        coarse_task: str = "",
    ) -> ToolDiscoveryResult:
        entity_type = _entity_type(active_entity)
        text = str(coarse_task or "")
        wanted_topics = {
            topic
            for topic, keywords in _TOPIC_KEYWORDS.items()
            if any(keyword.lower() in text.lower() for keyword in keywords)
        }
        if final_route == "financial-sop":
            wanted_topics.add("sop")
        if entity_type != "none":
            wanted_topics.add(entity_type)
        if not wanted_topics:
            wanted_topics.update({"stock", "market"})

        matched = [
            capability
            for capability in self.capabilities
            if capability.topic in wanted_topics
            or entity_type in capability.supported_entity_types
            or (entity_type == "none" and "none" in capability.supported_entity_types)
        ]
        return self._build_result(
            stage="pre_discover",
            entity_type=entity_type,
            matched_capabilities=matched,
            explicit_tool_hints=[],
            required_evidence=[],
        )

    def resolve(self, rewrite_result: Any, *, active_entity: Any = None) -> ToolDiscoveryResult:
        payload = _model_dump(rewrite_result)
        entity_type = _entity_type(active_entity)
        if entity_type == "none" and payload.get("entities"):
            first_entity = payload.get("entities")[0]
            entity_type = _entity_type(first_entity)

        explicit_tool_hints = [
            str(item).strip()
            for item in (payload.get("candidate_tool_hints") or [])
            if str(item).strip()
        ]
        required_evidence = [
            _normalize_requirement(str(item))
            for item in (payload.get("data_requirements") or [])
            if str(item).strip()
        ]

        required_set = set(required_evidence)
        matched = [
            capability
            for capability in self.capabilities
            if required_set
            and bool(required_set & set(capability.primary_evidence_types))
        ]
        if not matched and explicit_tool_hints:
            hinted_specs = [
                self.registry.spec(name)
                for name in explicit_tool_hints
                if name in self.registry.names()
            ]
            hinted_evidence = {spec.evidence_type for spec in hinted_specs}
            matched = [
                capability
                for capability in self.capabilities
                if hinted_evidence
                & (set(capability.primary_evidence_types) | set(capability.secondary_evidence_types))
            ]
        if not matched:
            matched = self.capabilities

        return self._build_result(
            stage="resolve",
            entity_type=entity_type,
            matched_capabilities=matched,
            explicit_tool_hints=explicit_tool_hints,
            required_evidence=required_evidence,
        )

    def missing_capability_signal(
        self,
        *,
        required_evidence_types: list[str],
        available_tools: list[str],
    ) -> list[str]:
        available_evidence = {
            self.registry.spec(name).evidence_type
            for name in available_tools
            if name in self.registry.names()
        }
        return [
            item
            for item in [_normalize_requirement(value) for value in required_evidence_types]
            if item not in available_evidence
        ]

    def _build_result(
        self,
        *,
        stage: Literal["pre_discover", "resolve"],
        entity_type: str,
        matched_capabilities: list[TushareCapability],
        explicit_tool_hints: list[str],
        required_evidence: list[str],
    ) -> ToolDiscoveryResult:
        names = self.registry.names()
        explicit_hint_set = set(explicit_tool_hints)
        matched_capability_ids = [item.capability_id for item in matched_capabilities]
        matched_evidence: set[str] = set()
        reference_refs: list[str] = []
        for capability in matched_capabilities:
            matched_evidence.update(capability.primary_evidence_types)
            matched_evidence.update(capability.secondary_evidence_types)
            for ref in capability.reference_refs:
                if ref not in reference_refs:
                    reference_refs.append(ref)

        available_tools: list[str] = []
        selection_reason: dict[str, str] = {}
        filtered_out_tools: dict[str, str] = {}

        for name in names:
            spec = self.registry.spec(name)
            blocked_reason = self._filter_reason(
                spec=spec,
                entity_type=entity_type,
                explicit_hint_set=explicit_hint_set,
                matched_evidence=matched_evidence,
            )
            if blocked_reason:
                filtered_out_tools[name] = blocked_reason
                continue
            available_tools.append(name)
            selection_reason[name] = self._selection_reason(
                spec=spec,
                explicit_hint_set=explicit_hint_set,
                matched_evidence=matched_evidence,
            )

        for hint in explicit_tool_hints:
            if hint not in names:
                filtered_out_tools[hint] = "unknown_tool_hint"

        missing_capabilities = self.missing_capability_signal(
            required_evidence_types=required_evidence,
            available_tools=available_tools,
        )
        return ToolDiscoveryResult(
            discovery_trace_id=_new_trace_id(),
            stage=stage,
            available_tools=available_tools,
            tool_schemas={name: self.registry.spec(name).input_schema() for name in available_tools},
            selection_reason=selection_reason,
            filtered_out_tools=filtered_out_tools,
            missing_capabilities=missing_capabilities,
            reference_refs=reference_refs,
            matched_capabilities=matched_capability_ids,
        )

    def _filter_reason(
        self,
        *,
        spec: ExecutableToolSpec,
        entity_type: str,
        explicit_hint_set: set[str],
        matched_evidence: set[str],
    ) -> str:
        if not spec.planner_visible:
            return "planner_hidden"
        if entity_type != "none" and entity_type not in spec.supported_entity_types:
            return "entity_type_mismatch"
        if explicit_hint_set and spec.name not in explicit_hint_set and spec.evidence_type not in matched_evidence:
            return "not_in_candidate_hints_or_capability"
        if matched_evidence and spec.evidence_type not in matched_evidence and spec.name not in explicit_hint_set:
            return "capability_mismatch"
        return ""

    @staticmethod
    def _selection_reason(
        *,
        spec: ExecutableToolSpec,
        explicit_hint_set: set[str],
        matched_evidence: set[str],
    ) -> str:
        if spec.name in explicit_hint_set:
            return "candidate_tool_hint"
        if spec.evidence_type in matched_evidence:
            return "capability_evidence_match"
        return "default_route_baseline"


def build_default_discovery_resolver() -> ToolDiscoveryResolver:
    return ToolDiscoveryResolver()


__all__ = [
    "ToolDiscoveryResolver",
    "ToolDiscoveryResult",
    "build_default_discovery_resolver",
]
