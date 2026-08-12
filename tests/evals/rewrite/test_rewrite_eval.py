import pytest


@pytest.mark.eval_smoke
def test_rewrite_eval_smoke_dataset_loads():
    from tests.evals.runner import load_jsonl
    from pathlib import Path

    rows = load_jsonl(Path("tests/evals/rewrite/data/smoke.jsonl"))
    assert rows[0]["gold"]["final_route"] == "tushare-data"
