from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class RouteMetadata(BaseModel):
    skill_id: str
    name: str = ""
    description: str = ""
    when_to_use: list[str] = Field(default_factory=list)
    when_not_to_use: list[str] = Field(default_factory=list)
    trigger_examples: list[str] = Field(default_factory=list)
    anti_trigger_examples: list[str] = Field(default_factory=list)
    supported_entity_types: list[str] = Field(default_factory=list)
    execution_mode: str = "deterministic"
    allowed_tools: list[str] = Field(default_factory=list)

    def prompt_summary(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name or self.skill_id,
            "description": self.description,
            "when_to_use": self.when_to_use[:4],
            "when_not_to_use": self.when_not_to_use[:4],
            "trigger_examples": self.trigger_examples[:4],
            "anti_trigger_examples": self.anti_trigger_examples[:4],
            "supported_entity_types": self.supported_entity_types[:8],
            "execution_mode": self.execution_mode,
        }


@dataclass(frozen=True, slots=True)
class RouteMetadataIndex:
    items: tuple[RouteMetadata, ...]

    @classmethod
    def build_from_registry(cls, registry: Any) -> "RouteMetadataIndex":
        items: list[RouteMetadata] = []
        for skill in registry.discoverable_sop_skills():
            spec = registry.load_skill_spec(skill.name) or {}
            route_meta = spec.get("route_metadata") or {}
            input_contract = spec.get("input_contract") or {}
            items.append(
                RouteMetadata(
                    skill_id=skill.name,
                    name=str(spec.get("skill_name") or skill.official_name or skill.name),
                    description=str(skill.description or ""),
                    when_to_use=_coerce_list(route_meta.get("when_to_use")),
                    when_not_to_use=_coerce_list(route_meta.get("when_not_to_use")),
                    trigger_examples=_coerce_list(route_meta.get("trigger_examples")),
                    anti_trigger_examples=_coerce_list(route_meta.get("anti_trigger_examples")),
                    supported_entity_types=_coerce_list(
                        route_meta.get("supported_entity_types")
                        or input_contract.get("supported_entity_types")
                    ),
                    execution_mode=str(spec.get("execution_policy") or skill.execution_mode or "deterministic"),
                    allowed_tools=[str(item) for item in (spec.get("allowed_tools") or skill.allowed_tools or [])],
                )
            )
        return cls(items=tuple(items))

    def shortlist(self, query: str, *, limit: int = 5) -> list[RouteMetadata]:
        text = (query or "").lower()
        scored: list[tuple[int, RouteMetadata]] = []
        for item in self.items:
            score = 0
            haystacks = [
                item.skill_id,
                item.name,
                item.description,
                *item.when_to_use,
                *item.trigger_examples,
            ]
            anti = [*item.when_not_to_use, *item.anti_trigger_examples]
            for hay in haystacks:
                hay_text = str(hay).lower()
                if hay_text and hay_text in text:
                    score += 6
                for token in _tokens(hay_text):
                    if token in text:
                        score += 2
            for hay in anti:
                for token in _tokens(str(hay).lower()):
                    if token in text:
                        score -= 1
            if score <= 0 and any(token in text for token in ("比较", "筛", "为什么", "异动", "怎么看", "适合")):
                score = 1
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].skill_id))
        return [item for score, item in scored if score > 0][:limit] or list(self.items[:limit])

    def as_prompt_payload(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return [item.prompt_summary() for item in self.shortlist(query, limit=limit)]


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _tokens(text: str) -> list[str]:
    import re

    return [token for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", text) if len(token) >= 2]


__all__ = ["RouteMetadata", "RouteMetadataIndex"]
