import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.eval_smoke
def test_skill_activation_eval_smoke(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "tests.evals.runner", "--target", "skill_activation", "--output-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    data = json.loads((tmp_path / "skill_activation_metrics.json").read_text(encoding="utf-8"))
    assert data["count"] == 2
    assert data["metrics"]["planned_evidence_coverage"] == 1.0
