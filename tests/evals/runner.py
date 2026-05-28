from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tests.evals.metrics import (
    allowed_claim_level_match,
    false_reject_rate,
    latency_percentiles,
    overclaim_rate,
    planned_evidence_coverage,
    schema_pass_rate,
)


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
    return metrics


def write_report(target: str, records: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{target}_metrics.json"
    path.write_text(
        json.dumps({"target": target, "count": len(records), "metrics": compute_metrics(target, records)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        choices=["entity", "route", "rewrite", "planner", "executor", "verifier", "synthesis", "skill_activation", "web_search"],
        required=True,
    )
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--output-dir", default="tests/evals/_runs/latest")
    args = parser.parse_args()
    path = Path("tests/evals") / args.target / "data" / "smoke.jsonl"
    records = load_jsonl(path)
    out = write_report(args.target, records, Path(args.output_dir))
    print(out)


if __name__ == "__main__":
    main()
