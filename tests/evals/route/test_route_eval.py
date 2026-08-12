import pytest


@pytest.mark.eval_smoke
def test_route_eval_smoke_dataset_loads():
    from tests.evals.runner import load_jsonl
    from pathlib import Path

    rows = load_jsonl(Path("tests/evals/route/data/smoke.jsonl"))
    assert {row["gold"]["final_route"] for row in rows} >= {"financial-sop", "fallback"}
