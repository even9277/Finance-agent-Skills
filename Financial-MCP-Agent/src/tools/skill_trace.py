from __future__ import annotations

import contextvars
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from src.utils.logging_config import setup_logger

logger = setup_logger("skill_trace")
_TRACE_SCHEMA_VERSION = "2026-04-07.1"
_TRACE_POLICY_VERSION = "trace-v1"
_TRACE_WORKFLOW_NAME = "chat-skill-turn"
_JSONL_PATH = Path(__file__).resolve().parents[2] / "logs" / "chat_traces.jsonl"
_JSONL_LOCK = threading.Lock()
_EXPORTERS_LOCK = threading.Lock()
_RUNTIME_LOCK = threading.Lock()
_TRACE_EXPORTERS: list[Any] = []
_TRACE_RUNTIME_INITIALIZED = False
_LOG_TOP_LEVEL_KEYS = {
    "trace_id",
    "group_id",
    "span_id",
    "parent_span_id",
    "workflow_name",
    "policy_version",
    "trace_schema_version",
    "session_id",
    "user_id",
    "turn_index",
}
_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "cookie",
    "password",
    "passwd",
    "secret",
    "secret_key",
    "connection_string",
    "database_url",
    "tushare_token",
}
_REDACTED_VALUE = "[REDACTED]"

