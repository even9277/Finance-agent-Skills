"""锁定报告入口对共享实体解析失败的 fail-closed 语义。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import agent_service
from backend.services import stock_resolver
from src.conversation.contracts import (
    ContextPacket,
    Entity,
    EntityResolutionResult,
    EntityResolverPath,
    EntityType,
)


class _Resolver:
    """返回固定领域结果的共享 Resolver fake。"""

    def __init__(self, result: EntityResolutionResult) -> None:
        self.result = result
        self.packets: list[ContextPacket] = []

    async def resolve(self, packet: ContextPacket) -> EntityResolutionResult:
        """记录当前轮边界并返回固定结果。"""
        self.packets.append(packet)
        return self.result


@pytest.mark.unit
def test_report_initial_state_rejects_unconfirmed_stock() -> None:
    """共享 Resolver 未确认唯一股票时不得构造可执行 AgentState。"""
    with patch.object(
        agent_service,
        "resolve_stock",
        new=AsyncMock(return_value=(None, None)),
    ):
        with pytest.raises(agent_service.ReportEntityResolutionError) as captured:
            asyncio.run(agent_service._build_initial_state("分析一家不存在的公司"))

    assert captured.value.error_code == "REPORT_ENTITY_UNRESOLVED"


@pytest.mark.unit
def test_report_adapter_maps_shared_canonical_stock_without_second_strategy() -> None:
    """报告只做格式适配，不得再次解析名称或猜测代码。"""
    entity = Entity("601012.SH", "隆基绿能", EntityType.STOCK)
    resolver = _Resolver(
        EntityResolutionResult(
            entity=entity,
            candidates=(entity,),
            resolved_entities=(entity,),
            inherited=False,
            confidence=0.96,
            resolver_path=EntityResolverPath.MODEL_FALLBACK,
        )
    )

    with patch.object(stock_resolver, "get_entity_resolver", return_value=resolver):
        company_name, stock_code = asyncio.run(stock_resolver.resolve_stock("研究隆基绿能"))

    assert (company_name, stock_code) == ("隆基绿能", "sh.601012")
    assert resolver.packets == [ContextPacket(current_message="研究隆基绿能")]


@pytest.mark.unit
def test_report_adapter_rejects_non_stock_entity() -> None:
    """基金/指数/板块不能进入只支持个股的报告工作流。"""
    entity = Entity("000300.SH", "沪深300", EntityType.INDEX)
    resolver = _Resolver(
        EntityResolutionResult(
            entity=entity,
            candidates=(entity,),
            resolved_entities=(entity,),
            inherited=False,
            confidence=1.0,
        )
    )

    with patch.object(stock_resolver, "get_entity_resolver", return_value=resolver):
        with pytest.raises(stock_resolver.ReportEntityResolutionError):
            asyncio.run(stock_resolver.resolve_stock("分析沪深300"))


@pytest.mark.unit
def test_report_adapter_rejects_malformed_stock_symbol() -> None:
    """薄 Adapter 仍需防止非法 canonical symbol 污染旧报告状态。"""
    entity = Entity("ABCDEF.SH", "异常标的", EntityType.STOCK)
    resolver = _Resolver(
        EntityResolutionResult(
            entity=entity,
            candidates=(entity,),
            resolved_entities=(entity,),
            inherited=False,
            confidence=1.0,
        )
    )

    with patch.object(stock_resolver, "get_entity_resolver", return_value=resolver):
        with pytest.raises(stock_resolver.ReportEntityResolutionError):
            asyncio.run(stock_resolver.resolve_stock("分析异常标的"))
