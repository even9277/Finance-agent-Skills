from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Session, WorkingStateEvent


def _default_state() -> dict[str, Any]:
    return {
        "active_entity": None,
        "candidate_entities": [],
        "constraints": [],
        "reply_preference_hint": "",
    }


def normalize_working_state(value: dict[str, Any] | None) -> dict[str, Any]:
    state = _default_state()
    if isinstance(value, dict):
        state.update(value)
    if not isinstance(state.get("candidate_entities"), list):
        state["candidate_entities"] = []
    if not isinstance(state.get("constraints"), list):
        state["constraints"] = []
    state["reply_preference_hint"] = str(state.get("reply_preference_hint") or "")[:220]
    return state


def get_working_state(session: Session) -> dict[str, Any]:
    return normalize_working_state(session.working_state)


async def upsert_active_entity(
    db: AsyncSession,
    session: Session,
    entity: dict[str, Any] | None,
    *,
    message_id: int | None = None,
    source: str = "entity_resolver_v2",
    confidence: float = 0.0,
    trace_id: str | None = None,
) -> dict[str, Any]:
    state = get_working_state(session)
    old = deepcopy(state.get("active_entity"))
    state["active_entity"] = deepcopy(entity) if entity else None
    if entity and isinstance(entity, dict):
        state["candidate_entities"] = list(entity.get("candidate_entities") or state.get("candidate_entities") or [])
    return await _commit_field(
        db,
        session,
        field_name="active_entity",
        old_value=old,
        new_value=state["active_entity"],
        new_state=state,
        message_id=message_id,
        source=source,
        confidence=confidence,
        trace_id=trace_id,
    )


async def upsert_constraints(
    db: AsyncSession,
    session: Session,
    constraints: list[str],
    *,
    message_id: int | None = None,
    source: str = "constraints_extractor",
    confidence: float = 0.0,
    trace_id: str | None = None,
) -> dict[str, Any]:
    state = get_working_state(session)
    old = deepcopy(state.get("constraints") or [])
    cleaned: list[str] = []
    for item in constraints or []:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text[:120])
    state["constraints"] = cleaned[:8]
    return await _commit_field(
        db,
        session,
        field_name="constraints",
        old_value=old,
        new_value=state["constraints"],
        new_state=state,
        message_id=message_id,
        source=source,
        confidence=confidence,
        trace_id=trace_id,
    )


async def upsert_reply_preference(
    db: AsyncSession,
    session: Session,
    hint: str,
    *,
    message_id: int | None = None,
    source: str = "reply_preference_extractor",
    confidence: float = 0.0,
    trace_id: str | None = None,
) -> dict[str, Any]:
    state = get_working_state(session)
    old = str(state.get("reply_preference_hint") or "")
    state["reply_preference_hint"] = str(hint or "").strip()[:220]
    return await _commit_field(
        db,
        session,
        field_name="reply_preference_hint",
        old_value=old,
        new_value=state["reply_preference_hint"],
        new_state=state,
        message_id=message_id,
        source=source,
        confidence=confidence,
        trace_id=trace_id,
    )


async def _commit_field(
    db: AsyncSession,
    session: Session,
    *,
    field_name: str,
    old_value: Any,
    new_value: Any,
    new_state: dict[str, Any],
    message_id: int | None,
    source: str,
    confidence: float,
    trace_id: str | None,
) -> dict[str, Any]:
    version = int(session.working_state_version or 0) + 1
    now = datetime.utcnow()
    session.working_state = normalize_working_state(new_state)
    session.working_state_version = version
    session.working_state_updated_at = now
    db.add(
        WorkingStateEvent(
            session_id=session.id,
            message_id=message_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            source=source,
            confidence=float(confidence or 0.0),
            summary_version=int(session.summary_version or 0),
            state_version=version,
            trace_id=trace_id,
        )
    )
    await db.flush()
    return session.working_state or {}


__all__ = [
    "get_working_state",
    "normalize_working_state",
    "upsert_active_entity",
    "upsert_constraints",
    "upsert_reply_preference",
]
