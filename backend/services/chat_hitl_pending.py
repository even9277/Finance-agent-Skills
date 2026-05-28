"""In-memory pending state for skill-route HITL (low-confidence confirm).

Survives until confirm API consumes it or TTL expires. Not durable across process
restart; acceptable for MVP per plan (SSE + API callback).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

_TTL = timedelta(minutes=30)
_PENDING: dict[str, dict[str, Any]] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_pending_skill_confirm(session_id: str, payload: dict[str, Any]) -> None:
    data = copy.deepcopy(payload)
    data["_stored_at"] = _utcnow().isoformat()
    _PENDING[session_id] = data


def pop_pending_skill_confirm(session_id: str) -> dict[str, Any] | None:
    raw = _PENDING.pop(session_id, None)
    if not raw:
        return None
    stored = raw.get("_stored_at")
    if stored:
        try:
            t = datetime.fromisoformat(str(stored))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if _utcnow() - t.astimezone(timezone.utc) > _TTL:
                return None
        except Exception:
            pass
    out = dict(raw)
    out.pop("_stored_at", None)
    return out


def peek_pending_skill_confirm(session_id: str) -> dict[str, Any] | None:
    """Read without consuming (debug)."""
    raw = _PENDING.get(session_id)
    if not raw:
        return None
    out = copy.deepcopy(raw)
    out.pop("_stored_at", None)
    return out
