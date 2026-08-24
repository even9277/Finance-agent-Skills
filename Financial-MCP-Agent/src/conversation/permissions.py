"""从 Rewrite、Skill 快照和工具目录生成最小只读权限。"""

from __future__ import annotations

from .contracts import (
    EntityType,
    RewriteKind,
    RewriteResult,
    SkillCatalogSnapshot,
    ToolPermissionSnapshot,
)
from .errors import ContractViolationError
from .tool_governance import ToolGovernanceCatalog

_REQUIREMENT_TO_TOOL = {
    "stock_basic": "get_stock_basic_info",
    "basic_profile": "get_stock_basic_info",
    "financial_indicator": "get_fina_indicator",
    "fundamental_or_valuation": "get_fina_indicator",
    "income_statement": "get_income",
    "balance_sheet": "get_balance_sheet",
    "cashflow_statement": "get_cashflow",
    "fund_basic": "get_fund_basic_info",
    "fund_nav_or_market": "get_fund_nav",
    "fund_nav": "get_fund_nav",
    "fund_market": "get_fund_market_bars",
    "fund_share": "get_fund_share",
    "sector_snapshot": "get_sector_snapshot",
    "sector_constituents": "get_sector_constituents",
    "index_or_sector_context": "get_index_bars",
    "index_daily": "get_index_bars",
}


def _market_tool(entity_type: EntityType | None) -> str:
    if entity_type is EntityType.FUND:
        return "get_fund_market_bars"
    if entity_type is EntityType.INDEX:
        return "get_index_bars"
    if entity_type is EntityType.SECTOR:
        return "get_sector_snapshot"
    return "get_market_bars"


def tools_for_requirements(rewrite: RewriteResult) -> tuple[str, ...]:
    """把结构化数据需求映射为最小只读工具集合。"""
    entity_type = rewrite.entity.entity_type if rewrite.entity is not None else None
    names: list[str] = []
    for requirement in rewrite.data_requirements:
        if requirement in {"market_snapshot", "current_financial_facts"}:
            name = _market_tool(entity_type)
        elif requirement == "index_or_sector_context" and entity_type is EntityType.SECTOR:
            name = "get_sector_snapshot"
        else:
            name = _REQUIREMENT_TO_TOOL.get(requirement, "")
        if name and name not in names:
            names.append(name)
    return tuple(names)


def permitted_tools_for_requirements(rewrite: RewriteResult) -> tuple[str, ...]:
    """返回首选工具和仅用于有界补证的治理内备用工具。

    Args:
        rewrite: 已结构化的数据需求与权威实体。

    Returns:
        请求级权限可包含的最小候选集合；Planner 仍只选择首选工具。
    """
    names = list(tools_for_requirements(rewrite))
    if (
        rewrite.kind is RewriteKind.TUSHARE_DATA
        and rewrite.entity is not None
        and rewrite.entity.entity_type is EntityType.STOCK
        and "get_market_bars" in names
    ):
        names.append("get_daily_bars")
    return tuple(dict.fromkeys(names))


class ControlledPermissionResolver:
    """将 Skill 声明和治理目录收敛成请求级只读权限快照。"""

    def __init__(
        self,
        *,
        catalog: ToolGovernanceCatalog,
        skill_catalog: SkillCatalogSnapshot,
    ) -> None:
        self._catalog = catalog
        self._skill_catalog = skill_catalog

    def resolve(self, rewrite: RewriteResult) -> ToolPermissionSnapshot:
        """生成 Planner 和 Executor 必须共同使用的冻结权限。

        Args:
            rewrite: 已完成路由主语校验的数据需求合同。

        Returns:
            只包含治理目录内只读工具和输入 Schema 的不可变快照。

        Raises:
            ContractViolationError: Fallback、缺失 Skill 或 Skill 声明未知工具。
        """
        if rewrite.kind is RewriteKind.FINANCIAL_SOP:
            if not rewrite.skill_name:
                raise ContractViolationError("financial SOP rewrite has no selected skill")
            execution_view = self._skill_catalog.execution_view(rewrite.skill_name)
            policies = self._catalog.select(execution_view.allowed_tools)
            source = f"skill:{execution_view.name}:{execution_view.version}"
        elif rewrite.kind is RewriteKind.TUSHARE_DATA:
            tool_names = permitted_tools_for_requirements(rewrite)
            if not tool_names:
                raise ContractViolationError("tushare rewrite has no governed tool mapping")
            policies = self._catalog.select(tool_names)
            source = "route:tushare-data"
        else:
            raise ContractViolationError("fallback rewrite cannot receive tool permissions")
        return ToolPermissionSnapshot.create(
            permissions=policies,
            source=source,
            version=self._catalog.version,
        )
