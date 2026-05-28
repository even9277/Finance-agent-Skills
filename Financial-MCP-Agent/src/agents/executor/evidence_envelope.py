from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from pydantic import BaseModel, Field

from src.agents.tool_discovery.executable_registry import ExecutableToolSpec


class EvidenceEnvelope(BaseModel):
    evidence_id: str
    tool_call_id: str
    step_id: str
    plan_id: str
    trace_id: str
    tool_name: str
    ok: bool
    source: str = "tushare"
    source_api: str
    evidence_type: str
    symbol: str | None = None
    trade_date: str | None = None
    data_time: str | None = None
    fetch_ts: str
    api_family: str
    payload_summary: dict[str, Any] | list[Any] | None = None
    payload_ref: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    cache_hit: bool = False
    retry_count: int = 0
    is_primary_evidence: bool = True


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _new_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex}"


def _payload_summary(payload: Any, *, max_items: int = 5) -> dict[str, Any] | list[Any] | None:
    if payload is None:
        return None
    if isinstance(payload, list):
        return payload[:max_items]
    if isinstance(payload, dict):
        summary = dict(payload)
        for key, value in list(summary.items()):
            if isinstance(value, list):
                summary[key] = value[:max_items]
        return summary
    return {"value": str(payload)[:500]}


def normalize_evidence_envelope(
    *,
    raw: Any,
    spec: ExecutableToolSpec,
    step_id: str,
    plan_id: str,
    trace_id: str,
    tool_call_id: str,
    tool_name: str,
    retry_count: int = 0,
) -> EvidenceEnvelope:
    data = dict(raw or {}) if isinstance(raw, dict) else {"payload": raw}
    error = data.get("error")
    ok = bool(data.get("ok", error in (None, "")))
    fetch_ts = str(data.get("fetch_ts") or data.get("data_time") or _now_text())
    return EvidenceEnvelope(
        evidence_id=str(data.get("evidence_id") or _new_evidence_id()),
        tool_call_id=tool_call_id,
        step_id=step_id,
        plan_id=plan_id,
        trace_id=trace_id,
        tool_name=tool_name,
        ok=ok,
        source=str(data.get("source") or spec.namespace or "tushare"),
        source_api=str(data.get("source_api") or spec.source_api),
        evidence_type=str(data.get("evidence_type") or spec.evidence_type),
        symbol=str(data.get("symbol") or "") or None,
        trade_date=str(data.get("trade_date") or "") or None,
        data_time=str(data.get("data_time") or fetch_ts),
        fetch_ts=fetch_ts,
        api_family=str(data.get("api_family") or spec.api_family),
        payload_summary=_payload_summary(data.get("payload")),
        payload_ref=str(data.get("payload_ref") or "") or None,
        error_type=str(data.get("error_type") or "") or ("tool_error" if error else None),
        error_message=str(error or data.get("error_message") or "") or None,
        cache_hit=bool(data.get("cache_hit", False)),
        retry_count=int(data.get("retry_count", retry_count) or 0),
        is_primary_evidence=bool(spec.is_primary_evidence),
    )


__all__ = ["EvidenceEnvelope", "normalize_evidence_envelope"]
