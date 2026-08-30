from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.evals.metrics import (
    allowed_claim_level_match,
    false_reject_rate,
    latency_percentiles,
    overclaim_rate,
    planned_evidence_coverage,
    required_stage_coverage,
    schema_pass_rate,
    terminal_status_accuracy,
)
from tests.evals.skills_sop.runner import run_from_cli as run_skills_sop_from_cli


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def compute_metrics(target: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "schema_pass_rate": schema_pass_rate(records),
        "latency_ms": latency_percentiles(records),
    }
    if target in {"planner", "executor", "verifier", "synthesis", "skill_activation", "web_search"}:
        metrics["planned_evidence_coverage"] = planned_evidence_coverage(records)
    if target in {"planner", "verifier"}:
        metrics["false_reject_rate"] = false_reject_rate(records)
    if target == "verifier":
        metrics["allowed_claim_level_match"] = allowed_claim_level_match(records)
    if target == "synthesis":
        metrics["overclaim_rate"] = overclaim_rate(records)
    if target == "mainline":
        metrics["terminal_status_accuracy"] = terminal_status_accuracy(records)
        metrics["required_stage_coverage"] = required_stage_coverage(records)
    return metrics


def _git_commit_short() -> str:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return commit or "unknown"
    except Exception:
        return "unknown"


def write_report(target: str, records: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{target}_metrics.json"
    now = datetime.now()
    timestamp_iso = now.isoformat()
    timestamp_for_file = now.strftime("%Y%m%dT%H%M%S")
    path.write_text(
        json.dumps(
            {
                "target": target,
                "count": len(records),
                "timestamp": timestamp_iso,
                "git_commit": _git_commit_short(),
                "metrics": compute_metrics(target, records),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    history_dir = Path("tests/evals/history") / target
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{timestamp_for_file}_{target}_metrics.json"
    shutil.copy2(path, history_path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        choices=["entity", "route", "rewrite", "planner", "executor", "verifier", "synthesis", "skill_activation", "web_search", "mainline", "skills_sop"],
        required=True,
    )
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output-dir", default="tests/evals/_runs/latest")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error("--repeat must be between 1 and 10")
    if args.target == "skills_sop":
        dataset_path = Path("tests/evals/skills_sop/data") / f"{args.mode}.jsonl"
        out = run_skills_sop_from_cli(
            dataset_path=dataset_path,
            output_dir=Path(args.output_dir),
            repeat=args.repeat,
            mode=args.mode,
        )
        print(out)
        return
    path = Path("tests/evals") / args.target / "data" / "smoke.jsonl"
    records = load_jsonl(path)
    out = write_report(args.target, records, Path(args.output_dir))
    print(out)


if __name__ == "__main__":
    main()
