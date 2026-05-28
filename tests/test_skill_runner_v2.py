import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.skill_runner_v2 import run_sop_v2_pipeline, run_tushare_v2_pipeline  # noqa: E402
from src.agents.tool_discovery.executable_registry import (  # noqa: E402
    ExecutableToolRegistry,
    ExecutableToolSpec,
    InputFieldSpec,
)


class _Config:
    per_tool_timeout_ms = 1000
    per_tool_retry_limit = 0
    max_steps = 4
    total_timeout_ms = 5000
    max_replans = 1
    executor_max_concurrency = 2
    executor_per_api_family_limit = 1
    executor_min_interval_ms = 0
    verifier_sufficient_threshold = 80
    verifier_partial_threshold = 60
    enable_skill_loader_v2 = False
    skill_loader_token_budget_per_stage = 2048


async def _fake_market_bars(**kwargs):
    return {
        "ok": True,
        "source": "tushare",
        "source_api": "pro_bar",
        "evidence_type": "stock_market",
        "symbol": "600519.SH",
        "trade_date": "20260520",
        "payload": {"rows": [{"close": 1688.0}]},
    }


def _registry() -> ExecutableToolRegistry:
    registry = ExecutableToolRegistry()
    registry.register(
        handler=_fake_market_bars,
        spec=ExecutableToolSpec(
            name="get_market_bars",
            description="fake market bars",
            supported_entity_types=["stock"],
            input_fields=[InputFieldSpec(name="query", type="string")],
            evidence_type="stock_market",
            source_api="pro_bar",
            api_family="stock_market",
            freshness_tier="daily",
            is_primary_evidence=True,
            rate_limit_group="stock_market",
        ),
    )
    return registry


def test_run_tushare_v2_pipeline_builds_trace_artifacts():
    result = asyncio.run(
        run_tushare_v2_pipeline(
            rewrite_result={
                "effective_query": "贵州茅台最近走势",
                "data_requirements": ["stock_market"],
                "candidate_tool_hints": ["get_market_bars"],
                "time_scope": {},
            },
            active_entity={"asset_type": "stock", "symbol": "600519.SH", "display_name": "贵州茅台"},
            trace_id="trace-test",
            config=_Config(),
            registry=_registry(),
        )
    )
    tool_data = result.tool_data()
    assert tool_data["plan"]["plan_id"]
    assert tool_data["plan_preview"]
    assert tool_data["verification"]["allowed_claim_level"] == "analytical"
    assert tool_data["executor_trace"]["plan_id"] == tool_data["plan"]["plan_id"]
    assert any(event["type"] == "plan_preview" for event in tool_data["step_status_events"])
    assert any(event["type"] == "verification_summary" for event in tool_data["step_status_events"])


def test_run_sop_v2_pipeline_includes_loader_artifacts_when_enabled():
    class _LoaderConfig(_Config):
        enable_skill_loader_v2 = True

    result = asyncio.run(
        run_sop_v2_pipeline(
            skill_name="stock-first-pass",
            skill_spec={
                "skill_name": "stock-first-pass",
                "tool_plan_steps": [{"tool": "get_market_bars", "required": True, "arguments": {"query": "贵州茅台", "limit": 1}}],
            },
            user_message="贵州茅台怎么看",
            rewrite_result={
                "effective_query": "贵州茅台怎么看",
                "entities": [{"asset_type": "stock", "symbol": "600519.SH", "display_name": "贵州茅台"}],
            },
            active_entity={"asset_type": "stock", "symbol": "600519.SH", "display_name": "贵州茅台"},
            trace_id="trace-sop",
            config=_LoaderConfig(),
            registry=_registry(),
        )
    )
    trace = result.tool_data()["executor_trace"]
    assert trace["skill_loader_artifacts"]
    assert trace["registry_version"]
