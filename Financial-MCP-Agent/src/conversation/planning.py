"""把 Rewrite 和权限快照转换为确定性、有界工具 DAG。"""

from __future__ import annotations

import hashlib
import json

from .contracts import (
    Entity,
    EvidenceRequirement,
    RewriteKind,
    RewriteResult,
    RouteFamily,
    ToolArgument,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
)
from .errors import ContractViolationError
from .permissions import tools_for_requirements
from .tool_governance import ToolGovernanceCatalog

_DEFAULT_LIMITS = {
    "get_daily_bars": 20,
    "get_market_bars": 20,
    "get_index_bars": 10,
    "get_sector_constituents": 12,
    "get_fund_basic_info": 5,
    "get_etf_basic_info": 5,
    "get_fund_nav": 6,
    "get_fund_market_bars": 10,
    "get_fund_share": 6,
    "get_fina_indicator": 6,
    "get_income": 4,
    "get_balance_sheet": 4,
    "get_cashflow": 4,
}


def _fingerprint(tool_name: str, arguments: tuple[ToolArgument, ...]) -> str:
    payload = json.dumps(
        {item.name: item.value for item in arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(f"{tool_name}|{payload}".encode()).hexdigest()


def _subjects_for_tool(
    rewrite: RewriteResult,
    tool_name: str,
    catalog: ToolGovernanceCatalog,
) -> tuple[Entity | None, ...]:
    policy = catalog.require(tool_name)
    matching = tuple(
        entity
        for entity in rewrite.entities
        if entity.entity_type in policy.supported_entity_types
    )
    if rewrite.skill_name == "fund-compare" and matching:
        return matching
    if matching:
        return (matching[0],)
    return (None,)


def _arguments(
    *,
    tool_name: str,
    entity: Entity | None,
    query: str,
    catalog: ToolGovernanceCatalog,
) -> tuple[ToolArgument, ...]:
    fields = {item.name for item in catalog.require(tool_name).input_fields}
    values: list[ToolArgument] = []
    if entity is not None and entity.entity_type.value == "sector" and "sector_name" in fields:
        values.append(ToolArgument(name="sector_name", value=entity.name))
    elif entity is not None and "symbol" in fields:
        values.append(ToolArgument(name="symbol", value=entity.symbol))
    elif "query" in fields:
        values.append(ToolArgument(name="query", value=query))
    if "limit" in fields and tool_name in _DEFAULT_LIMITS:
        values.append(ToolArgument(name="limit", value=_DEFAULT_LIMITS[tool_name]))
    return tuple(sorted(values, key=lambda item: item.name))


class ControlledPlanner:
    """只生成可复现计划，不执行工具、不扩大权限也不读取 SDK。"""

    def __init__(self, *, catalog: ToolGovernanceCatalog) -> None:
        self._catalog = catalog

    def plan(
        self,
        rewrite: RewriteResult,
        permissions: ToolPermissionSnapshot,
        *,
        trace_id: str,
    ) -> ToolPlan:
        """生成必须再交给 Validator 的只读 DAG。

        Args:
            rewrite: 已校验主语、数据需求和路由判别字段。
            permissions: 本请求冻结的只读工具政策。
            trace_id: 本轮关联 ID，只用于计划追踪，不进入节点名称。

        Returns:
            包含结构化参数、指纹和证据需求的未校验计划。

        Raises:
            ContractViolationError: 数据需求没有映射或所需工具不在权限快照。
        """
        selected_tools = tools_for_requirements(rewrite)
        if not selected_tools:
            raise ContractViolationError("rewrite cannot be mapped to a governed tool plan")
        missing = tuple(name for name in selected_tools if name not in permissions.allowed_tools)
        if missing:
            raise ContractViolationError(
                f"required tools are outside the permission snapshot: {','.join(missing)}"
            )

        steps: list[ToolPlanStep] = []
        for tool_name in selected_tools:
            policy = permissions.require(tool_name)
            for entity in _subjects_for_tool(rewrite, tool_name, self._catalog):
                arguments = _arguments(
                    tool_name=tool_name,
                    entity=entity,
                    query=rewrite.effective_query,
                    catalog=self._catalog,
                )
                step_number = len(steps) + 1
                subject_suffix = entity.symbol if entity is not None else "query"
                steps.append(
                    ToolPlanStep(
                        step_id=f"s{step_number}-{tool_name}-{subject_suffix}",
                        tool_name=tool_name,
                        symbol=entity.symbol if entity is not None else "",
                        evidence_dimension=policy.evidence_dimension,
                        required=True,
                        arguments=arguments,
                        idempotency_key=_fingerprint(tool_name, arguments),
                    )
                )

        dimensions = tuple(dict.fromkeys(step.evidence_dimension for step in steps))
        requirements = tuple(
            EvidenceRequirement(dimension=dimension, required=True) for dimension in dimensions
        )
        route_family = (
            RouteFamily.FINANCIAL_SOP
            if rewrite.kind is RewriteKind.FINANCIAL_SOP
            else RouteFamily.TUSHARE_DATA
        )
        plan_seed = "|".join(
            (trace_id, permissions.snapshot_hash, *(step.idempotency_key for step in steps))
        )
        return ToolPlan(
            plan_id=f"plan-{hashlib.sha256(plan_seed.encode()).hexdigest()[:16]}",
            trace_id=trace_id,
            route_family=route_family,
            objective=rewrite.effective_query,
            entity=rewrite.entity,
            entities=rewrite.entities,
            steps=tuple(steps),
            requirements=requirements,
        )
