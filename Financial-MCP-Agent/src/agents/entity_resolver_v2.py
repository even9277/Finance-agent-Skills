from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

EntityType = Literal["stock", "fund", "sector", "index", "none"]
ResolutionStatus = Literal["resolved", "ambiguous", "need_clarification", "no_entity", "competing_candidates"]


class PrimaryEntity(BaseModel):
    entity_type: EntityType
    canonical_id: str = ""
    display_name: str = ""
    market: str = ""
    alias_hit: list[str] = Field(default_factory=list)
    resolver_path: str = ""
    validation_status: Literal["passed", "schema_repaired", "semantic_repaired", "failed"] = "passed"


class CandidateEntity(BaseModel):
    entity_type: EntityType
    canonical_id: str
    display_name: str
    score: float = 0.0
    source: str = ""


class EntityResolutionResultV2(BaseModel):
    entity_found: bool = False
    entity_type: EntityType = "none"
    primary_entity: PrimaryEntity | None = None
    candidate_entities: list[CandidateEntity] = Field(default_factory=list)
    should_inherit: bool = False
    inherit_from_previous: bool = False
    need_clarification: bool = False
    clarification_question: str = ""
    failure_code: str = ""
    confidence: float = 0.0
    source_message_id: int | None = None
    resolution_status: ResolutionStatus = "no_entity"
    audit: dict[str, Any] = Field(default_factory=dict)


_FOLLOWUP_RE = re.compile(r"(它|这只|这个|该股|刚才|继续|前面|那只|那个)")
_SWITCH_RE = re.compile(r"(换成|别看|不要看|改看|换一个)")


async def resolve_authoritative_entity(
    user_message: str,
    *,
    allowed_asset_types: set[str] | None = None,
    previous_active_entity: dict[str, Any] | None = None,
    session_symbols: list[str] | None = None,
    summary_active_symbols: list[str] | None = None,
    source_message_id: int | None = None,
) -> EntityResolutionResultV2:
    from backend.services.entity_resolver import gather_candidates

    allowed = set(allowed_asset_types or {"stock", "fund", "sector", "index"})
    candidates_raw = await gather_candidates(
        user_message,
        allowed_asset_types=allowed,  # type: ignore[arg-type]
        session_symbols=session_symbols,
        summary_active_symbols=summary_active_symbols,
    )
    candidates = [_candidate_from_raw(item) for item in candidates_raw if _candidate_from_raw(item) is not None]
    candidates.sort(key=lambda item: item.score, reverse=True)

    if candidates:
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        if second and (top.score - second.score) < 0.15:
            return _clarify(
                candidates,
                status="competing_candidates",
                failure_code="competing_candidates",
                source_message_id=source_message_id,
            )
        if top.score < 0.75:
            return _clarify(
                candidates,
                status="ambiguous",
                failure_code=candidates_raw[0].get("failure_code") or "entity_unresolved",
                source_message_id=source_message_id,
            )
        return EntityResolutionResultV2(
            entity_found=True,
            entity_type=top.entity_type,
            primary_entity=PrimaryEntity(
                entity_type=top.entity_type,
                canonical_id=top.canonical_id,
                display_name=top.display_name,
                market=str(candidates_raw[0].get("market") or ""),
                resolver_path=top.source or "catalog",
            ),
            candidate_entities=candidates,
            confidence=top.score,
            source_message_id=source_message_id,
            resolution_status="resolved",
            audit={"candidate_count": len(candidates)},
        )

    if previous_active_entity and _FOLLOWUP_RE.search(user_message or "") and not _SWITCH_RE.search(user_message or ""):
        entity_type = str(previous_active_entity.get("entity_type") or previous_active_entity.get("asset_type") or "none")
        if entity_type in allowed:
            canonical_id = str(previous_active_entity.get("canonical_id") or previous_active_entity.get("symbol") or "")
            display_name = str(previous_active_entity.get("display_name") or canonical_id)
            return EntityResolutionResultV2(
                entity_found=bool(canonical_id or display_name),
                entity_type=entity_type if entity_type in {"stock", "fund", "sector", "index"} else "none",
                primary_entity=PrimaryEntity(
                    entity_type=entity_type if entity_type in {"stock", "fund", "sector", "index"} else "none",
                    canonical_id=canonical_id,
                    display_name=display_name,
                    resolver_path="session_inherit",
                ),
                should_inherit=True,
                inherit_from_previous=True,
                confidence=0.82,
                source_message_id=source_message_id,
                resolution_status="resolved",
                audit={"resolver_path": "session_inherit"},
            )

    return EntityResolutionResultV2(
        entity_found=False,
        entity_type="none",
        should_inherit=False,
        failure_code="no_entity_detected",
        source_message_id=source_message_id,
        resolution_status="no_entity",
    )


def _candidate_from_raw(item: dict[str, Any]) -> CandidateEntity | None:
    entity_type = str(item.get("entity_type") or item.get("asset_type") or "none")
    if entity_type not in {"stock", "fund", "sector", "index"}:
        return None
    canonical_id = str(item.get("canonical_id") or item.get("symbol") or item.get("display_name") or "").strip()
    display_name = str(item.get("display_name") or canonical_id).strip()
    if not canonical_id and not display_name:
        return None
    return CandidateEntity(
        entity_type=entity_type,  # type: ignore[arg-type]
        canonical_id=canonical_id or display_name,
        display_name=display_name or canonical_id,
        score=float(item.get("score") or item.get("confidence") or 0.0),
        source=str(item.get("source") or "catalog"),
    )


def _clarify(
    candidates: list[CandidateEntity],
    *,
    status: Literal["ambiguous", "competing_candidates"],
    failure_code: str,
    source_message_id: int | None,
) -> EntityResolutionResultV2:
    names = [item.display_name for item in candidates[:3] if item.display_name]
    question = "你说的是哪一个标的？"
    if names:
        question = f"你说的是 {(' / '.join(names))} 中的哪一个？"
    return EntityResolutionResultV2(
        entity_found=False,
        entity_type=candidates[0].entity_type if candidates else "none",
        candidate_entities=candidates[:5],
        need_clarification=True,
        clarification_question=question,
        failure_code=failure_code,
        confidence=candidates[0].score if candidates else 0.0,
        source_message_id=source_message_id,
        resolution_status=status,
    )


__all__ = [
    "CandidateEntity",
    "EntityResolutionResultV2",
    "PrimaryEntity",
    "resolve_authoritative_entity",
]
