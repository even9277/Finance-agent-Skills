"""锁定迁移前 Router/Executor 的离线决策与失败归一化行为。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.agents import skill_executor_node, skill_router_node  # noqa: E402

ROUTE_CASES_PATH = ROOT / "tests" / "fixtures" / "conversation" / "legacy_route_cases.json"


def _load_route_cases() -> list[dict[str, Any]]:
    """读取版本化离线路由案例，防止测试隐式依赖真实模型。"""
    payload = json.loads(ROUTE_CASES_PATH.read_text(encoding="utf-8"))
    assert payload["fixture_version"] == "legacy-chat-characterization-v1"
    return list(payload["cases"])


@pytest.mark.unit
@pytest.mark.parametrize("case", _load_route_cases(), ids=lambda case: str(case["case_id"]))
def test_legacy_router_rules_remain_available_without_model(case: dict[str, Any]) -> None:
    """确认模型不可用时，当前规则路由仍返回冻结的兼容决策。"""

    async def run_case() -> None:
        # 两个模型选择点都固定返回 None，保证默认测试不会访问真实 API。
        with patch.object(
            skill_router_node,
            "_llm_select_financial_sop_skill",
            new=AsyncMock(return_value=None),
        ), patch.object(
            skill_router_node,
            "_llm_route_with_context",
            new=AsyncMock(return_value=None),
        ):
            decision = await skill_router_node.route_chat_skill(
                case["message"],
                conversation_context=case["conversation_context"],
            )

        assert decision.selected_skill_family == case["expected_skill_family"]
        assert decision.selected_skill == case["expected_skill"]
        assert decision.skill_name == case["expected_skill_name"]
        assert decision.analysis_mode == case["expected_analysis_mode"]
        assert decision.arguments["router_model"].endswith("rule-based")

    asyncio.run(run_case())


@pytest.mark.unit
def test_legacy_router_swallows_model_failure_and_uses_rules() -> None:
    """刻画当前 Router 对模型异常静默降级到规则路由的行为。"""

    async def run_case() -> None:
        with patch.object(
            skill_router_node,
            "_route_financial_sop",
            new=AsyncMock(return_value=None),
        ), patch.object(
            skill_router_node,
            "_llm_route_with_context",
            new=AsyncMock(side_effect=RuntimeError("offline model unavailable")),
        ):
            decision = await skill_router_node.route_chat_skill("查询 600519.SH 最新行情")

        assert decision.selected_skill == "tushare-data"
        assert decision.analysis_mode == "single_stock_data"
        assert decision.arguments["router_model"] == "rule-based"

    asyncio.run(run_case())


@pytest.mark.unit
def test_legacy_executor_fallback_never_builds_model_or_tools() -> None:
    """确认 fallback 路由只返回控制信号，不在 Executor 内调用模型或工具。"""

    async def run_case() -> None:
        with patch.object(
            skill_executor_node,
            "_build_model",
            side_effect=AssertionError("fallback 不应创建模型"),
        ), patch.object(
            skill_executor_node,
            "_run_tool_batch",
            new=AsyncMock(side_effect=AssertionError("fallback 不应执行工具")),
        ):
            result = await skill_executor_node.execute_skill(
                selected_skill="fallback",
                user_message="解释 ETF 和 LOF 的区别",
                route_trace={
                    "selected_skill_family": "fallback",
                    "analysis_mode": "general_chat",
                    "confidence": 0.9,
                },
            )

        assert result.selected_skill == "fallback"
        assert result.reply_text == ""
        assert result.used_fallback is True
        assert result.trace == {"reason": "fallback route"}

    asyncio.run(run_case())


@pytest.mark.unit
def test_legacy_executor_disabled_skill_returns_explainable_result() -> None:
    """确认 Tushare Skill 关闭时返回明确降级，而不是访问真实工具。"""

    async def run_case() -> None:
        with patch.object(
            skill_executor_node,
            "_build_model",
            side_effect=AssertionError("禁用 Skill 不应创建模型"),
        ), patch.object(
            skill_executor_node,
            "_run_tool_batch",
            new=AsyncMock(side_effect=AssertionError("禁用 Skill 不应执行工具")),
        ):
            result = await skill_executor_node.execute_skill(
                selected_skill="tushare-data",
                user_message="查询 600519.SH 最新行情",
                route_trace={
                    "selected_skill_family": "tushare-data",
                    "analysis_mode": "single_stock_data",
                    "confidence": 0.9,
                },
                enable_tushare_skills=False,
            )

        assert result.selected_skill == "tushare-data"
        assert result.used_fallback is False
        assert result.trace == {"enabled": False, "reason": "skill disabled"}
        assert "当前能力暂未启用" in result.reply_text

    asyncio.run(run_case())


@pytest.mark.unit
def test_legacy_executor_normalizes_concurrent_tool_exception_in_order() -> None:
    """确认并发工具异常被归一化为失败结果，并保持原计划顺序。"""

    async def fake_invoke(tool_name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if tool_name == "broken_tool":
            raise TimeoutError("offline fixture timeout")
        return tool_name, {
            "ok": True,
            "source": "fixture",
            "symbol": arguments["symbol"],
            "payload": [{"close": 100.0}],
        }

    async def run_case() -> None:
        calls = [
            {"tool_name": "good_tool", "arguments": {"symbol": "600519.SH"}},
            {"tool_name": "broken_tool", "arguments": {"symbol": "000001.SZ"}},
        ]
        with patch.object(skill_executor_node, "_invoke_tool", side_effect=fake_invoke):
            results = await skill_executor_node._run_tool_batch(calls, concurrent=True)

        assert [name for name, _ in results] == ["good_tool", "broken_tool"]
        assert results[0][1]["ok"] is True
        assert results[1][1]["ok"] is False
        assert results[1][1]["symbol"] == "000001.SZ"
        assert results[1][1]["error"] == "offline fixture timeout"

    asyncio.run(run_case())


@pytest.mark.unit
def test_legacy_executor_policy_violation_preserves_plan_order() -> None:
    """确认工具白名单校验按计划顺序报告越权项。"""
    violations = skill_executor_node._policy_violation_names(
        ["stock_basic", "trade_order", "daily", "portfolio_write"],
        ["stock_basic", "daily"],
    )

    assert violations == ["trade_order", "portfolio_write"]
