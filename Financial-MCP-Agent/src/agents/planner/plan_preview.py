from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanPreviewItem(BaseModel):
    step_id: str
    title: str
    description: str | None = None
    required: bool
    estimated_evidence: str
    status: Literal["planned", "running", "succeeded", "failed", "replanned", "skipped"] = "planned"
    args_summary: dict[str, str] = Field(default_factory=dict)


def _args_summary(arguments: dict[str, Any]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for key in ("symbol", "query", "sector_name", "limit", "max_results", "freshness_days"):
        value = arguments.get(key)
        if value is None or value == "":
            continue
        summary[key] = str(value)
    return summary


def build_plan_preview(plan: Any) -> list[PlanPreviewItem]:
    steps = getattr(plan, "steps", None) or []
    items: list[PlanPreviewItem] = []
    for step in steps:
        goal = str(getattr(step, "goal", "") or "").strip()
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        evidence_type = str(getattr(step, "evidence_type", "") or "").strip()
        arguments = getattr(step, "arguments", None) or {}
        items.append(
            PlanPreviewItem(
                step_id=str(getattr(step, "step_id", "")),
                title=goal or f"执行 {tool_name}",
                description=tool_name,
                required=bool(getattr(step, "required", False)),
                estimated_evidence=evidence_type or "unknown",
                args_summary=_args_summary(arguments),
            )
        )
    return items


__all__ = ["PlanPreviewItem", "build_plan_preview"]
