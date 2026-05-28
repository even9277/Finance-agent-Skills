from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RewriteContextPacket(BaseModel):
    route: Literal["financial-sop", "tushare-data", "fallback"]
    skill_id: str | None = None
    user_query: str
    active_entity: dict[str, Any] | None = None
    candidate_entities: list[dict[str, Any]] = Field(default_factory=list)
    resolution_status: str = "no_entity"
    recent_user_turns: list[str] = Field(default_factory=list)
    loaded_skill_context: dict[str, Any] = Field(default_factory=dict)
    capability_shortlist: list[str] = Field(default_factory=list)
    working_state_prev: dict[str, Any] = Field(default_factory=dict)


__all__ = ["RewriteContextPacket"]
