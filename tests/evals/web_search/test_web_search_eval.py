import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.eval_smoke
def test_web_search_eval_smoke(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "tests.evals.runner", "--target", "web_search", "--output-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    data = json.loads((tmp_path / "web_search_metrics.json").read_text(encoding="utf-8"))
    assert data["count"] == 2
    assert data["metrics"]["schema_pass_rate"] == 1.0
