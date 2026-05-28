from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConstraintsExtractionResult(BaseModel):
    constraints: list[str] = Field(default_factory=list)
    operation: Literal["replace", "merge", "clear", "no_update"] = "no_update"
    confidence: float = 0.0
    source: str = "rule"


def extract_constraints_rule(text: str) -> ConstraintsExtractionResult:
    query = text or ""
    items: list[str] = []
    patterns = [
        (r"(只看|仅看)\s*(A股|港股|美股)", "只看{group}口径"),
        (r"(不要|别|不)\s*(展开)?\s*(技术面|技术分析)", "不展开技术面分析"),
        (r"(简单|简短|简洁)(说|讲|一点)?", "回答保持简洁"),
        (r"(重点看|主要看)\s*(最近|近)\s*(\d+)?\s*(天|日|周|月)", "重点看近期时间窗口"),
    ]
    for pattern, label in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if not match:
            continue
        if "{group}" in label:
            label = label.format(group=match.group(2))
        if label not in items:
            items.append(label)
    return ConstraintsExtractionResult(
        constraints=items,
        operation="merge" if items else "no_update",
        confidence=0.85 if items else 0.0,
    )


async def extract_constraints(ctx_packet: Any, rewrite_result: Any | None = None) -> ConstraintsExtractionResult:
    text = getattr(ctx_packet, "user_query", "") if ctx_packet is not None else ""
    return extract_constraints_rule(str(text))


__all__ = ["ConstraintsExtractionResult", "extract_constraints", "extract_constraints_rule"]
