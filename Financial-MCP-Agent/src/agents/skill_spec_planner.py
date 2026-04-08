from __future__ import annotations

import re
from typing import Any

from src.agents.tushare_reference_planner import PlannedToolCall, TushareToolPlan
from src.skills.skill_registry import get_skill_registry

_FUND_ENTITY_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\-]{2,30}(?:ETF|etf|基金|联接|LOF|lof|QDII|qdii)")


def _dedupe(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in items:
            items.append(normalized)
    return items


def _normalize_fund_subject(text: str) -> str:
    candidate = str(text or "").strip("，。！？,.!?：:；;()（）[]【】 ")
    if not candidate:
        return ""
    match = _FUND_ENTITY_RE.search(candidate)
    if match:
        candidate = match.group(0)
    candidate = re.sub(r"^(请|帮我|重新回答|请重新回答|比较|对比)+", "", candidate).strip()
    return candidate.strip("，。！？,.!?：:；;()（）[]【】 ")


def extract_skill_subjects(skill_name: str, user_message: str) -> list[str]:
    query = (user_message or "").strip()
    if not query:
        return []

    if skill_name != "fund-compare":
        return []

    candidates = _dedupe(
        [
            _normalize_fund_subject(item)
            for item in _FUND_ENTITY_RE.findall(query)
            if not any(token in item for token in ("和", "与", "对比", "比较", "vs", "VS", "pk", "PK"))
        ]
    )
    if len(candidates) >= 2:
        return candidates[:4]

    cleaned = query
    for token in ("帮我", "请", "比较", "对比", "一下", "分析", "看看", "哪个", "更适合我", "更适合"):
        cleaned = cleaned.replace(token, " ")
    parts = re.split(r"\s+|和|与|跟|及|,|，|/|对比|比较|vs|VS|pk|PK", cleaned)
    for part in parts:
        candidate = _normalize_fund_subject(part)
        if any(keyword.lower() in candidate.lower() for keyword in ("etf", "基金", "联接", "lof", "qdii")):
            candidates.append(candidate)
    return _dedupe(candidates)[:4]


def build_skill_tool_plan(
    *,
    skill_name: str,
    skill_spec: dict[str, Any],
    user_message: str,
    resolved_entities: list[str] | None = None,
) -> TushareToolPlan:
    registry = get_skill_registry()
    refs = registry.find_references(skill_name, user_message, limit=5)
    subjects = _dedupe(list(resolved_entities or []) or extract_skill_subjects(skill_name, user_message))

    tool_calls: list[PlannedToolCall] = []
    for step in skill_spec.get("tool_plan_steps") or []:
        tool_name = str(step.get("tool") or "").strip()
        if not tool_name:
            continue
        base_arguments = dict(step.get("arguments") or {})
        reason = str(step.get("step") or tool_name)
        required = bool(step.get("required", True))
        repeat_for_each_subject = bool(step.get("repeat_for_each_subject"))

        if repeat_for_each_subject:
            for subject in subjects:
                arguments = dict(base_arguments)
                arguments["query"] = subject
                tool_calls.append(
                    PlannedToolCall(
                        tool_name=tool_name,
                        arguments=arguments,
                        reason=f"{reason} for subject={subject}",
                        required=required,
                    )
                )
            continue

        arguments = dict(base_arguments)
        if user_message:
            arguments.setdefault("query", user_message)
        tool_calls.append(
            PlannedToolCall(
                tool_name=tool_name,
                arguments=arguments,
                reason=reason,
                required=required,
            )
        )

    deduped: list[PlannedToolCall] = []
    seen: set[str] = set()
    for item in tool_calls:
        key = f"{item.tool_name}|{sorted(item.arguments.items())}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return TushareToolPlan(
        selected_skill="financial-sop",
        analysis_mode=skill_name.replace("-", "_"),
        planner_type="skill_planner",
        references=refs,
        tool_calls=deduped,
    )
