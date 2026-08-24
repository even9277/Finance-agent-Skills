"""定义受控主链唯一的只读工具 Schema 与治理目录。"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    EntityType,
    EvidenceDimension,
    ToolArgumentKind,
    ToolInputSpec,
    ToolPolicy,
)
from .errors import ContractViolationError

_SYMBOL = ToolInputSpec(name="symbol", kind=ToolArgumentKind.STRING)
_QUERY = ToolInputSpec(name="query", kind=ToolArgumentKind.STRING)
_SECTOR_NAME = ToolInputSpec(name="sector_name", kind=ToolArgumentKind.STRING)
_LIMIT = ToolInputSpec(
    name="limit",
    kind=ToolArgumentKind.INTEGER,
    minimum=1,
    maximum=100,
)


def _policy(
    tool_name: str,
    dimension: EvidenceDimension,
    entity_types: tuple[EntityType, ...],
    *fields: ToolInputSpec,
) -> ToolPolicy:
    """构造同属 Tushare 只读族、允许瞬时重试的工具政策。"""
    return ToolPolicy(
        tool_name=tool_name,
        evidence_dimension=dimension,
        supported_entity_types=entity_types,
        input_fields=tuple(fields),
        api_family="tushare-read",
        retryable=True,
    )


_DEFAULT_POLICIES = (
    _policy(
        "get_stock_basic_info",
        EvidenceDimension.BASIC_PROFILE,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
    ),
    _policy(
        "get_daily_bars",
        EvidenceDimension.MARKET_SNAPSHOT,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_market_bars",
        EvidenceDimension.MARKET_SNAPSHOT,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_fina_indicator",
        EvidenceDimension.FINANCIAL_INDICATOR,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_income",
        EvidenceDimension.INCOME_STATEMENT,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_balance_sheet",
        EvidenceDimension.BALANCE_SHEET,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_cashflow",
        EvidenceDimension.CASHFLOW_STATEMENT,
        (EntityType.STOCK,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_index_bars",
        EvidenceDimension.INDEX_DAILY,
        (EntityType.INDEX,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_sector_snapshot",
        EvidenceDimension.SECTOR_SNAPSHOT,
        (EntityType.SECTOR,),
        _QUERY,
        _SECTOR_NAME,
    ),
    _policy(
        "get_sector_constituents",
        EvidenceDimension.SECTOR_CONSTITUENTS,
        (EntityType.SECTOR,),
        _QUERY,
        _SECTOR_NAME,
        _LIMIT,
    ),
    _policy(
        "get_fund_basic_info",
        EvidenceDimension.FUND_BASIC,
        (EntityType.FUND,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_etf_basic_info",
        EvidenceDimension.ETF_BASIC,
        (EntityType.FUND,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_fund_nav",
        EvidenceDimension.FUND_NAV,
        (EntityType.FUND,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_fund_market_bars",
        EvidenceDimension.FUND_MARKET,
        (EntityType.FUND,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
    _policy(
        "get_fund_share",
        EvidenceDimension.FUND_SHARE,
        (EntityType.FUND,),
        _SYMBOL,
        _QUERY,
        _LIMIT,
    ),
)


@dataclass(frozen=True, slots=True)
class ToolGovernanceCatalog:
    """保存版本化只读工具政策，不持有 SDK、凭证或可执行 handler。"""

    policies: tuple[ToolPolicy, ...]
    version: str = "controlled-read-tools-v1"

    def __post_init__(self) -> None:
        names = tuple(item.tool_name for item in self.policies)
        if len(names) != len(set(names)):
            raise ContractViolationError("tool governance catalog contains duplicate tools")

    @classmethod
    def default(cls) -> ToolGovernanceCatalog:
        """构建与当前 Chat Tushare 工具签名一致的只读目录。"""
        return cls(policies=tuple(sorted(_DEFAULT_POLICIES, key=lambda item: item.tool_name)))

    def require(self, tool_name: str) -> ToolPolicy:
        """返回已登记政策；未知工具在进入计划前失败。"""
        for policy in self.policies:
            if policy.tool_name == tool_name:
                return policy
        raise ContractViolationError(f"tool is absent from governance catalog: {tool_name}")

    def select(self, tool_names: tuple[str, ...]) -> tuple[ToolPolicy, ...]:
        """按请求白名单选择政策并保持稳定排序。"""
        return tuple(self.require(name) for name in sorted(set(tool_names)))
