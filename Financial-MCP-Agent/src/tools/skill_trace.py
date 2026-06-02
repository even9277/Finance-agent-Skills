from __future__ import annotations

import concurrent.futures
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

_TRACE_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "skill_trace_context",
    default={},
)
_SPAN_STACK: contextvars.ContextVar[tuple[dict[str, Any], ...]] = contextvars.ContextVar(
    "skill_trace_span_stack",
    default=(),
)
# 当前轮次内收集到的 span 记录列表（只在 skill_trace_context 内有效）
# 每个元素是 {"name", "duration_ms", "status", "data"} 的 dict
_TURN_SPANS: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "skill_trace_turn_spans",
    default=None,
)

# 全局线程池，用于异步写报告，避免阻塞主流程
_REPORT_EXECUTOR: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="session_reporter",
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# 观测系统全局总开关：设置 ENABLE_SKILL_TRACE=false 可一键关闭所有埋点写入
# 默认开启，生产环境如需完全关闭追踪可通过环境变量控制
_TRACE_MASTER_ENABLED: bool = _bool_env("ENABLE_SKILL_TRACE", True)


def _sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize_value(val) for key, val in value.items()}
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
                fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
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
            exporter(dict(record))
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

        if _bool_env("ENABLE_TRACE_DB_SINK", False):
            try:
                from src.tools.trace_db_sink import is_trace_db_sink_enabled

                if is_trace_db_sink_enabled():
                    logger.info("chat.trace.db_sink_enabled")
            except Exception as exc:
                logger.warning("chat.trace.db_sink_init_failed %s", {"error": _sanitize_value(exc)})

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
    # 总开关：关闭时跳过所有写入，不影响主流程
    if not _TRACE_MASTER_ENABLED:
        return
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
    try:
        from src.tools.trace_db_sink import enqueue_trace_record

        enqueue_trace_record(record)
    except Exception as exc:
        logger.warning("chat.trace.db_sink_enqueue_failed %s", {"error": _sanitize_value(exc)})
    log_payload = _log_record_payload(record)
    if level == "error":
        logger.error("%s %s", name, log_payload, exc_info=exc_info)
    elif level == "warning":
        logger.warning("%s %s", name, log_payload)
    else:
        logger.info("%s %s", name, log_payload)

    # 如果当前在 skill_trace_context 内部，且是 span 类型，把关键字段暂存到本轮列表
    if record_type == "span":
        turn_spans = _TURN_SPANS.get()
        if turn_spans is not None:
            turn_spans.append(
                {
                    "name": name,
                    "stage": stage,
                    "status": status or "ok",
                    "duration_ms": duration_ms,
                    "data": dict(data or {}),
                }
            )


def _trigger_session_report(
    session_id: str,
    turn_index: int,
    user_message: str,
    reply_summary: str,
    span_records: list[dict[str, Any]],
) -> None:
    """在独立线程中生成会话 Markdown 报告，不阻塞主流程。"""
    if not _bool_env("ENABLE_SESSION_REPORT", True):
        return
    try:
        from src.tools.session_reporter import append_turn_to_session_report

        append_turn_to_session_report(
            session_id=session_id,
            turn_index=turn_index,
            user_message=user_message,
            reply_summary=reply_summary,
            span_records=span_records,
        )
    except Exception as exc:
        logger.warning("skill_trace.report_trigger_failed %s", {"error": _sanitize_value(exc)})


@contextmanager
def skill_trace_context(**kwargs: Any) -> Iterator[None]:
    """
    每次对话的顶层上下文管理器。

    使用方式：
        with skill_trace_context(session_id="xxx", turn_index=1, user_message="..."):
            ...（业务处理）...
            # 处理完成后可通过 set_turn_reply() 传入回答摘要

    退出时（无论成功或异常）：
    - 如果 ENABLE_SESSION_REPORT=true，异步写会话 Markdown 报告
    """
    current = dict(_TRACE_CONTEXT.get() or {})
    current.update({k: v for k, v in kwargs.items() if v is not None})
    ctx_token = _TRACE_CONTEXT.set(current)

    # 初始化本轮 span 收集列表
    span_list: list[dict[str, Any]] = []
    spans_token = _TURN_SPANS.set(span_list)

    try:
        yield
    finally:
        # 在 reset 前先读取最新的 context（业务侧可能通过 set_turn_reply 更新了 reply_summary）
        live_context = dict(_TRACE_CONTEXT.get() or {})

        _TRACE_CONTEXT.reset(ctx_token)
        _TURN_SPANS.reset(spans_token)

        # 收集当前上下文的关键字段，用于生成报告
        if _TRACE_MASTER_ENABLED and _bool_env("ENABLE_SESSION_REPORT", True):
            session_id = str(live_context.get("session_id") or current.get("session_id") or "unknown")
            turn_index = int(live_context.get("turn_index") or current.get("turn_index") or 0)
            user_message = str(live_context.get("user_message") or current.get("user_message") or "")
            # reply_summary 由业务侧通过 set_turn_reply() 写入 context
            reply_summary = str(live_context.get("reply_summary") or "")
            spans_snapshot = list(span_list)  # 已 reset，取副本

            try:
                _REPORT_EXECUTOR.submit(
                    _trigger_session_report,
                    session_id,
                    turn_index,
                    user_message,
                    reply_summary,
                    spans_snapshot,
                )
            except Exception as exc:
                logger.warning(
                    "skill_trace.report_submit_failed %s", {"error": _sanitize_value(exc)}
                )


def set_turn_reply(reply_summary: str) -> None:
    """
    在 skill_trace_context 内部调用，将本轮回答摘要写入当前上下文。
    用于报告生成时填写"系统回答"一列。

    参数：
      reply_summary - 回答的前200字左右的摘要（传入全文也可，报告生成器会自动截断）
    """
    current = dict(_TRACE_CONTEXT.get() or {})
    current["reply_summary"] = reply_summary
    _TRACE_CONTEXT.set(current)


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
    # 总开关：关闭时直接生成一个占位 span_id 并 yield，不做任何记录
    if not _TRACE_MASTER_ENABLED:
        yield new_span_id()
        return
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
