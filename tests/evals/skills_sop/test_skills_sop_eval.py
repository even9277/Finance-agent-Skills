"""验证 Skills SOP 专项集和可复现 runner 的冻结合同。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
DATA_PATH = Path(__file__).parent / "data" / "smoke.jsonl"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
REQUIRED_GOLD_FIELDS = {
    "gold_route",
    "gold_skill_id",
    "required_slots",
    "allowed_tools",
    "forbidden_tools",
    "expected_evidence_types",
    "should_clarify",
    "allowed_claim_level",
}


def _load_rows() -> list[dict[str, Any]]:
    """加载版本化 JSONL 样例。"""
    return [json.loads(line) for line in DATA_PATH.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.eval_smoke
def test_skills_sop_dataset_covers_all_skills_boundaries_and_gold_fields() -> None:
    """专项集必须覆盖五个 Skill、fallback、显式选择、确认和多任务。"""
    rows = _load_rows()
    skill_ids = {row["gold"]["gold_skill_id"] for row in rows}
    labels = {label for row in rows for label in row["labels"]}

    assert len(rows) >= 15
    assert {
        "stock-first-pass",
        "fund-compare",
        "etf-screen",
        "sector-hotspot-brief",
        "market-move-explain",
    } <= skill_ids
    assert {"positive", "negative", "missing_slot", "explicit", "multi_task", "confirm"} <= labels
    for row in rows:
        assert REQUIRED_GOLD_FIELDS <= set(row["gold"]), row["case_id"]
        assert set(row["gold"]["allowed_tools"]).isdisjoint(row["gold"]["forbidden_tools"])


@pytest.mark.eval_smoke
def test_skills_sop_runner_writes_reproducible_metadata(tmp_path: Path) -> None:
    """Runner 必须执行真实离线预测并记录数据、Registry 和运行次数元数据。"""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.evals.runner",
            "--target",
            "skills_sop",
            "--mode",
            "smoke",
            "--repeat",
            "3",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    report = json.loads((tmp_path / "skills_sop_metrics.json").read_text(encoding="utf-8"))
    assert report["count"] == len(_load_rows())
    assert report["repeat"] == 3
    assert report["dataset_version"]
    assert report["dataset_hash"]
    assert report["runner_version"]
    assert report["registry_snapshot_hash"]
    assert report["tool_schema_version"]
    assert report["provider"] == "deterministic"
    assert {
        "skill_activation_accuracy",
        "plan_compliance_rate",
        "evidence_coverage_rate",
        "overclaim_rate",
    } <= set(report["metrics"])
    assert report["metrics"]["deterministic_stability_rate"] == 1.0
    assert {
        "stock-first-pass",
        "fund-compare",
        "etf-screen",
        "sector-hotspot-brief",
        "market-move-explain",
        "no-skill",
    } <= set(report["metrics"]["per_skill"])
    assert report["historical_metrics"]["status"] == "not_reproduced"
    assert report["artifacts"]["records"]["path"] == "skills_sop_records.jsonl"
    assert report["artifacts"]["records"]["sha256"]
    assert report["reproducibility_hash"]

    records = [
        json.loads(line)
        for line in (tmp_path / "skills_sop_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    assert len(records) == len(_load_rows()) * 3
    assert all("user_message" not in item for item in records)
    by_case: dict[str, set[str]] = {}
    for item in records:
        by_case.setdefault(item["case_id"], set()).add(item["prediction_hash"])
    assert all(len(hashes) == 1 for hashes in by_case.values())

    replay_dir = tmp_path / "replay"
    replay = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.evals.runner",
            "--target",
            "skills_sop",
            "--mode",
            "smoke",
            "--repeat",
            "3",
            "--output-dir",
            str(replay_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert replay.returncode == 0, replay.stderr
    replay_report = json.loads(
        (replay_dir / "skills_sop_metrics.json").read_text(encoding="utf-8")
    )
    assert replay_report["reproducibility_hash"] == report["reproducibility_hash"]
    assert replay_report["artifacts"]["records"]["sha256"] == (
        report["artifacts"]["records"]["sha256"]
    )


@pytest.mark.eval_smoke
def test_skills_sop_runner_rejects_invalid_repeat_without_writing_artifacts(
    tmp_path: Path,
) -> None:
    """repeat 越界必须在运行前失败，不能留下看似成功的空报告。"""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.evals.runner",
            "--target",
            "skills_sop",
            "--mode",
            "smoke",
            "--repeat",
            "0",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert not list(tmp_path.glob("*"))


@pytest.mark.eval_smoke
def test_ci_quality_gate_includes_maintained_skills_modules() -> None:
    """新增 Skills runtime 必须同时进入 Ruff 和 Pyright 的既有 CI job。"""
    ci_text = CI_PATH.read_text(encoding="utf-8")

    assert ci_text.count("Financial-MCP-Agent/src/skills") == 2
    assert "Offline eval smoke" in ci_text
