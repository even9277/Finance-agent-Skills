from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.eval_smoke
def test_synthesis_smoke_detects_no_overclaim_in_fixture_answers(tmp_path: Path) -> None:
    from tests.evals.metrics import overclaim_rate, planned_evidence_coverage
    from tests.evals.runner import load_jsonl, write_report

    rows = load_jsonl(Path("tests/evals/synthesis/data/smoke.jsonl"))
    assert rows
    assert planned_evidence_coverage(rows) == 1.0
    assert overclaim_rate(rows) == 0.0

    report = write_report("synthesis", rows, tmp_path)
    assert report.exists()
