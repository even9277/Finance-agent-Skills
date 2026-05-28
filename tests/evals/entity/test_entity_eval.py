import pytest


@pytest.mark.eval_smoke
def test_entity_eval_smoke_dataset_loads():
    from tests.evals.runner import load_jsonl
    from pathlib import Path

    rows = load_jsonl(Path("tests/evals/entity/data/smoke.jsonl"))
    assert rows
    assert rows[0]["gold"]["active_entity"]["resolution_status"] == "resolved"
