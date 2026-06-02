from __future__ import annotations

from typing import Any
import uuid

from src.agents.planner.plan_validator import ToolPlanStepV2, ToolPlanV2
from src.agents.skill_spec_planner import build_skill_tool_plan
from src.agents.tool_discovery.executable_registry import (
    ExecutableToolRegistry,
    build_default_registry,
)
from src.tools.skill_trace import trace_span


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _new_plan_id() -> str:
    return f"plan_{uuid.uuid4().hex}"


class SopPlanner:
    def __init__(self, *, registry: ExecutableToolRegistry | None = None, prompt_version: str = "p5_sop_planner_v1") -> None:
        self.registry = registry or build_default_registry()
        self.prompt_version = prompt_version

    def plan(
        self,
        *,
        skill_name: str,
        skill_spec: dict[str, Any],
        user_message: str,
        rewrite_result: Any = None,
        discovery_result: Any = None,
        resolved_entities: list[str] | None = None,
        skill_params: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> ToolPlanV2:
        with trace_span(
            "plan_generate",
            stage="planner",
            data={"planner_type": "sop", "skill_name": skill_name, "prompt_version": self.prompt_version},
        ):
            rewrite = _model_dump(rewrite_result)
            discovery = _model_dump(discovery_result)
            params = dict(skill_params or rewrite.get("skill_params") or {})
            effective_query = str(rewrite.get("effective_query") or user_message or "").strip()
            if effective_query:
                params.setdefault("effective_query", effective_query)

            base_plan = build_skill_tool_plan(
                skill_name=skill_name,
                skill_spec=skill_spec,
                user_message=user_message,
                resolved_entities=resolved_entities,
                skill_params=params,
            )
            available_tools = set(discovery.get("available_tools") or self.registry.names(planner_visible_only=True))
            steps: list[ToolPlanStepV2] = []
            for item in base_plan.tool_calls:
                tool_name = str(item.tool_name or "").strip()
                if tool_name not in available_tools or tool_name not in self.registry.names():
                    continue
                spec = self.registry.spec(tool_name)
                steps.append(
                    ToolPlanStepV2(
                        step_id=f"s{len(steps) + 1}",
                        goal=str(item.reason or tool_name),
                        tool_name=tool_name,
                        arguments=dict(item.arguments or {}),
                        depends_on=[],
                        expected_observation=spec.evidence_type,
                        required=bool(item.required),
                        evidence_type=spec.evidence_type,
                    )
                )

            result = ToolPlanV2(
                plan_id=_new_plan_id(),
                trace_id=trace_id,
                discovery_trace_id=str(discovery.get("discovery_trace_id") or ""),
                route="financial-sop",
                skill_id=skill_name,
                objective=effective_query or skill_name,
                entity=self._entity_from_rewrite(rewrite),
                time_scope=dict(rewrite.get("time_scope") or {}),
                steps=steps,
                planner_model=base_plan.planner_type,
                prompt_version=self.prompt_version,
                metadata={
                    "skill_concurrency": dict(skill_spec.get("concurrency") or {}),
                    "required_evidence": dict(skill_spec.get("required_evidence") or {}),
                    "degrade_policy": dict(skill_spec.get("degrade_policy") or {}),
                    "output_template": dict(skill_spec.get("output_template") or {}),
                },
            )
            return result

    @staticmethod
    def _entity_from_rewrite(rewrite: dict[str, Any]) -> dict[str, Any] | None:
        entities = rewrite.get("entities") or []
        if not entities:
            return None
        return _model_dump(entities[0])


__all__ = ["SopPlanner"]
