from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agents.route_stage1 import Stage1Result, default_model_env as stage1_env, route_stage1
from src.agents.route_stage2 import Stage2Result, default_model_env as stage2_env, route_stage2
from src.skills.route_metadata import RouteMetadataIndex
from src.skills.skill_registry import get_skill_registry

FinalRoute = Literal["financial-sop", "tushare-data", "fallback"]


class RouteDecisionV2(BaseModel):
    final_route: FinalRoute
    skill_id: str | None = None
    execution_policy: Literal["deterministic", "agentic"] = "deterministic"
    need_confirm: bool = False
    confirm_candidates: list[str] = Field(default_factory=list)
    route_source: Literal["user_explicit", "stage1_high", "stage1_confirmed", "stage2"] = "stage2"
    stage1: Stage1Result | None = None
    stage2: Stage2Result | None = None

    @property
    def legacy_route(self) -> Literal["sop", "tushare", "fallback"]:
        if self.final_route == "financial-sop":
            return "sop"
        if self.final_route == "tushare-data":
            return "tushare"
        return "fallback"


async def route_v2(
    user_message: str,
    *,
    active_entity: dict[str, Any] | None = None,
    explicit_skill_id: str | None = None,
    metadata_index: RouteMetadataIndex | None = None,
    route_stage1_confidence_high: float = 0.85,
) -> RouteDecisionV2:
    registry = get_skill_registry()
    if explicit_skill_id:
        skill = registry.get_skill(explicit_skill_id)
        if skill is None:
            return RouteDecisionV2(final_route="fallback", route_source="user_explicit")
        return RouteDecisionV2(
            final_route="financial-sop",
            skill_id=skill.name,
            execution_policy=_execution_policy(skill.name),
            route_source="user_explicit",
        )

    index = metadata_index or RouteMetadataIndex.build_from_registry(registry)
    env = stage1_env()
    s1 = await route_stage1(
        user_message,
        active_entity=active_entity,
        index=index,
        confidence_high=route_stage1_confidence_high,
        **env,
    )
    if s1.outcome == "sop_hit_high" and s1.skill_id:
        return RouteDecisionV2(
            final_route="financial-sop",
            skill_id=s1.skill_id,
            execution_policy=_execution_policy(s1.skill_id),
            route_source="stage1_high",
            stage1=s1,
        )
    if s1.outcome == "sop_hit_low" and s1.skill_id:
        return RouteDecisionV2(
            final_route="financial-sop",
            skill_id=s1.skill_id,
            execution_policy=_execution_policy(s1.skill_id),
            need_confirm=True,
            confirm_candidates=[s1.skill_id, "fallback"],
            route_source="stage1_high",
            stage1=s1,
        )

    s2 = await route_stage2(user_message, active_entity=active_entity, **stage2_env())
    return RouteDecisionV2(
        final_route=s2.final_route,
        route_source="stage2",
        stage1=s1,
        stage2=s2,
    )


def _execution_policy(skill_id: str) -> Literal["deterministic", "agentic"]:
    spec = get_skill_registry().load_skill_spec(skill_id) or {}
    value = str(spec.get("execution_policy") or "deterministic").strip()
    return "agentic" if value == "agentic" else "deterministic"


__all__ = ["FinalRoute", "RouteDecisionV2", "route_v2"]
