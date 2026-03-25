from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from typing import Any, Iterator

from src.utils.logging_config import setup_logger

logger = setup_logger("skill_trace")

_TRACE_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "skill_trace_context",
    default={},
)


def _sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def _base_event_payload() -> dict[str, Any]:
    current = dict(_TRACE_CONTEXT.get() or {})
    if "session_id" in current and current["session_id"]:
        current["session_id"] = str(current["session_id"])[:8]
    if "user_id" in current and current["user_id"]:
        current["user_id"] = str(current["user_id"])[:8]
    return current


@contextmanager
def skill_trace_context(**kwargs: Any) -> Iterator[None]:
    current = dict(_TRACE_CONTEXT.get() or {})
    current.update({k: v for k, v in kwargs.items() if v is not None})
    token = _TRACE_CONTEXT.set(current)
    try:
        yield
    finally:
        _TRACE_CONTEXT.reset(token)


def log_router_decision(**kwargs: Any) -> None:
    payload = _base_event_payload()
    payload.update(kwargs)
    logger.info("chat.router.decision %s", payload)


def log_skill_selected(**kwargs: Any) -> None:
    payload = _base_event_payload()
    payload.update(kwargs)
    logger.info("chat.skill.selected %s", payload)


def log_tool_plan(**kwargs: Any) -> None:
    payload = _base_event_payload()
    payload.update(kwargs)
    logger.info("chat.tool.plan %s", payload)


def log_model_stage(**kwargs: Any) -> None:
    payload = _base_event_payload()
    payload.update(kwargs)
    logger.info("chat.model.stage %s", payload)


def log_reply_completed(**kwargs: Any) -> None:
    payload = _base_event_payload()
    payload.update(kwargs)
    logger.info("chat.reply.completed %s", payload)


@contextmanager
def log_tool_call(tool_name: str, **kwargs: Any) -> Iterator[None]:
    payload = _base_event_payload()
    payload["tool_name"] = tool_name
    payload["args_summary"] = {
        key: _sanitize_value(value)
        for key, value in kwargs.items()
        if key.lower() not in {"token", "memory_context", "profile_summary", "payload"}
    }
    start = time.perf_counter()
    logger.info("chat.tool.start %s", payload)
    try:
        yield
    except Exception as exc:
        payload["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
        payload["error"] = _sanitize_value(exc)
        logger.error("chat.tool.error %s", payload, exc_info=True)
        raise
    else:
        payload["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
        logger.info("chat.tool.end %s", payload)
