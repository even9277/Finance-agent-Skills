from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path("Financial-MCP-Agent").resolve()))

from importlib.util import find_spec

pytestmark = pytest.mark.skipif(
    find_spec("src.agents.executor") is None,
    reason="依赖受控主链 executor 模块，待 M2 迁移后自动启用",
)


def _tool_snapshots() -> dict[str, Any]:
    return json.loads(Path("tests/evals/_fixtures/tool_snapshots.json").read_text(encoding="utf-8"))


@pytest.mark.eval_smoke
def test_executor_smoke_replays_artificial_tool_fixtures() -> None:
    from src.agents.executor.budget import ExecutionBudget
    from src.agents.executor.execution_scheduler import ExecutionScheduler
    from src.agents.planner.plan_validator import ToolPlanV2
    from tests.evals.runner import load_jsonl

    rows = load_jsonl(Path("tests/evals/executor/data/smoke.jsonl"))
    snapshots = _tool_snapshots()

    async def run_case(row: dict[str, Any]) -> list[str]:
        async def fake_invoker(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return snapshots[row["fixture_key"]][tool_name]

        plan = ToolPlanV2.model_validate(row["plan"]) if hasattr(ToolPlanV2, "model_validate") else ToolPlanV2.parse_obj(row["plan"])
        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(per_tool_retry_limit=0, min_interval_ms=0, max_concurrency=2, per_api_family_limit=2),
            tool_invoker=fake_invoker,
        )
        batches = await scheduler.run(plan)
        return [result.status for batch in batches for result in batch.step_results]

    for row in rows:
        assert asyncio.run(run_case(row)) == row["gold"]["expected_statuses"]
