"""确认离线 E2E 使用的 Fake Model/Tool/MCP Provider 不访问外部服务。"""

import asyncio

import pytest

from tests.fixtures.fake_providers import FakeMcpProvider, FakeModelProvider, FakeToolProvider


@pytest.mark.e2e
def test_fake_provider_chain_is_deterministic() -> None:
    async def run_check() -> None:
        model = FakeModelProvider()
        tool = FakeToolProvider()
        mcp = FakeMcpProvider()

        answer = await model.complete("fixed prompt")
        quote = await tool.read_market_data("000001.SZ")
        resource = await mcp.read_resource("fixture://evidence")

        assert answer == "fake-provider: answer"
        assert quote == {"symbol": "000001.SZ", "close": "100.00", "as_of": "2026-01-01"}
        assert resource == "fake-resource:fixture://evidence"
        assert model.calls == ["fixed prompt"]
        assert tool.calls == ["000001.SZ"]
        assert mcp.calls == ["fixture://evidence"]

    asyncio.run(run_check())
