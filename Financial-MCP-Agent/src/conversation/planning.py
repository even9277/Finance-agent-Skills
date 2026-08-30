"""把 Rewrite、Skill 规范和权限快照转换为确定性、有界工具 DAG。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.skills.contracts import RequiredEvidence, ToolPlanStep as SkillToolPlanStep
    from src.skills.loader import LoadedSkillContext, PlannerSkillView

from .contracts import (
    Entity,
    EvidenceDimension,
    EvidenceRequirement,
    RewriteKind,
    RewriteResult,
    RouteFamily,
    SkillEvidenceContract,
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

_SKILL_EVIDENCE_DIMENSIONS: dict[str, EvidenceDimension] = {
    "stock_basic": EvidenceDimension.BASIC_PROFILE,
    "stock_market": EvidenceDimension.MARKET_SNAPSHOT,
    "financial_indicator": EvidenceDimension.FINANCIAL_INDICATOR,
    "income_statement": EvidenceDimension.INCOME_STATEMENT,
    "balance_sheet": EvidenceDimension.BALANCE_SHEET,
    "cashflow_statement": EvidenceDimension.CASHFLOW_STATEMENT,
    "fund_basic": EvidenceDimension.FUND_BASIC,
    "etf_basic": EvidenceDimension.ETF_BASIC,
    "fund_nav": EvidenceDimension.FUND_NAV,
    "fund_daily": EvidenceDimension.FUND_MARKET,
    "fund_share": EvidenceDimension.FUND_SHARE,
    "index_daily": EvidenceDimension.INDEX_DAILY,
    "sector_snapshot": EvidenceDimension.SECTOR_SNAPSHOT,
    "sector_constituents": EvidenceDimension.SECTOR_CONSTITUENTS,
    "web_news": EvidenceDimension.WEB_NEWS,
}

_MARKET_CONTEXT_TOOLS = frozenset(
    {
        "get_index_bars",
        "get_sector_snapshot",
        "get_sector_constituents",
        "search_web_news",
    }
)

_WEB_EVENT_TERMS = (
    "上涨",
    "下跌",
    "涨",
    "跌",
    "拉升",
    "跳水",
    "异动",
    "公告",
    "消息",
    "催化",
    "利好",
    "利空",
)
_WEB_TIME_LABELS = {
    "latest_trading_day": "今日",
    "recent_5_trading_days": "最近一周",
    "unspecified": "近期",
}
_PRIVATE_QUERY_PATTERNS = (
    re.compile(r"(?:持仓|成本价|金额|身份证|手机号|邮箱)[^，。；;]{0,24}"),
    re.compile(r"(?:api[_ -]?key|token|secret|password)[^，。；;\s]{0,32}", re.I),
)


def build_minimal_web_news_query(rewrite: RewriteResult) -> str:
    """只用公开主体、事件词和时间范围构造有界新闻查询。

    Args:
        rewrite: 已完成权威实体解析和时间抽取的本轮改写结果。

    Returns:
        不含历史消息、记忆、用户约束或私密字段的最多 120 字查询。
    """
    entity = rewrite.entity or (rewrite.entities[0] if rewrite.entities else None)
    subject = (
        " ".join(item for item in (entity.name, entity.symbol) if item).strip()
        if entity is not None
        else ""
    )
    effective_query = rewrite.effective_query
    for pattern in _PRIVATE_QUERY_PATTERNS:
        effective_query = pattern.sub(" ", effective_query)
    event = next((term for term in _WEB_EVENT_TERMS if term in effective_query), "异动")
    time_label = _WEB_TIME_LABELS[rewrite.time_scope.value]
    query = re.sub(r"\s+", " ", f"{subject} {time_label} {event} 公告 新闻").strip()
    return query[:120]


def tool_action_fingerprint(tool_name: str, arguments: tuple[ToolArgument, ...]) -> str:
    """为规范化只读工具动作生成稳定去重指纹。"""
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
    *,
    repeat_for_each_subject: bool = False,
) -> tuple[Entity | None, ...]:
    """按工具实体合同选择权威主体，禁止跨主体类型套用调用。"""
    policy = catalog.require(tool_name)
    matching = tuple(
        entity
        for entity in rewrite.entities
        if entity.entity_type in policy.supported_entity_types
    )
    if repeat_for_each_subject and matching:
        return matching
    if matching:
        return (matching[0],)
    if rewrite.entities and tool_name not in _MARKET_CONTEXT_TOOLS:
        return ()
    return (None,)


def build_tool_arguments(
    *,
    tool_name: str,
    entity: Entity | None,
    query: str,
    catalog: ToolGovernanceCatalog,
    template_arguments: Mapping[str, object] | None = None,
) -> tuple[ToolArgument, ...]:
    """按治理 Schema 合并权威主体和 Skill 模板标量参数。

    Args:
        tool_name: 当前治理目录中的稳定工具名。
        entity: 与工具类型匹配的权威主体；筛选型调用可为空。
        query: Rewrite 生成的有效查询，仅作为无主体工具输入。
        catalog: 当前进程的版本化只读治理目录。
        template_arguments: Skill spec 声明的静态标量参数；未知字段被治理 Schema 丢弃。

    Returns:
        名称稳定排序、可交给 Validator 再校验的参数元组。

    Raises:
        ContractViolationError: Skill 模板试图注入非标量参数。
    """
    fields = {item.name for item in catalog.require(tool_name).input_fields}
    values: dict[str, str | int | float | bool] = {}
    if entity is not None and entity.entity_type.value == "sector" and "sector_name" in fields:
        values["sector_name"] = entity.name
    elif entity is not None and "symbol" in fields:
        values["symbol"] = entity.symbol
    elif "query" in fields:
        values["query"] = query
    if "limit" in fields and tool_name in _DEFAULT_LIMITS:
        values["limit"] = _DEFAULT_LIMITS[tool_name]
    for name, value in (template_arguments or {}).items():
        if name not in fields or name in values:
            continue
        if not isinstance(value, (str, int, float, bool)):
            raise ContractViolationError("Skill tool arguments must be governed scalars")
        values[name] = value
    return tuple(
        ToolArgument(name=name, value=value)
        for name, value in sorted(values.items())
    )


def _evidence_dimensions(names: tuple[str, ...], *, required: bool) -> tuple[EvidenceDimension, ...]:
    """把 Skill 证据名转换为领域维度；必需未知维度直接拒绝。"""
    dimensions: list[EvidenceDimension] = []
    for name in names:
        dimension = _SKILL_EVIDENCE_DIMENSIONS.get(name)
        if dimension is None:
            if required:
                raise ContractViolationError(f"unknown required Skill evidence: {name}")
            continue
        if dimension not in dimensions:
            dimensions.append(dimension)
    return tuple(dimensions)


def _build_evidence_contract(spec: RequiredEvidence) -> SkillEvidenceContract:
    """将版本化 RequiredEvidence 投影为执行域不可变合同。"""
    return SkillEvidenceContract(
        must_have_all=_evidence_dimensions(spec.must_have_all, required=True),
        must_have_any=_evidence_dimensions(spec.must_have_any, required=True),
        per_symbol_must_have_any=_evidence_dimensions(
            spec.per_symbol_must_have_any,
            required=True,
        ),
        optional=_evidence_dimensions(spec.optional, required=False),
        min_distinct_symbols=spec.min_distinct_symbols,
    )


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
        skill_context: LoadedSkillContext | None = None,
    ) -> ToolPlan:
        """生成必须再交给 Validator 的只读 DAG。

        Args:
            rewrite: 已校验主语、数据需求和路由判别字段。
            permissions: 本请求冻结的只读工具政策。
            trace_id: 本轮关联 ID，只用于计划追踪，不进入节点名称。
            skill_context: 金融 SOP 的 planner-stage 固定快照；普通数据路由不使用。

        Returns:
            包含结构化参数、指纹和证据需求的未校验计划。

        Raises:
            ContractViolationError: 数据需求没有映射、Skill 快照不一致或工具越权。
        """
        if rewrite.kind is RewriteKind.FINANCIAL_SOP:
            return self._plan_skill(
                rewrite,
                permissions,
                trace_id=trace_id,
                skill_context=skill_context,
            )
        return self._plan_requirements(rewrite, permissions, trace_id=trace_id)

    def _plan_requirements(
        self,
        rewrite: RewriteResult,
        permissions: ToolPermissionSnapshot,
        *,
        trace_id: str,
    ) -> ToolPlan:
        """保持既有 Tushare 数据路由的确定性规划合同。"""
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
                arguments = build_tool_arguments(
                    tool_name=tool_name,
                    entity=entity,
                    query=rewrite.effective_query,
                    catalog=self._catalog,
                )
                steps.append(
                    self._make_step(
                        tool_name,
                        policy.evidence_dimension,
                        True,
                        entity,
                        arguments,
                        len(steps) + 1,
                    )
                )
        return self._build_plan(
            rewrite,
            permissions,
            trace_id=trace_id,
            steps=tuple(steps),
            route_family=RouteFamily.TUSHARE_DATA,
        )

    def _plan_skill(
        self,
        rewrite: RewriteResult,
        permissions: ToolPermissionSnapshot,
        *,
        trace_id: str,
        skill_context: LoadedSkillContext | None,
    ) -> ToolPlan:
        """严格按同一 spec 的模板、证据组和并发限制生成 SOP 计划。"""
        if not rewrite.skill_name or skill_context is None or skill_context.stage != "planner":
            raise ContractViolationError("financial SOP planning requires planner context")
        if (
            skill_context.skill_id != rewrite.skill_name
            or permissions.skill_name != rewrite.skill_name
            or permissions.skill_version != skill_context.skill_version
            or permissions.skill_spec_hash != skill_context.spec_hash
            or permissions.registry_snapshot_hash != skill_context.registry_snapshot_hash
        ):
            raise ContractViolationError("Skill planner context differs from permission snapshot")
        view = cast("PlannerSkillView", skill_context.spec_view)
        steps: list[ToolPlanStep] = []
        for template in view.tool_plan_steps:
            if template.tool not in permissions.allowed_tools:
                continue
            policy = permissions.require(template.tool)
            for entity in _subjects_for_tool(
                rewrite,
                template.tool,
                self._catalog,
                repeat_for_each_subject=template.repeat_for_each_subject,
            ):
                arguments = build_tool_arguments(
                    tool_name=template.tool,
                    entity=entity,
                    query=(
                        build_minimal_web_news_query(rewrite)
                        if template.tool == "search_web_news"
                        else rewrite.effective_query
                    ),
                    catalog=self._catalog,
                    template_arguments=cast("SkillToolPlanStep", template).arguments,
                )
                steps.append(
                    self._make_step(
                        template.tool,
                        policy.evidence_dimension,
                        template.required,
                        entity,
                        arguments,
                        len(steps) + 1,
                        template_step=template.step,
                    )
                )
        if not steps:
            raise ContractViolationError("Skill spec produced no governed plan steps")
        expansion = view.candidate_expansion
        return self._build_plan(
            rewrite,
            permissions,
            trace_id=trace_id,
            steps=tuple(steps),
            route_family=RouteFamily.FINANCIAL_SOP,
            skill_context=skill_context,
            evidence_contract=_build_evidence_contract(view.required_evidence),
            concurrency_limit=view.concurrency.batch_size if view.concurrency.enabled else 1,
            candidate_expansion_top_n=expansion.top_n if expansion else None,
            candidate_expansion_tools=(
                tuple(name for name in expansion.trigger_tools if name in permissions.allowed_tools)
                if expansion
                else ()
            ),
        )

    @staticmethod
    def _make_step(
        tool_name: str,
        dimension: EvidenceDimension,
        required: bool,
        entity: Entity | None,
        arguments: tuple[ToolArgument, ...],
        number: int,
        *,
        template_step: str = "",
    ) -> ToolPlanStep:
        """构造带稳定主体后缀和幂等指纹的计划节点。"""
        subject_suffix = entity.symbol if entity is not None else "query"
        return ToolPlanStep(
            step_id=f"s{number}-{tool_name}-{subject_suffix}",
            tool_name=tool_name,
            symbol=entity.symbol if entity is not None else "",
            evidence_dimension=dimension,
            required=required,
            arguments=arguments,
            idempotency_key=tool_action_fingerprint(tool_name, arguments),
            template_step=template_step,
        )

    @staticmethod
    def _build_plan(
        rewrite: RewriteResult,
        permissions: ToolPermissionSnapshot,
        *,
        trace_id: str,
        steps: tuple[ToolPlanStep, ...],
        route_family: RouteFamily,
        skill_context: LoadedSkillContext | None = None,
        evidence_contract: SkillEvidenceContract | None = None,
        concurrency_limit: int | None = None,
        candidate_expansion_top_n: int | None = None,
        candidate_expansion_tools: tuple[str, ...] = (),
    ) -> ToolPlan:
        """收敛两类规划路径共享的计划身份和个体证据要求。"""
        requirements = tuple(
            EvidenceRequirement(
                dimension=step.evidence_dimension,
                required=step.required,
                entity_symbol=step.symbol or None,
            )
            for step in steps
        )
        plan_seed = "|".join(
            (
                trace_id,
                permissions.snapshot_hash,
                skill_context.spec_hash if skill_context is not None else "",
                *(step.idempotency_key for step in steps),
            )
        )
        return ToolPlan(
            plan_id=f"plan-{hashlib.sha256(plan_seed.encode()).hexdigest()[:16]}",
            trace_id=trace_id,
            route_family=route_family,
            objective=rewrite.effective_query,
            entity=rewrite.entity,
            entities=rewrite.entities,
            steps=steps,
            requirements=requirements,
            skill_name=rewrite.skill_name,
            skill_version=skill_context.skill_version if skill_context is not None else "",
            skill_spec_hash=skill_context.spec_hash if skill_context is not None else "",
            registry_snapshot_hash=(
                skill_context.registry_snapshot_hash if skill_context is not None else ""
            ),
            evidence_contract=evidence_contract,
            concurrency_limit=concurrency_limit,
            candidate_expansion_top_n=candidate_expansion_top_n,
            candidate_expansion_tools=candidate_expansion_tools,
        )
