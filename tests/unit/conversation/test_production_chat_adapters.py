"""验证生产聊天适配器的安全归一化，不访问真实外部服务。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for path in (ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.infrastructure.chat.providers import TushareToolProvider  # noqa: E402
from src.conversation.contracts import EvidenceDimension, ToolArgument, ToolCall  # noqa: E402
from src.conversation.errors import ToolPermanentError  # noqa: E402


class _OfflineTool:
    """模拟 LangChain StructuredTool 的离线最小接口。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.arguments: dict[str, Any] | None = None

    async def ainvoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.arguments = arguments
        return self._payload


def _call() -> ToolCall:
    return ToolCall(
        step_id="step-1",
        tool_name="get_market_bars",
        symbol="600519.SH",
        evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
        arguments=(
            ToolArgument(name="symbol", value="600519.SH"),
            ToolArgument(name="limit", value=20),
        ),
    )


@pytest.mark.unit
def test_tushare_adapter_normalizes_envelope_without_arbitrary_payload() -> None:
    """确认真实适配器只保留首行标量事实和权威来源日期。"""

    async def run_case() -> None:
        tool = _OfflineTool(
            {
                "ok": True,
                "source_api": "pro_bar",
                "trade_date": "20260824",
                "payload": [
                    {"ts_code": "600519.SH", "close": 1688.0, "nested": {"unsafe": True}},
                    {"ts_code": "OTHER", "close": 1},
                ],
            }
        )
        provider = TushareToolProvider()
        provider._tools = {"get_market_bars": tool}  # type: ignore[assignment]

        observation = await provider.execute(_call())

        assert tool.arguments == {"symbol": "600519.SH", "limit": 20}
        assert observation.source == "tushare:pro_bar"
        assert observation.observed_at.isoformat() == "2026-08-24"
        assert [(item.key, item.value) for item in observation.facts] == [
            ("ts_code", "600519.SH"),
            ("close", "1688.0"),
        ]

    asyncio.run(run_case())


@pytest.mark.unit
def test_tushare_adapter_maps_provider_failure_to_stable_domain_error() -> None:
    """确认 Provider 原始错误不会作为 Evidence 内容进入主链。"""

    async def run_case() -> None:
        tool = _OfflineTool(
            {"ok": False, "error": "token=secret production database internal detail"}
        )
        provider = TushareToolProvider()
        provider._tools = {"get_market_bars": tool}  # type: ignore[assignment]

        with pytest.raises(ToolPermanentError, match="tushare tool execution failed"):
            await provider.execute(_call())

    asyncio.run(run_case())
