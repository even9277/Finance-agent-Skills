from __future__ import annotations

from pydantic import BaseModel, Field

from src.agents.tool_discovery.executable_registry import EntityType, FreshnessTier


class TushareCapability(BaseModel):
    capability_id: str
    topic: str
    api_family: str
    description: str
    supported_entity_types: list[EntityType]
    primary_evidence_types: list[str]
    secondary_evidence_types: list[str] = Field(default_factory=list)
    freshness_tier: FreshnessTier
    reference_refs: list[str] = Field(default_factory=list)


_CAPABILITIES: tuple[TushareCapability, ...] = (
    TushareCapability(
        capability_id="stock.identity",
        topic="stock",
        api_family="stock_basic",
        description="Resolve stock identity, exchange suffix, listing metadata, industry, and market board.",
        supported_entity_types=["stock"],
        primary_evidence_types=["stock_basic"],
        freshness_tier="static",
    ),
    TushareCapability(
        capability_id="stock.daily_quote",
        topic="market",
        api_family="stock_market",
        description="Fetch daily stock quotes for recent price and volume facts.",
        supported_entity_types=["stock"],
        primary_evidence_types=["stock_daily", "stock_market"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="stock.realtime_context",
        topic="market",
        api_family="stock_market",
        description="Fetch recent market bars for today/recent movement analysis.",
        supported_entity_types=["stock"],
        primary_evidence_types=["stock_market"],
        secondary_evidence_types=["stock_basic"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="stock.financial_indicators",
        topic="fundamental",
        api_family="stock_fundamental",
        description="Fetch profitability, growth, valuation, and operating indicator rows.",
        supported_entity_types=["stock"],
        primary_evidence_types=["financial_indicator"],
        secondary_evidence_types=["income_statement", "balance_sheet", "cashflow_statement"],
        freshness_tier="quarterly",
    ),
    TushareCapability(
        capability_id="stock.income_statement",
        topic="fundamental",
        api_family="stock_fundamental",
        description="Fetch revenue and profit statement evidence.",
        supported_entity_types=["stock"],
        primary_evidence_types=["income_statement"],
        freshness_tier="quarterly",
    ),
    TushareCapability(
        capability_id="stock.balance_sheet",
        topic="fundamental",
        api_family="stock_fundamental",
        description="Fetch balance sheet quality evidence.",
        supported_entity_types=["stock"],
        primary_evidence_types=["balance_sheet"],
        freshness_tier="quarterly",
    ),
    TushareCapability(
        capability_id="stock.cashflow_statement",
        topic="fundamental",
        api_family="stock_fundamental",
        description="Fetch operating and free cashflow evidence.",
        supported_entity_types=["stock"],
        primary_evidence_types=["cashflow_statement"],
        freshness_tier="quarterly",
    ),
    TushareCapability(
        capability_id="index.market_bars",
        topic="index",
        api_family="index_market",
        description="Fetch A-share index bars for market comparison and benchmark context.",
        supported_entity_types=["index", "sector", "none"],
        primary_evidence_types=["index_daily"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="sector.snapshot",
        topic="sector",
        api_family="sector_market",
        description="Fetch Shenwan sector daily snapshot evidence.",
        supported_entity_types=["sector", "none"],
        primary_evidence_types=["sector_snapshot"],
        secondary_evidence_types=["index_daily"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="sector.constituents",
        topic="sector",
        api_family="sector_market",
        description="Fetch representative sector constituents for breadth and attribution.",
        supported_entity_types=["sector", "none"],
        primary_evidence_types=["sector_constituents"],
        secondary_evidence_types=["stock_market"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="fund.discovery",
        topic="fund",
        api_family="fund_basic",
        description="Search fund and ETF candidates by natural-language query or code.",
        supported_entity_types=["fund", "none"],
        primary_evidence_types=["fund_basic"],
        freshness_tier="static",
    ),
    TushareCapability(
        capability_id="fund.nav",
        topic="fund",
        api_family="fund_market",
        description="Fetch fund NAV evidence for recent performance and comparison.",
        supported_entity_types=["fund"],
        primary_evidence_types=["fund_nav"],
        secondary_evidence_types=["fund_basic"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="fund.market_bars",
        topic="fund",
        api_family="fund_market",
        description="Fetch ETF exchange-traded bar evidence.",
        supported_entity_types=["fund"],
        primary_evidence_types=["fund_daily"],
        secondary_evidence_types=["fund_basic"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="fund.share_size",
        topic="fund",
        api_family="fund_market",
        description="Fetch fund share and size evidence for liquidity and scale checks.",
        supported_entity_types=["fund"],
        primary_evidence_types=["fund_share"],
        secondary_evidence_types=["fund_basic"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="news.catalyst_clues",
        topic="news",
        api_family="web_news",
        description="Search recent finance news as weak supplementary catalyst clues.",
        supported_entity_types=["stock", "fund", "sector", "index", "none"],
        primary_evidence_types=["web_news"],
        freshness_tier="realtime",
    ),
    TushareCapability(
        capability_id="stock.first_pass",
        topic="sop",
        api_family="stock_market",
        description="Support first-pass single stock analysis with identity, market, and fundamentals.",
        supported_entity_types=["stock"],
        primary_evidence_types=["stock_basic", "stock_market", "financial_indicator"],
        secondary_evidence_types=["income_statement", "balance_sheet", "cashflow_statement", "web_news"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="fund.compare",
        topic="sop",
        api_family="fund_market",
        description="Support fund comparison with fund identity plus NAV, market, or share evidence.",
        supported_entity_types=["fund"],
        primary_evidence_types=["fund_basic", "fund_nav", "fund_daily", "fund_share"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="etf.screen",
        topic="sop",
        api_family="fund_market",
        description="Support ETF screening with candidate discovery and tradable evidence.",
        supported_entity_types=["fund", "none"],
        primary_evidence_types=["fund_basic", "fund_daily"],
        secondary_evidence_types=["fund_nav", "fund_share"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="sector.hotspot_brief",
        topic="sop",
        api_family="sector_market",
        description="Support sector hotspot briefing with sector snapshot and constituents.",
        supported_entity_types=["sector", "none"],
        primary_evidence_types=["sector_snapshot", "sector_constituents"],
        secondary_evidence_types=["index_daily", "web_news"],
        freshness_tier="daily",
    ),
    TushareCapability(
        capability_id="market.move_explain",
        topic="sop",
        api_family="stock_market",
        description="Support market move explanations with market facts plus optional news clues.",
        supported_entity_types=["stock", "sector", "index", "none"],
        primary_evidence_types=["stock_market", "sector_snapshot", "index_daily"],
        secondary_evidence_types=["web_news", "sector_constituents"],
        freshness_tier="daily",
    ),
)


def build_capability_index() -> list[TushareCapability]:
    return list(_CAPABILITIES)


def evidence_types_for_capability(capability_id: str) -> set[str]:
    for capability in _CAPABILITIES:
        if capability.capability_id == capability_id:
            return set(capability.primary_evidence_types) | set(capability.secondary_evidence_types)
    raise KeyError(f"unknown capability: {capability_id}")


__all__ = [
    "TushareCapability",
    "build_capability_index",
    "evidence_types_for_capability",
]
