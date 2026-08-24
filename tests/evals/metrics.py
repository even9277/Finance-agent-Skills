from __future__ import annotations

import math
from typing import Any


def schema_pass_rate(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    return sum(1 for item in records if item.get("schema_pass", True)) / len(records)


def field_accuracy(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    ok = 0
    for item in records:
        pred = ((item.get("prediction") or {}).get(field))
        gold = ((item.get("gold") or {}).get(field))
        ok += int(pred == gold)
    return ok / len(records)


def route_accuracy_stage2(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    return sum(1 for item in records if item.get("prediction", {}).get("final_route") == item.get("gold", {}).get("final_route")) / len(records)


def false_reject_rate(records: list[dict[str, Any]]) -> float:
    """Share of gold-acceptable cases rejected by verifier/planner output."""
    eligible = [
        item
        for item in records
        if (item.get("gold") or {}).get("should_accept", True)
        or (item.get("gold") or {}).get("expected_status") in {"sufficient", "partial"}
    ]
    if not eligible:
        return 0.0
    rejected = 0
    for item in eligible:
        prediction = item.get("prediction") or {}
        status = str(prediction.get("status") or prediction.get("verification_status") or "").lower()
        claim_level = str(prediction.get("allowed_claim_level") or "").lower()
        rejected += int(status in {"insufficient", "rejected", "refuse"} or claim_level == "refuse")
    return rejected / len(eligible)


def planned_evidence_coverage(records: list[dict[str, Any]]) -> float:
    """Average coverage of required evidence types by planned or accepted evidence."""
    if not records:
        return 0.0
    scores: list[float] = []
    for item in records:
        gold = item.get("gold") or {}
        prediction = item.get("prediction") or {}
        required = set(str(value) for value in gold.get("required_evidence") or gold.get("required_evidence_types") or [])
        if not required:
            scores.append(1.0)
            continue
        planned = set(str(value) for value in prediction.get("planned_evidence") or prediction.get("accepted_evidence_types") or [])
        steps = prediction.get("steps") or []
        planned.update(str(step.get("evidence_type")) for step in steps if isinstance(step, dict) and step.get("evidence_type"))
        scores.append(len(required & planned) / len(required))
    return sum(scores) / len(scores)


_OVERCLAIM_TERMS = (
    "必然",
    "一定",
    "确定导致",
    "唯一原因",
    "保证",
    "直接买入",
    "强烈买入",
    "will definitely",
    "guaranteed",
)


def overclaim_rate(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    overclaims = 0
    for item in records:
        prediction = item.get("prediction") or {}
        text = str(prediction.get("final_answer") or prediction.get("answer") or "")
        flagged = bool(prediction.get("overclaim"))
        if not flagged:
            flagged = any(term in text for term in _OVERCLAIM_TERMS)
        overclaims += int(flagged)
    return overclaims / len(records)


def allowed_claim_level_match(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    matched = 0
    for item in records:
        prediction = item.get("prediction") or {}
        gold = item.get("gold") or {}
        matched += int(prediction.get("allowed_claim_level") == gold.get("allowed_claim_level"))
    return matched / len(records)


def terminal_status_accuracy(records: list[dict[str, Any]]) -> float:
    """计算完整主链终态与固定 gold 的精确匹配率。"""
    if not records:
        return 0.0
    matched = sum(
        1
        for item in records
        if (item.get("prediction") or {}).get("terminal_status")
        == (item.get("gold") or {}).get("terminal_status")
    )
    return matched / len(records)


def required_stage_coverage(records: list[dict[str, Any]]) -> float:
    """计算每个案例的必经阶段是否都出现在实际主链事件中。"""
    if not records:
        return 0.0
    scores: list[float] = []
    for item in records:
        required = set((item.get("gold") or {}).get("required_stages") or [])
        actual = set((item.get("prediction") or {}).get("stages") or [])
        scores.append(1.0 if not required else len(required & actual) / len(required))
    return sum(scores) / len(scores)


def latency_percentiles(records: list[dict[str, Any]]) -> dict[str, int]:
    latencies = sorted(
        int((item.get("prediction") or item).get("latency_ms") or 0)
        for item in records
        if ((item.get("prediction") or item).get("latency_ms") is not None)
    )
    if not latencies:
        return {"p50": 0, "p95": 0}
    return {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)}


def _percentile(values: list[int], percentile: int) -> int:
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * (percentile / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return values[int(rank)]
    weight = rank - lower
    return int(round(values[lower] * (1 - weight) + values[upper] * weight))
