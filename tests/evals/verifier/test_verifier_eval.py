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
    find_spec("src.agents.verifier") is None,
    reason="依赖受控主链 verifier 模块，待 M2 迁移后自动启用",
)


def _tool_snapshots() -> dict[str, Any]:
    return json.loads(Path("tests/evals/_fixtures/tool_snapshots.json").read_text(encoding="utf-8"))


@pytest.mark.eval_smoke
def test_verifier_smoke_scores_sufficient_and_partial_cases() -> None:
    from src.agents.executor.budget import ExecutionBudget
    from src.agents.executor.execution_scheduler import ExecutionScheduler, StepResult
    from src.agents.planner.plan_validator import ToolPlanV2
    from src.agents.verifier.evidence_verifier import EvidenceVerifier
    from tests.evals.runner import load_jsonl

    executor_rows = {row["case_id"]: row for row in load_jsonl(Path("tests/evals/executor/data/smoke.jsonl"))}
    verifier_rows = load_jsonl(Path("tests/evals/verifier/data/smoke.jsonl"))
    snapshots = _tool_snapshots()

    async def run_steps(row: dict[str, Any]) -> tuple[ToolPlanV2, list[StepResult]]:
        plan_payload = executor_rows[row["plan_ref"]]["plan"]
        plan = ToolPlanV2.model_validate(plan_payload) if hasattr(ToolPlanV2, "model_validate") else ToolPlanV2.parse_obj(plan_payload)

        async def fake_invoker(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return snapshots[row["fixture_key"]][tool_name]

        scheduler = ExecutionScheduler(
            budget=ExecutionBudget(per_tool_retry_limit=0, min_interval_ms=0, max_concurrency=2, per_api_family_limit=2),
            tool_invoker=fake_invoker,
        )
        batches = await scheduler.run(plan)
        return plan, [result for batch in batches for result in batch.step_results]

    verifier = EvidenceVerifier()
    for row in verifier_rows:
        plan, step_results = asyncio.run(run_steps(row))
        result = verifier.verify(plan=plan, step_results=step_results)

        assert result.status == row["gold"]["expected_status"]
        assert result.allowed_claim_level == row["gold"]["allowed_claim_level"]
