from __future__ import annotations

from datetime import datetime
import os
from typing import Any

from src.utils.logging_config import setup_logger

logger = setup_logger("langfuse_exporter")


class LangfuseTraceExporter:
    """
    Langfuse exporter bridge for the local skill_trace record contract.

    This exporter is intentionally defensive:
    - if langfuse is not installed or env is incomplete, it degrades to a no-op
    - business code should still emit only local trace records via skill_trace.py
    """

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        host: str,
        environment: str,
        release: str,
        sample_rate: float | None = None,
        flush_at: int | None = None,
        flush_interval: float | None = None,
    ) -> None:
        self.host = base_url or host
        self.base_url = base_url or host
        self.environment = environment
        self.release = release
        self.enabled = False
        self.disabled_reason = ""
        self._client = None
        self._langfuse_trace_ids: dict[str, str] = {}
        self._trace_state: dict[str, dict[str, Any]] = {}
        self._span_cache: dict[str, Any] = {}

        if not public_key or not secret_key:
            self.disabled_reason = "missing public/secret key"
            return

        try:
            from langfuse import Langfuse
        except Exception as exc:
            self.disabled_reason = f"langfuse import failed: {exc}"
            return

        try:
            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                base_url=(base_url or None),
                host=(host or None),
                environment=environment or None,
                release=release or None,
                sample_rate=sample_rate,
                flush_at=flush_at,
                flush_interval=flush_interval,
            )
            self.enabled = True
        except Exception as exc:
            self.disabled_reason = f"langfuse client init failed: {exc}"

    @classmethod
    def from_env(cls) -> "LangfuseTraceExporter":
        base_url = os.getenv("LANGFUSE_BASE_URL", "").strip()
        host = os.getenv("LANGFUSE_HOST", "").strip() or base_url or "https://cloud.langfuse.com"

        sample_rate_raw = os.getenv("LANGFUSE_SAMPLE_RATE", "").strip()
        flush_at_raw = os.getenv("LANGFUSE_FLUSH_AT", "").strip()
        flush_interval_raw = os.getenv("LANGFUSE_FLUSH_INTERVAL_SEC", "").strip()
        return cls(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
            base_url=base_url,
            host=host,
            environment=os.getenv("LANGFUSE_ENV", "dev").strip(),
            release=os.getenv("LANGFUSE_RELEASE", "").strip(),
            sample_rate=float(sample_rate_raw) if sample_rate_raw else None,
            flush_at=int(flush_at_raw) if flush_at_raw else None,
            flush_interval=float(flush_interval_raw) if flush_interval_raw else None,
        )

    def __call__(self, record: dict[str, Any]) -> None:
        if not self.enabled or self._client is None:
            return

        record_type = str(record.get("record_type") or "")
        trace_id = str(record.get("trace_id") or "").strip()
        if not trace_id:
            return

        if record_type == "trace":
            self._ingest_trace(record)
        elif record_type == "span":
            self._ingest_span(record)
        elif record_type == "event":
            self._ingest_event(record)

    def _normalize_name(self, record: dict[str, Any]) -> str:
        name = str(record.get("name") or "event")
        data = record.get("data") or {}
        if name == "tool_call":
            tool_name = str(data.get("tool_name") or "").strip()
            if tool_name:
                return f"tool:{tool_name}"
        return name

    def _scalar(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (bool, int, float, str)):
            return value
        return str(value)

    def _flatten_metadata(self, record: dict[str, Any]) -> dict[str, Any]:
        data = record.get("data") or {}
        metrics = record.get("metrics") or {}
        refs = record.get("refs") or {}

        metadata: dict[str, Any] = {
            "workflow_name": record.get("workflow_name"),
            "trace_schema_version": record.get("trace_schema_version"),
            "policy_version": record.get("policy_version"),
            "group_id": record.get("group_id"),
            "session_id": record.get("session_id"),
            "user_id": record.get("user_id"),
            "turn_index": record.get("turn_index"),
            "record_type": record.get("record_type"),
            "stage": record.get("stage"),
            "status": record.get("status"),
            "duration_ms": record.get("duration_ms"),
            "span_name": self._normalize_name(record),
        }

        preferred_data_keys = {
            "selected_skill_family",
            "selected_skill",
            "skill_name",
            "analysis_mode",
            "execution_policy",
            "mode",
            "planner_type",
            "tool_name",
            "model",
            "execution_path",
            "router_model",
            "memory_enabled",
            "queued",
            "enqueue_skipped_reason",
            "claim_count",
            "evidence_ok",
        }
        preferred_metric_keys = {
            "route_confidence",
            "tool_batch_size",
            "tool_failure_rate",
            "p95_latency",
            "degrade_stage",
            "policy_violation_count",
            "evidence_ok",
        }
        preferred_ref_keys = {
            "prompt_ref",
            "reply_ref",
            "claim_ref",
        }

        for key, value in data.items():
            if key in preferred_data_keys:
                metadata[key] = self._scalar(value)

        for key, value in metrics.items():
            if key in preferred_metric_keys:
                metadata[key] = self._scalar(value)

        for key, value in refs.items():
            if key in preferred_ref_keys:
                metadata[key] = self._scalar(value)

        return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}

    def _trace_context(self, record: dict[str, Any], *, parent_observation_id: str | None = None) -> dict[str, Any]:
        context = {"trace_id": self._langfuse_trace_id(str(record.get("trace_id") or "").strip())}
        if parent_observation_id:
            context["parent_observation_id"] = parent_observation_id
        return context

    def _langfuse_trace_id(self, local_trace_id: str) -> str:
        if not local_trace_id:
            return ""
        if local_trace_id in self._langfuse_trace_ids:
            return self._langfuse_trace_ids[local_trace_id]
        if self._client is None:
            return local_trace_id
        try:
            langfuse_trace_id = self._client.create_trace_id(seed=local_trace_id)
        except Exception:
            langfuse_trace_id = local_trace_id
        self._langfuse_trace_ids[local_trace_id] = langfuse_trace_id
        return langfuse_trace_id

    def _trace_tags(self, record: dict[str, Any]) -> list[str]:
        data = record.get("data") or {}
        tags = [
            str(record.get("workflow_name") or "").strip(),
            str(record.get("stage") or "").strip(),
            str(data.get("selected_skill_family") or "").strip(),
            str(data.get("skill_name") or "").strip(),
        ]
        return [item for item in tags if item]

    def _trace_input(self, record: dict[str, Any]) -> Any:
        data = record.get("data") or {}
        if record.get("status") == "started":
            summary = data.get("user_query_summary")
            if summary:
                return {"summary": summary}
            if not self._allow_prompt_reply_upload():
                return self._privacy_preserving_payload(data)
            return data or None
        return None

    def _trace_output(self, record: dict[str, Any]) -> Any:
        if record.get("status") == "started":
            return None
        data = record.get("data") or {}
        metrics = record.get("metrics") or {}
        # 默认只上传结构化状态、引用路径和指标，完整 prompt/reply 需显式开关放行。
        payload = {**data} if self._allow_prompt_reply_upload() else self._privacy_preserving_payload(data)
        if metrics:
            payload["metrics"] = metrics
        return payload or None

    def _allow_prompt_reply_upload(self) -> bool:
        return os.getenv("LANGFUSE_UPLOAD_PROMPT_REPLY", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _privacy_preserving_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        sensitive_keys = {
            "prompt",
            "prompt_text",
            "synthesis_prompt",
            "user_message",
            "user_query",
            "reply",
            "reply_text",
            "answer",
            "final_answer",
        }
        return {key: value for key, value in payload.items() if key not in sensitive_keys}

    def _upsert_trace(self, record: dict[str, Any]) -> None:
        local_trace_id = str(record.get("trace_id") or "").strip()
        if not local_trace_id:
            return
        trace_id = self._langfuse_trace_id(local_trace_id)

        state = self._trace_state.setdefault(local_trace_id, {})
        trace_name = str(record.get("name") or state.get("name") or record.get("workflow_name") or "chat-skill-turn")
        user_id = str(record.get("user_id") or state.get("user_id") or "").strip() or None
        session_id = str(record.get("session_id") or state.get("session_id") or record.get("group_id") or "").strip() or None
        metadata = {**state.get("metadata", {}), **self._flatten_metadata(record)}
        tags = list(dict.fromkeys([*(state.get("tags") or []), *self._trace_tags(record)]))
        trace_input = self._trace_input(record) or state.get("input")
        trace_output = self._trace_output(record) or state.get("output")

        state.update(
            {
                "name": trace_name,
                "user_id": user_id,
                "session_id": session_id,
                "metadata": metadata,
                "tags": tags,
                "input": trace_input,
                "output": trace_output,
            }
        )

        try:
            from langfuse._client.client import TraceBody

            event = {
                "id": self._client.create_trace_id(),
                "type": "trace-create",
                "timestamp": datetime.utcnow(),
                "body": TraceBody(
                    id=trace_id,
                    name=trace_name,
                    user_id=user_id,
                    session_id=session_id,
                    input=trace_input,
                    output=trace_output,
                    release=self.release or None,
                    version=str(record.get("trace_schema_version") or "") or None,
                    metadata=metadata or None,
                    tags=tags or None,
                    environment=self.environment or None,
                ),
            }
            if getattr(self._client, "_resources", None) is not None:
                self._client._resources.add_trace_task(event)
        except Exception as exc:
            logger.warning("langfuse.trace_upsert_failed %s", {"error": str(exc)})

    def _resolve_parent_observation_id(self, record: dict[str, Any]) -> str | None:
        if str(record.get("record_type") or "") == "event":
            current_local_id = str(record.get("span_id") or "").strip()
            if current_local_id:
                current = self._span_cache.get(current_local_id)
                if current is not None:
                    return getattr(current, "id", None)

        parent_local_id = str(record.get("parent_span_id") or "").strip()
        if not parent_local_id:
            return None
        parent = self._span_cache.get(parent_local_id)
        if parent is None:
            return
        return getattr(parent, "id", None)

    def _ensure_current_span_from_event(self, record: dict[str, Any]) -> None:
        if str(record.get("record_type") or "") != "event":
            return

        local_span_id = str(record.get("span_id") or "").strip()
        if not local_span_id or local_span_id in self._span_cache:
            return

        try:
            placeholder = self._client.start_observation(
                trace_context=self._trace_context(
                    record,
                    parent_observation_id=self._resolve_parent_observation_id(
                        {
                            **record,
                            "record_type": "span",
                            "span_id": local_span_id,
                        }
                    ),
                ),
                name=f"{str(record.get('stage') or 'span')}:pending",
                as_type="span",
                metadata=self._flatten_metadata(record),
            )
            self._span_cache[local_span_id] = placeholder
        except Exception as exc:
            logger.warning("langfuse.span_placeholder_failed %s", {"error": str(exc)})

    def _ingest_trace(self, record: dict[str, Any]) -> None:
        self._upsert_trace(record)

    def _ingest_span(self, record: dict[str, Any]) -> None:
        self._upsert_trace(record)
        span_id = str(record.get("span_id") or "").strip()
        if not span_id:
            return
        if span_id in self._span_cache:
            span = self._span_cache[span_id]
        else:
            try:
                parent_observation_id = self._resolve_parent_observation_id(record)
                span = self._client.start_observation(
                    trace_context=self._trace_context(record, parent_observation_id=parent_observation_id),
                    name=self._normalize_name(record),
                    as_type="span",
                    metadata=self._flatten_metadata(record),
                    input=record.get("data") or {},
                    output=record.get("metrics") or {},
                )
                self._span_cache[span_id] = span
            except Exception as exc:
                logger.warning("langfuse.span_create_failed %s", {"error": str(exc)})
                return
        try:
            span.update(
                name=self._normalize_name(record),
                input=record.get("data") or {},
                output={
                    "status": record.get("status"),
                    "metrics": record.get("metrics") or {},
                },
                metadata=self._flatten_metadata(record),
            )
            span.end()
        except Exception as exc:
            logger.warning("langfuse.span_update_failed %s", {"error": str(exc)})

    def _ingest_event(self, record: dict[str, Any]) -> None:
        self._upsert_trace(record)
        self._ensure_current_span_from_event(record)

        data = record.get("data") or {}
        if str(record.get("name") or "") == "chat.reply.completed" and str(data.get("mode") or "") == "skill-stream":
            return

        try:
            parent_observation_id = self._resolve_parent_observation_id(record)
            if parent_observation_id:
                current_local_id = str(record.get("span_id") or "").strip()
                parent_span = self._span_cache.get(current_local_id) or self._span_cache.get(str(record.get("parent_span_id") or "").strip())
                if parent_span is not None and hasattr(parent_span, "create_event"):
                    parent_span.create_event(
                        name=str(record.get("name") or "event"),
                        input=data or {},
                        metadata=self._flatten_metadata(record),
                    )
                    return

            self._client.create_event(
                trace_context=self._trace_context(record, parent_observation_id=parent_observation_id),
                name=str(record.get("name") or "event"),
                input=data or {},
                metadata=self._flatten_metadata(record),
            )
        except Exception as exc:
            logger.warning("langfuse.event_failed %s", {"error": str(exc)})

    def flush(self) -> None:
        if self.enabled and self._client is not None:
            try:
                self._client.flush()
            except Exception as exc:
                logger.warning("langfuse.flush_failed %s", {"error": str(exc)})