_TRACE_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "skill_trace_context",
    default={},
)
_SPAN_STACK: contextvars.ContextVar[tuple[dict[str, Any], ...]] = contextvars.ContextVar(
    "skill_trace_span_stack",
    default=(),
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _is_sensitive_key(key: object) -> bool:
    """判断字段名是否可能包含凭证或连接信息。"""
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized in _SENSITIVE_KEYS:
        return True
    return any(
        marker in normalized
        for marker in ("api_key", "access_token", "refresh_token", "password", "secret")
    )


def _sanitize_value(value: Any) -> Any:
    """递归截断值并按字段名移除敏感信息。"""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _REDACTED_VALUE if _is_sensitive_key(key) else _sanitize_value(val)
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    text = str(value)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def _event_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _full_trace_context() -> dict[str, Any]:
    current = dict(_TRACE_CONTEXT.get() or {})
    current.setdefault("workflow_name", _TRACE_WORKFLOW_NAME)
    current.setdefault("policy_version", _TRACE_POLICY_VERSION)
    current.setdefault("trace_schema_version", _TRACE_SCHEMA_VERSION)
    return current


def _current_span() -> dict[str, Any]:
    stack = _SPAN_STACK.get() or ()
    return dict(stack[-1]) if stack else {}


def _record_envelope(
    *,
    record_type: str,
    name: str,
    stage: str | None = None,
    status: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_ms: float | int | None = None,
    data: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _full_trace_context()
    span = _current_span()
    record = {
        "record_type": record_type,
        "trace_id": context.get("trace_id"),
        "group_id": context.get("group_id"),
        "span_id": span.get("span_id"),
        "parent_span_id": span.get("parent_span_id"),
        "workflow_name": context.get("workflow_name"),
        "trace_schema_version": context.get("trace_schema_version"),
        "policy_version": context.get("policy_version"),
        "timestamp": _event_timestamp(),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "status": status,
        "name": name,
        "stage": stage,
        "data": data or {},
        "metrics": metrics or {},
        "refs": refs or {},
    }
    for key, value in context.items():
        if key in record or value is None:
            continue
        record[key] = value
    return record


def _log_record_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in _LOG_TOP_LEVEL_KEYS:
        value = record.get(key)
        if value is None:
            continue
        if key in {"session_id", "user_id"}:
            payload[key] = str(value)[:8]
        else:
            payload[key] = value
    for bucket in ("data", "metrics", "refs"):
        section = record.get(bucket) or {}
        if section:
            payload[bucket] = _sanitize_value(section)
    if record.get("status") is not None:
        payload["status"] = record["status"]
    if record.get("duration_ms") is not None:
        payload["duration_ms"] = record["duration_ms"]
    if record.get("stage") is not None:
        payload["stage"] = record["stage"]
    return payload


def _write_jsonl_record(record: dict[str, Any]) -> None:
    try:
        _JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _JSONL_LOCK:
            with _JSONL_PATH.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(_sanitize_value(record), ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logger.warning("chat.trace.jsonl_write_failed %s", {"error": _sanitize_value(exc)})


def register_trace_exporter(exporter: Callable[[dict[str, Any]], None]) -> None:
    with _EXPORTERS_LOCK:
        _TRACE_EXPORTERS.append(exporter)


def clear_trace_exporters() -> None:
    with _EXPORTERS_LOCK:
        _TRACE_EXPORTERS.clear()


def _dispatch_exporters(record: dict[str, Any]) -> None:
    with _EXPORTERS_LOCK:
        exporters = list(_TRACE_EXPORTERS)
    for exporter in exporters:
        try:
            # Exporter 与本地 JSONL 一样只能接触脱敏后的 Trace，避免可选观测出口绕过安全边界。
            exporter(_sanitize_value(record))
        except Exception as exc:
            logger.warning("chat.trace.export_failed %s", {"error": _sanitize_value(exc)})


def flush_trace_exporters() -> None:
    with _EXPORTERS_LOCK:
        exporters = list(_TRACE_EXPORTERS)
    for exporter in exporters:
        flush = getattr(exporter, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception as exc:
                logger.warning("chat.trace.flush_failed %s", {"error": _sanitize_value(exc)})


def initialize_trace_runtime(*, force: bool = False) -> None:
    global _TRACE_RUNTIME_INITIALIZED
    with _RUNTIME_LOCK:
        if _TRACE_RUNTIME_INITIALIZED and not force:
            return
        if force:
            clear_trace_exporters()

        if _bool_env("ENABLE_LANGFUSE", False):
            try:
                from src.tools.trace_exporters.langfuse_exporter import LangfuseTraceExporter

                exporter = LangfuseTraceExporter.from_env()
                if exporter.enabled:
                    register_trace_exporter(exporter)
                    logger.info("chat.trace.langfuse_enabled %s", {"host": exporter.host})
                else:
                    logger.info("chat.trace.langfuse_disabled %s", {"reason": exporter.disabled_reason})
            except Exception as exc:
                logger.warning("chat.trace.langfuse_init_failed %s", {"error": _sanitize_value(exc)})

        _TRACE_RUNTIME_INITIALIZED = True


def _emit_record(
    *,
    record_type: str,
    name: str,
    data: dict[str, Any] | None = None,
    stage: str | None = None,
    status: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_ms: float | int | None = None,
    metrics: dict[str, Any] | None = None,
    refs: dict[str, Any] | None = None,
    level: str = "info",
    exc_info: bool = False,
) -> None:
    record = _record_envelope(
        record_type=record_type,
        name=name,
        stage=stage,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        data=data,
        metrics=metrics,
        refs=refs,
    )
    _write_jsonl_record(record)
    _dispatch_exporters(record)
    log_payload = _log_record_payload(record)
    if level == "error":
        logger.error("%s %s", name, log_payload, exc_info=exc_info)
    elif level == "warning":
        logger.warning("%s %s", name, log_payload)
    else:
        logger.info("%s %s", name, log_payload)


@contextmanager
def skill_trace_context(**kwargs: Any) -> Iterator[None]:
    current = dict(_TRACE_CONTEXT.get() or {})
    current.update({k: v for k, v in kwargs.items() if v is not None})
    token = _TRACE_CONTEXT.set(current)
    try:
        yield
    finally:
        _TRACE_CONTEXT.reset(token)


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex}"


def new_span_id() -> str:
    return f"sp_{uuid.uuid4().hex}"


def new_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex}"


def new_claim_id() -> str:
    return f"clm_{uuid.uuid4().hex}"


def _artifact_root() -> Path:
    configured = os.getenv("TRACE_ARTIFACT_DIR", "").strip()
    if configured:
        return Path(configured)
    return _JSONL_PATH.parent / "chat_trace_artifacts"


def _artifact_enabled(kind: str) -> bool:
    if kind == "prompt":
        return _bool_env("ENABLE_TRACE_PROMPT_CAPTURE", False)
    if kind == "reply":
        return _bool_env("ENABLE_TRACE_REPLY_CAPTURE", False)
    return _bool_env("ENABLE_TRACE_ARTIFACT_REFS", False)


def write_trace_artifact(
    kind: str,
    content: Any,
    *,
    extension: str = "json",
    file_stem: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any] | None:
    if not _artifact_enabled(kind):
        return None

    current_trace_id = trace_id or str((_full_trace_context().get("trace_id") or "")).strip()
    if not current_trace_id:
        return None

    extension = extension.lstrip(".") or "txt"
    dated_dir = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    subdir = {
        "payload": "tool_payloads",
        "prompt": "prompts",
        "reply": "replies",
        "claims": "claims",
    }.get(kind, kind)
    root = _artifact_root() / dated_dir / current_trace_id / subdir
    root.mkdir(parents=True, exist_ok=True)

    safe_stem = str(file_stem or f"{kind}_{uuid.uuid4().hex}").replace("/", "_")
    path = root / f"{safe_stem}.{extension}"
    if extension == "json":
        serialized = json.dumps(content, ensure_ascii=False, default=str, indent=2)
    else:
        serialized = str(content)
    path.write_text(serialized, encoding="utf-8")
    return {
        "artifact_kind": kind,
        "path": str(path),
        "relative_path": str(path.relative_to(_artifact_root())),
    }


@contextmanager
def trace_span(
    name: str,
    *,
    stage: str,
    data: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    refs: dict[str, Any] | None = None,
    status_on_error: str = "error",
) -> Iterator[str]:
    stack = _SPAN_STACK.get() or ()
    parent_span_id = stack[-1]["span_id"] if stack else None
    span = {
        "span_id": new_span_id(),
        "parent_span_id": parent_span_id,
        "name": name,
        "stage": stage,
    }
    token = _SPAN_STACK.set(stack + (span,))
    started_at = _event_timestamp()
    started = time.perf_counter()
    try:
        yield span["span_id"]
    except Exception as exc:
        _emit_record(
            record_type="span",
            name=name,
            stage=stage,
            status=status_on_error,
            started_at=started_at,
            ended_at=_event_timestamp(),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            data={**(data or {}), "error": _sanitize_value(exc)},
            metrics=metrics,
            refs=refs,
            level="error",
            exc_info=True,
        )
        raise
    else:
        _emit_record(
            record_type="span",
            name=name,
            stage=stage,
            status="ok",
            started_at=started_at,
            ended_at=_event_timestamp(),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            data=data,
            metrics=metrics,
            refs=refs,
        )
    finally:
        _SPAN_STACK.reset(token)


def log_router_decision(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.router.decision", stage="route", data=kwargs)


def log_skill_selected(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.skill.selected", stage="executor", data=kwargs)


def log_tool_plan(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.tool.plan", stage="executor", data=kwargs)


def log_model_stage(**kwargs: Any) -> None:
    stage = str(kwargs.get("stage") or "model")
    _emit_record(record_type="event", name="chat.model.stage", stage=stage, data=kwargs)


def log_reply_completed(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.reply.completed", stage="reply", data=kwargs)


def log_policy_violation(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.policy_violation", stage="executor", data=kwargs, level="warning")


def log_degrade_transition(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.degrade_transition", stage="executor", data=kwargs, level="warning")


def log_claim_lineage(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.claim_lineage", stage="reply", data=kwargs)


def log_memory_enqueue(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.memory_write_enqueue", stage="memory", data=kwargs)


def log_compaction_enqueue(**kwargs: Any) -> None:
    _emit_record(record_type="event", name="chat.compaction_enqueue", stage="memory", data=kwargs)


def log_trace_started(**kwargs: Any) -> None:
    metrics = kwargs.pop("metrics", None)
    refs = kwargs.pop("refs", None)
    _emit_record(
        record_type="trace",
        name="chat-skill-turn",
        stage="workflow",
        status="started",
        data=kwargs,
        metrics=metrics,
        refs=refs,
    )


def log_trace_finished(**kwargs: Any) -> None:
    payload = dict(kwargs)
    status = str(payload.pop("status", "ok"))
    duration_ms = payload.pop("duration_ms", None)
    metrics = payload.pop("metrics", None)
    refs = payload.pop("refs", None)
    _emit_record(
        record_type="trace",
        name="chat-skill-turn",
        stage="workflow",
        status=status,
        duration_ms=duration_ms,
        data=payload,
        metrics=metrics,
        refs=refs,
    )


@contextmanager
def log_tool_call(tool_name: str, **kwargs: Any) -> Iterator[None]:
    payload = {
        "tool_name": tool_name,
        "tool_args_summary": {
            key: _sanitize_value(value)
            for key, value in kwargs.items()
            if key.lower() not in {"token", "memory_context", "profile_summary", "payload"}
        },
    }
    started = time.perf_counter()
    with trace_span(
        "tool_call",
        stage="executor",
        data={
            "tool_name": tool_name,
            "tool_args_summary": payload["tool_args_summary"],
        },
    ):
        _emit_record(
            record_type="event",
            name="chat.tool.start",
            stage="executor",
            status="started",
            data=payload,
        )
        try:
            yield
        except Exception as exc:
            _emit_record(
                record_type="event",
                name="chat.tool.error",
                stage="executor",
                status="error",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                data={**payload, "error": _sanitize_value(exc)},
                level="error",
                exc_info=True,
            )
            raise
        else:
            _emit_record(
                record_type="event",
                name="chat.tool.end",
                stage="executor",
                status="ok",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                data=payload,
            )
