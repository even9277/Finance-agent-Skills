"""
Agent runtime integration contracts.

本模块仅承载说明/类型占位，不放业务逻辑。
"""

from __future__ import annotations

from typing import Any, TypedDict


class SkillTracePayload(TypedDict, total=False):
    selected_skill_family: str
    selected_skill: str
    skill_name: str
    analysis_mode: str
    execution_policy: str
    route_trace: dict[str, Any]
