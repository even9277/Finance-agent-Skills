"""Rolling summary runtime for STM preflight and fallback compaction.

This module keeps the public API expected by ``chat_service`` and the
existing tests, while moving the source-of-truth toward structured payloads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session, SessionSummary, SummaryAuditLog
from backend.services.stm_context_service import refresh_session_context_metrics
from backend.services.token_counter import count_message_tokens, count_text_tokens

logger = logging.getLogger("stm_summary_runtime")

ROLLING_SUMMARY_SCHEMA_VERSION = "v2"
REQUIRED_SUMMARY_SECTIONS = (
    "Decisions",
    "Open TODOs",
    "Constraints/Rules",
    "Pending user asks",
    "Exact identifiers",
)

_SECTION_RE = re.compile(
    r"^##\s+(Decisions|Open TODOs|Constraints/Rules|Pending user asks|Exact identifiers)\s*$",
    re.MULTILINE,
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_STOCK_CODE_RE = re.compile(r"\b\d{6}\.(?:SH|SZ|BJ)\b|\b\d{6}\b|\b\d{5}\.HK\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_CHINESE_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,12}(?:ETF|指数|股票|基金)?")
_REPLACEMENT_VERB_RE = re.compile(r"(?:替换成|换成|改成|换为|改为)")
_REPLACEMENT_SLOT_HINTS: tuple[tuple[str, int], ...] = (
    ("第一家公司", 0),
    ("第1家公司", 0),
    ("第一家", 0),
    ("第一只", 0),
    ("第一个标的", 0),
    ("前者", 0),
    ("第二家公司", 1),
    ("第2家公司", 1),
    ("第二家", 1),
    ("第二只", 1),
    ("第二个标的", 1),
    ("后者", 1),
)
_FOLLOWUP_REFERENCE_HINTS = ("它", "上一题", "上一个", "前面", "刚才", "延续", "沿用", "继续")
_COMPARE_HINTS = ("和", "跟", "与", "一起", "放一起", "对比", "比较")


@dataclass(slots=True)
class PreflightSummaryDecision:
    should_compact: bool
    threshold_tokens: int
    projected_tokens: int
    pending_message_tokens: int
    prompt_overhead_tokens: int
    reason: str


@dataclass(slots=True)
class SummaryCompactionResult:
    compacted: bool
    reason: str
    summary_text: str | None = None
    summary_payload: dict[str, Any] | None = None
    summary_id: int | None = None
    summary_mode: str | None = None
    summary_trigger: str | None = None
    compressed_message_count: int = 0
    total_message_count: int = 0
    final_strategy: str = "skipped"
    summary_version_after: int | None = None
    schema_reasons: list[str] = field(default_factory=list)
    hot_updated_fields: list[str] = field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.utcnow()


def _utc_now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat() + "Z"


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _deepcopy_jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        item = _coerce_text(raw)
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _truncate_list(values: Iterable[str], *, max_items: int, max_len: int) -> list[str]:
    truncated: list[str] = []
    for item in _dedupe_keep_order(values):
        clipped = item[:max_len].strip()
        if clipped:
            truncated.append(clipped)
        if len(truncated) >= max_items:
            break
    return truncated


def _empty_summary_payload() -> dict[str, Any]:
    return {
        "schema_version": ROLLING_SUMMARY_SCHEMA_VERSION,
        "summary_version": 0,
        "reply_preference_hint": "",
        "active_entities": [],
        "constraints": [],
        "open_loops": [],
        "session_record_summary": "",
        "field_updated_at": {},
        "evidence_refs": {},
        "source_span": {},
        "noise_flags": [],
        "summary_quality": {
            "mode": "normal",
            "source": "empty",
            "audit_reasons": [],
        },
    }


def _empty_hot_fields_payload() -> dict[str, Any]:
    payload = _empty_summary_payload()
    payload["summary_quality"] = {
        "mode": "hot_update",
        "source": "heuristic",
        "audit_reasons": [],
    }
    return payload


def _normalize_active_entities(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_entities = payload.get("active_entities")
    if not isinstance(raw_entities, list):
        return []

    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        canonical_id = _coerce_text(raw.get("canonical_id"))
        display_name = _coerce_text(raw.get("display_name"))
        entity_type = _coerce_text(raw.get("entity_type")) or "symbol"
        market = _coerce_text(raw.get("market"))
        confidence = _coerce_text(raw.get("confidence")) or "medium"
        status = _coerce_text(raw.get("status")) or "active"
        source = _coerce_text(raw.get("source")) or "unknown"
        evidence_text = _coerce_text(raw.get("evidence_text"))
        first_seen_message_id = raw.get("first_seen_message_id")
        last_seen_message_id = raw.get("last_seen_message_id")
        if not canonical_id and not display_name:
            continue
        key = (canonical_id, display_name)
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "canonical_id": canonical_id,
                "display_name": display_name,
                "entity_type": entity_type,
                "market": market,
                "confidence": confidence,
                "status": status,
                "source": source,
                "evidence_text": evidence_text,
                "first_seen_message_id": int(first_seen_message_id) if isinstance(first_seen_message_id, int) else None,
                "last_seen_message_id": int(last_seen_message_id) if isinstance(last_seen_message_id, int) else None,
            }
        )
        if len(entities) >= 8:
            break
    return entities


def _normalize_summary_payload(
    payload: dict[str, Any] | None,
    *,
    base_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _empty_summary_payload()
    if isinstance(base_payload, dict):
        normalized.update(json.loads(json.dumps(base_payload)))
    if isinstance(payload, dict):
        normalized.update({k: v for k, v in payload.items() if v is not None})

    normalized["schema_version"] = ROLLING_SUMMARY_SCHEMA_VERSION
    normalized["summary_version"] = int(normalized.get("summary_version") or 0)
    normalized["reply_preference_hint"] = _coerce_text(normalized.get("reply_preference_hint"))[:220]
    normalized["constraints"] = _truncate_list(normalized.get("constraints") or [], max_items=8, max_len=120)
    normalized["open_loops"] = _truncate_list(normalized.get("open_loops") or [], max_items=6, max_len=160)
    normalized["session_record_summary"] = _coerce_text(normalized.get("session_record_summary"))[:800]
    normalized["noise_flags"] = _truncate_list(normalized.get("noise_flags") or [], max_items=8, max_len=80)
    normalized["active_entities"] = _normalize_active_entities(normalized)
    normalized["field_updated_at"] = (
        normalized.get("field_updated_at") if isinstance(normalized.get("field_updated_at"), dict) else {}
    )
    normalized["evidence_refs"] = (
        normalized.get("evidence_refs") if isinstance(normalized.get("evidence_refs"), dict) else {}
    )
    normalized["source_span"] = (
        normalized.get("source_span") if isinstance(normalized.get("source_span"), dict) else {}
    )
    normalized["summary_quality"] = (
        normalized.get("summary_quality") if isinstance(normalized.get("summary_quality"), dict) else {}
    )
    normalized["summary_quality"].setdefault("mode", "normal")
    normalized["summary_quality"].setdefault("source", "unknown")
    normalized["summary_quality"]["audit_reasons"] = _truncate_list(
        normalized["summary_quality"].get("audit_reasons") or [],
        max_items=8,
        max_len=80,
    )
    return normalized


def _entity_identity_key(entity: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(entity, dict):
        return ("", "")
    return (_coerce_text(entity.get("canonical_id")), _coerce_text(entity.get("display_name")))


def _same_entity(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    left_key = _entity_identity_key(left)
    right_key = _entity_identity_key(right)
    if not any(left_key) or not any(right_key):
        return False
    return left_key == right_key


def _clean_replacement_target_text(raw_text: str) -> str:
    candidate = _coerce_text(raw_text)
    if not candidate:
        return ""
    candidate = re.split(r"[，。,；;]", candidate, maxsplit=1)[0].strip()
    candidate = re.split(r"(?:还是|沿用|继续|并且|并|然后|再回答|回答一遍|先给结论|再给)", candidate, maxsplit=1)[0].strip()
    return candidate.strip("：: ")


def _locate_replacement_slot(reference_text: str, previous_entities: Sequence[dict[str, Any]]) -> int | None:
    text = _coerce_text(reference_text)
    if not text or not previous_entities:
        return None
    for token, index in _REPLACEMENT_SLOT_HINTS:
        if token in text and index < len(previous_entities):
            return index
    for index, entity in enumerate(previous_entities):
        canonical_id = _coerce_text(entity.get("canonical_id"))
        display_name = _coerce_text(entity.get("display_name"))
        if display_name and display_name in text:
            return index
        if canonical_id and canonical_id in text:
            return index
    return None


def _detect_replacement_instruction(
    current_user_message: str,
    previous_entities: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    text = _coerce_text(current_user_message)
    if not text or not previous_entities or not _REPLACEMENT_VERB_RE.search(text):
        return None

    slot_match = re.search(
        r"(?P<slot>第一家公司|第1家公司|第一家|第一只|第一个标的|前者|第二家公司|第2家公司|第二家|第二只|第二个标的|后者)"
        r"(?:[^，。,；;]{0,8})?"
        r"(?P<verb>替换成|换成|改成|换为|改为)"
        r"(?P<target>[^，。,；;]{1,24})",
        text,
    )
    if slot_match:
        slot_index = _locate_replacement_slot(slot_match.group("slot"), previous_entities)
        target_text = _clean_replacement_target_text(slot_match.group("target"))
        if slot_index is not None and target_text:
            return {"slot_index": slot_index, "target_text": target_text}

    named_match = re.search(
        r"把(?P<source>[^，。,；;]{1,24}?)"
        r"(?P<verb>替换成|换成|改成|换为|改为)"
        r"(?P<target>[^，。,；;]{1,24})",
        text,
    )
    if named_match:
        slot_index = _locate_replacement_slot(named_match.group("source"), previous_entities)
        target_text = _clean_replacement_target_text(named_match.group("target"))
        if slot_index is not None and target_text:
            return {"slot_index": slot_index, "target_text": target_text}
    return None


def _looks_like_additive_followup(text: str) -> bool:
    clean = _coerce_text(text)
    if not clean:
        return False
    return any(token in clean for token in _FOLLOWUP_REFERENCE_HINTS) and any(token in clean for token in _COMPARE_HINTS)


def _looks_like_reference_followup(text: str) -> bool:
    clean = _coerce_text(text)
    if not clean:
        return False
    return any(token in clean for token in _FOLLOWUP_REFERENCE_HINTS)


def _pick_distinct_entity(
    candidates: Sequence[dict[str, Any]],
    *,
    avoid_entity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for entity in candidates:
        if not isinstance(entity, dict):
            continue
        if avoid_entity is not None and _same_entity(entity, avoid_entity):
            continue
        return _deepcopy_jsonable(entity)
    return None


async def _resolve_hot_active_entities(
    *,
    current_user_message: str,
    recent_user_messages: Sequence[str],
    previous_payload: dict[str, Any] | None,
    candidate_entities: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    previous_entities = _normalize_active_entities(previous_payload or {})
    current_entities = await _extract_entity_candidates(current_user_message)
    normalized_candidates = _normalize_active_entities({"active_entities": list(candidate_entities or [])})

    replacement = _detect_replacement_instruction(current_user_message, previous_entities)
    if replacement:
        slot_index = int(replacement["slot_index"])
        base_entities = [_deepcopy_jsonable(item) for item in previous_entities]
        target_candidates = await _extract_entity_candidates(replacement["target_text"])
        old_entity = base_entities[slot_index] if slot_index < len(base_entities) else None
        replacement_entity = _pick_distinct_entity(target_candidates, avoid_entity=old_entity)
        if replacement_entity is None:
            replacement_entity = _pick_distinct_entity(current_entities, avoid_entity=old_entity)
        if replacement_entity is None:
            replacement_entity = _pick_distinct_entity(normalized_candidates, avoid_entity=old_entity)
        if replacement_entity is not None:
            if slot_index < len(base_entities):
                base_entities[slot_index] = replacement_entity
            else:
                base_entities.append(replacement_entity)
            return _normalize_active_entities({"active_entities": base_entities})

    if previous_entities and _looks_like_additive_followup(current_user_message):
        anchor_entities = [_deepcopy_jsonable(previous_entities[0])]
        additive_candidates = current_entities or normalized_candidates
        extras = [entity for entity in additive_candidates if not any(_same_entity(entity, anchor) for anchor in anchor_entities)]
        if extras:
            return _normalize_active_entities({"active_entities": anchor_entities + extras})

    if current_entities:
        return _normalize_active_entities({"active_entities": current_entities})

    if previous_entities and _looks_like_reference_followup(current_user_message):
        return previous_entities

    if normalized_candidates:
        return normalized_candidates

    if _looks_like_reference_followup(current_user_message):
        recent_text = "\n".join(_coerce_text(item) for item in recent_user_messages if _coerce_text(item))
        if recent_text:
            recent_entities = await _extract_entity_candidates(recent_text)
            if recent_entities:
                return _normalize_active_entities({"active_entities": recent_entities})
        return previous_entities
    return []


def _parse_markdown_sections(text: str) -> dict[str, list[str]]:
    sections = {name: [] for name in REQUIRED_SUMMARY_SECTIONS}
    current: str | None = None
    for line in (text or "").splitlines():
        header = _SECTION_RE.match(line.strip())
        if header:
            current = header.group(1)
            continue
        if not current:
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            sections[current].append(bullet.group(1).strip())
        elif line.strip():
            sections[current].append(line.strip())
    return sections


def _parse_markdown_summary_to_payload(text: str) -> dict[str, Any]:
    sections = _parse_markdown_sections(text)
    payload = _empty_summary_payload()
    payload["session_record_summary"] = "；".join(sections["Decisions"])[:800]
    merged_loops = sections["Open TODOs"] + sections["Pending user asks"]
    payload["open_loops"] = _truncate_list(merged_loops, max_items=6, max_len=160)
    payload["constraints"] = _truncate_list(sections["Constraints/Rules"], max_items=8, max_len=120)

    entities: list[dict[str, Any]] = []
    for item in sections["Exact identifiers"]:
        code_match = _STOCK_CODE_RE.search(item)
        if code_match:
            entities.append(
                {
                    "canonical_id": code_match.group(0),
                    "display_name": "",
                    "entity_type": "symbol",
                    "confidence": "high",
                    "status": "active",
                    "source": "legacy_markdown",
                    "evidence_text": item[:120],
                }
            )
    payload["active_entities"] = _normalize_active_entities({"active_entities": entities})
    payload["summary_quality"] = {
        "mode": "normal",
        "source": "legacy_markdown",
        "audit_reasons": [],
    }
    return payload


def _extract_summary_payload(raw_text: str) -> dict[str, Any] | None:
    text = _coerce_text(raw_text)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return _normalize_summary_payload(parsed)
    return _parse_markdown_summary_to_payload(text)


def _collect_exact_identifiers(payload: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    for entity in payload.get("active_entities") or []:
        if not isinstance(entity, dict):
            continue
        canonical_id = _coerce_text(entity.get("canonical_id"))
        display_name = _coerce_text(entity.get("display_name"))
        if canonical_id:
            identifiers.append(canonical_id)
        if display_name and display_name.endswith(("ETF", "指数")):
            identifiers.append(display_name)
    return _truncate_list(identifiers, max_items=8, max_len=60)


def _render_summary_payload_to_markdown(payload: dict[str, Any]) -> str:
    normalized = _normalize_summary_payload(payload)

    decisions: list[str] = []
    if normalized["session_record_summary"]:
        decisions.append(normalized["session_record_summary"])
    if normalized["reply_preference_hint"]:
        decisions.append(f"回答偏好：{normalized['reply_preference_hint']}")
    if normalized["active_entities"]:
        entities_text = "、".join(
            filter(
                None,
                [
                    _coerce_text(entity.get("display_name")) or _coerce_text(entity.get("canonical_id"))
                    for entity in normalized["active_entities"]
                ],
            )
        )
        if entities_text:
            decisions.append(f"当前活跃实体：{entities_text}")
    if not decisions:
        decisions.append("已记录当前会话关键信息，后续回答以最新用户问题为准")

    open_todos = normalized["open_loops"] or ["暂无待补充事项"]
    constraints = normalized["constraints"] or ["暂无额外口径限制"]
    pending_user_asks = normalized["open_loops"] or ["后续以最新用户追问为准"]
    identifiers = _collect_exact_identifiers(normalized) or ["暂无高置信标识"]

    sections = {
        "Decisions": decisions,
        "Open TODOs": open_todos,
        "Constraints/Rules": constraints,
        "Pending user asks": pending_user_asks,
        "Exact identifiers": identifiers,
    }

    lines: list[str] = []
    for section_name in REQUIRED_SUMMARY_SECTIONS:
        lines.append(f"## {section_name}")
        for item in sections[section_name]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _extract_summary_text(raw_text: str) -> str:
    payload = _extract_summary_payload(raw_text)
    if payload is None:
        return ""
    return _render_summary_payload_to_markdown(payload)


def _field_changed(old_value: Any, new_value: Any) -> bool:
    return json.dumps(old_value, sort_keys=True, ensure_ascii=False) != json.dumps(
        new_value,
        sort_keys=True,
        ensure_ascii=False,
    )


def _mark_field_updated(payload: dict[str, Any], field_name: str) -> None:
    payload.setdefault("field_updated_at", {})
    payload["field_updated_at"][field_name] = _utc_now_iso()


def _build_identifier_source_text(
    *,
    source_rows: Sequence[Message] | None = None,
    pending_user_message: str = "",
) -> str:
    parts: list[str] = []
    if pending_user_message.strip():
        parts.append(pending_user_message.strip())
    for row in source_rows or []:
        content = _coerce_text(getattr(row, "content", ""))
        if content:
            parts.append(content)
    return "\n".join(parts)


def _infer_market_from_symbol(symbol: str) -> str:
    upper = _coerce_text(symbol).upper()
    if upper.endswith((".SH", ".SZ", ".BJ")):
        return "CN-A"
    if upper.endswith(".HK"):
        return "HK"
    return ""


def extract_summary_identifiers(
    *,
    source_rows: Sequence[Message] | None = None,
    pending_user_message: str = "",
    previous_payload: dict[str, Any] | None = None,
) -> list[str]:
    source_text = _build_identifier_source_text(
        source_rows=source_rows,
        pending_user_message=pending_user_message,
    )
    matches = list(_STOCK_CODE_RE.findall(source_text))
    matches.extend(_DATE_RE.findall(source_text))
    identifiers = _truncate_list(matches, max_items=8, max_len=60)
    return [item for item in identifiers if item]


async def _extract_entity_candidates(text: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    clean_text = _coerce_text(text)

    for match in _STOCK_CODE_RE.finditer(clean_text):
        canonical_id = _coerce_text(match.group(0)).upper()
        if canonical_id.isdigit() and len(canonical_id) == 6:
            if canonical_id.startswith("6"):
                canonical_id = f"{canonical_id}.SH"
            elif canonical_id.startswith(("0", "3")):
                canonical_id = f"{canonical_id}.SZ"
            elif canonical_id.startswith(("4", "8")):
                canonical_id = f"{canonical_id}.BJ"
        key = (canonical_id, "")
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "canonical_id": canonical_id,
                "display_name": "",
                "entity_type": "symbol",
                "confidence": "high",
                "status": "active",
                "source": "user_explicit",
                "evidence_text": canonical_id,
                "market": _infer_market_from_symbol(canonical_id),
            }
        )

    try:
        from backend.services.entity_resolver import _load_stock_catalog

        catalog = await _load_stock_catalog()
        matches: list[tuple[int, str, str]] = []
        for row in catalog:
            display_name = _coerce_text(row.get("name"))
            canonical_id = _coerce_text(row.get("ts_code")).upper()
            if not display_name or not canonical_id:
                continue
            if display_name in clean_text:
                matches.append((len(display_name), display_name, canonical_id))
        for _, display_name, canonical_id in sorted(matches, key=lambda item: (-item[0], item[1])):
            key = (canonical_id, display_name)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                {
                    "canonical_id": canonical_id,
                    "display_name": display_name,
                    "entity_type": "stock",
                    "confidence": "high",
                    "status": "active",
                    "source": "catalog_match",
                    "evidence_text": display_name[:120],
                    "market": _infer_market_from_symbol(canonical_id),
                }
            )
            if len(entities) >= 6:
                return entities
    except Exception:
        pass

    for match in _CHINESE_NAME_RE.finditer(clean_text):
        display_name = match.group(0).strip()
        if not display_name or len(display_name) < 2:
            continue
        if not display_name.endswith(("ETF", "基金", "指数")):
            continue
        key = ("", display_name)
        if key in seen:
            continue
        seen.add(key)
        entity_type = "fund" if "ETF" in display_name or "基金" in display_name else "index"
        entities.append(
            {
                "canonical_id": "",
                "display_name": display_name,
                "entity_type": entity_type,
                "confidence": "medium",
                "status": "active",
                "source": "user_explicit",
                "evidence_text": display_name[:120],
            }
        )
        if len(entities) >= 6:
            break
    return entities


def _extract_constraints_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    text = _coerce_text(text)
    if not text:
        return []
    patterns = (
        ("只看A股", "当前只看 A 股口径"),
        ("只看a股", "当前只看 A 股口径"),
        ("A股", "回答需明确 A 股口径"),
        ("港股", "如涉及港股需单独说明口径"),
        ("不要技术面", "回答中不展开技术面分析"),
        ("不看技术面", "回答中不展开技术面分析"),
        ("先给结论", "回答先给结论再展开"),
        ("简洁", "回答保持简洁"),
        ("风险优先", "回答优先提示风险"),
        ("先讲风险", "回答优先提示风险"),
    )
    lower_text = text.lower()
    for token, normalized in patterns:
        if token.lower() in lower_text:
            candidates.append(normalized)
    return _truncate_list(candidates, max_items=8, max_len=120)


def _extract_reply_preference_hint(text: str) -> str:
    text = _coerce_text(text)
    if not text:
        return ""
    hints: list[str] = []
    lower_text = text.lower()
    if "简洁" in text or "简单" in text or "concise" in lower_text:
        hints.append("用户偏好简洁回答")
    if "先给结论" in text:
        hints.append("先给结论，再展开")
    if "风险优先" in text or "先讲风险" in text:
        hints.append("风险提示优先")
    if "基本面" in text:
        hints.append("优先从基本面展开")
    return "；".join(_truncate_list(hints, max_items=3, max_len=80))[:220]


def _render_running_summary_from_state(payload: dict[str, Any]) -> str:
    return _render_summary_payload_to_markdown(payload)


def resolve_session_rolling_payload(session: Session | Any) -> dict[str, Any]:
    candidates = [
        getattr(session, "running_summary_state", None),
        _extract_summary_payload(_coerce_text(getattr(session, "running_summary", ""))),
    ]
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            continue
        normalized = _normalize_summary_payload(raw_candidate)
        gate = run_summary_schema_gate(normalized, stage="compaction")
        if gate.get("pass"):
            return gate.get("payload") or _empty_summary_payload()
        logger.warning(
            "event=resolve_session_rolling_payload_invalid session=%s reasons=%s",
            getattr(session, "id", ""),
            ",".join(gate.get("reasons") or []),
        )
    return _empty_summary_payload()


def build_route_summary_slice(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalize_summary_payload(payload)
    route_entities: list[dict[str, Any]] = []
    for entity in normalized.get("active_entities") or []:
        if not isinstance(entity, dict):
            continue
        if _coerce_text(entity.get("status")) == "inactive":
            continue
        route_entities.append(
            {
                "canonical_id": _coerce_text(entity.get("canonical_id")),
                "display_name": _coerce_text(entity.get("display_name")),
                "entity_type": _coerce_text(entity.get("entity_type")) or "symbol",
                "market": _coerce_text(entity.get("market")),
                "confidence": _coerce_text(entity.get("confidence")) or "medium",
                "status": _coerce_text(entity.get("status")) or "active",
                "source": _coerce_text(entity.get("source")) or "unknown",
                "first_seen_message_id": entity.get("first_seen_message_id")
                if isinstance(entity.get("first_seen_message_id"), int)
                else None,
                "last_seen_message_id": entity.get("last_seen_message_id")
                if isinstance(entity.get("last_seen_message_id"), int)
                else None,
            }
        )
        if len(route_entities) >= max(1, int(settings.stm_route_slice_max_entities or 4)):
            break
    return {"active_entities": route_entities}


def build_answer_policy_slice(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalize_summary_payload(payload)
    constraints = _truncate_list(
        normalized.get("constraints") or [],
        max_items=max(1, int(settings.stm_answer_policy_max_constraints or 8)),
        max_len=120,
    )
    return {
        "constraints": constraints,
        "reply_preference_hint": _coerce_text(normalized.get("reply_preference_hint"))[:220],
    }


def format_route_active_entities_context(
    payload: dict[str, Any] | None,
    *,
    max_items: int | None = None,
) -> str:
    route_slice = build_route_summary_slice(payload)
    active_entities = list(route_slice.get("active_entities") or [])
    if max_items is not None:
        active_entities = active_entities[: max(0, max_items)]
    if not active_entities:
        return ""
    lines = ["【Rolling Summary / Route Slice】", "仅供主语补全、指代消解、follow-up 实体继承使用："]
    for entity in active_entities:
        parts = [
            f"display_name={_coerce_text(entity.get('display_name')) or 'unknown'}",
            f"canonical_id={_coerce_text(entity.get('canonical_id')) or 'unknown'}",
            f"entity_type={_coerce_text(entity.get('entity_type')) or 'symbol'}",
            f"market={_coerce_text(entity.get('market')) or 'unknown'}",
            f"confidence={_coerce_text(entity.get('confidence')) or 'medium'}",
            f"status={_coerce_text(entity.get('status')) or 'active'}",
            f"source={_coerce_text(entity.get('source')) or 'unknown'}",
        ]
        lines.append("- " + "; ".join(parts))
    return "\n".join(lines)


def format_answer_policy_context(
    payload: dict[str, Any] | None,
    *,
    max_constraints: int | None = None,
) -> str:
    answer_slice = build_answer_policy_slice(payload)
    constraints = list(answer_slice.get("constraints") or [])
    if max_constraints is not None:
        constraints = constraints[: max(0, max_constraints)]
    reply_preference_hint = _coerce_text(answer_slice.get("reply_preference_hint"))
    if not constraints and not reply_preference_hint:
        return ""
    lines = ["【回答策略上下文】", "以下字段仅用于回答风格、口径与禁项控制："]
    if constraints:
        lines.append("constraints:")
        lines.extend(f"- {item}" for item in constraints)
    if reply_preference_hint:
        lines.append(f"reply_preference_hint: {reply_preference_hint}")
    return "\n".join(lines)


def merge_hot_summary_fields(
    base_payload: dict[str, Any] | None,
    hot_fields_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    merged = _normalize_summary_payload(base_payload)
    hot_payload = _normalize_summary_payload(hot_fields_payload, base_payload=merged)
    updated_fields: list[str] = []
    for field_name in ("reply_preference_hint", "active_entities", "constraints"):
        if _field_changed(merged.get(field_name), hot_payload.get(field_name)):
            merged[field_name] = hot_payload.get(field_name)
            _mark_field_updated(merged, field_name)
            updated_fields.append(field_name)
    merged["summary_quality"] = {
        "mode": "hot_update" if updated_fields else merged.get("summary_quality", {}).get("mode", "normal"),
        "source": hot_payload.get("summary_quality", {}).get("source", "heuristic"),
        "audit_reasons": [],
    }
    return merged, updated_fields


async def apply_route_entity_hot_update(
    session: Session | Any,
    *,
    user_message: str,
    candidate_entities: Sequence[dict[str, Any]] | None,
    source: str = "route_runtime_success",
) -> tuple[dict[str, Any], list[str]]:
    """Merge executor-confirmed entities back into the STM hot state.

    This keeps `running_summary_state.active_entities` aligned with the latest
    successfully resolved route/executor result, instead of waiting for the
    next compaction snapshot to repair stale entities.
    """

    previous_payload = _normalize_summary_payload(
        getattr(session, "running_summary_state", None)
        or _extract_summary_payload(getattr(session, "running_summary", "") or "")
    )
    normalized_candidates = _normalize_active_entities({"active_entities": list(candidate_entities or [])})
    if not normalized_candidates:
        return previous_payload, []

    for entity in normalized_candidates:
        if not _coerce_text(entity.get("source")):
            entity["source"] = source
        if not _coerce_text(entity.get("status")):
            entity["status"] = "active"
        if not _coerce_text(entity.get("confidence")):
            entity["confidence"] = "high"

    resolved_entities = await _resolve_hot_active_entities(
        current_user_message=user_message,
        recent_user_messages=[],
        previous_payload=previous_payload,
        candidate_entities=normalized_candidates,
    )
    if not _field_changed(previous_payload.get("active_entities"), resolved_entities):
        return previous_payload, []

    merged_payload = _normalize_summary_payload(previous_payload)
    merged_payload["active_entities"] = resolved_entities
    _mark_field_updated(merged_payload, "active_entities")
    merged_payload["summary_version"] = int(getattr(session, "summary_version", 0) or 0) + 1
    merged_payload["summary_quality"] = {
        "mode": "hot_update",
        "source": source,
        "audit_reasons": [],
    }
    session.summary_version = merged_payload["summary_version"]
    session.running_summary_state = merged_payload
    session.running_summary = _render_running_summary_from_state(merged_payload)
    session.running_summary_mode = "hot_update"
    return merged_payload, ["active_entities"]


def run_summary_schema_gate(
    payload: dict[str, Any] | None,
    *,
    stage: str,
    field_name: str | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not isinstance(payload, dict):
        return {"pass": False, "reasons": ["invalid_json_object"], "payload": None}

    allowed_fields_by_stage = {
        "hot_update": {
            "schema_version",
            "summary_version",
            "reply_preference_hint",
            "active_entities",
            "constraints",
            "field_updated_at",
            "evidence_refs",
            "source_span",
            "noise_flags",
            "summary_quality",
        },
        "compaction": set(_empty_summary_payload().keys()),
    }
    allowed = allowed_fields_by_stage.get(stage, allowed_fields_by_stage["compaction"])
    for key, value in payload.items():
        if key not in allowed and _has_meaningful_value(value):
            reasons.append("field_not_allowed_in_stage")
            break

    raw_list_fields = ("constraints", "open_loops", "noise_flags")
    for list_field in raw_list_fields:
        raw_value = payload.get(list_field)
        if raw_value is not None and not isinstance(raw_value, list):
            reasons.append("invalid_field_type")

    raw_mapping_fields = ("field_updated_at", "evidence_refs", "source_span", "summary_quality")
    for mapping_field in raw_mapping_fields:
        raw_value = payload.get(mapping_field)
        if raw_value is not None and not isinstance(raw_value, dict):
            reasons.append("invalid_field_type")

    raw_string_fields = ("reply_preference_hint", "session_record_summary")
    for string_field in raw_string_fields:
        raw_value = payload.get(string_field)
        if raw_value is not None and not isinstance(raw_value, str):
            reasons.append("invalid_field_type")

    raw_entities = payload.get("active_entities")
    if raw_entities is not None:
        if not isinstance(raw_entities, list):
            reasons.append("invalid_field_type")
        else:
            for entity in raw_entities:
                if not isinstance(entity, dict):
                    reasons.append("invalid_field_type")
                    break
                if not _coerce_text(entity.get("canonical_id")) and not _coerce_text(entity.get("display_name")):
                    reasons.append("missing_required_field")
                    break

    normalized = _normalize_summary_payload(payload)
    if stage == "compaction":
        required_fields = ("active_entities", "constraints", "open_loops", "session_record_summary")
        if any(field not in payload for field in required_fields):
            reasons.append("missing_required_field")
    if len(normalized["reply_preference_hint"]) > 220:
        reasons.append("item_too_long")
    if len(normalized["constraints"]) > 8 or len(normalized["open_loops"]) > 6:
        reasons.append("too_many_items")
    if stage == "hot_update" and normalized["open_loops"]:
        reasons.append("field_not_allowed_in_stage")
    if field_name:
        expected_fields = {field_name, "schema_version", "summary_version", "summary_quality"}
        expected_fields.update({"field_updated_at", "evidence_refs", "source_span", "noise_flags"})
        extra_keys = [key for key in normalized.keys() if key not in expected_fields and normalized.get(key)]
        if extra_keys:
            reasons.append("cross_field_output_detected")
    return {"pass": not reasons, "reasons": _dedupe_keep_order(reasons), "payload": normalized}


def _refresh_field_updated_at(
    previous_payload: dict[str, Any] | None,
    next_payload: dict[str, Any] | None,
    *,
    fields: Sequence[str],
) -> dict[str, Any]:
    previous = _normalize_summary_payload(previous_payload)
    refreshed = _normalize_summary_payload(next_payload, base_payload=previous)
    previous_updated_at = previous.get("field_updated_at") if isinstance(previous.get("field_updated_at"), dict) else {}
    for field_name in fields:
        if _field_changed(previous.get(field_name), refreshed.get(field_name)):
            _mark_field_updated(refreshed, field_name)
            continue
        old_timestamp = _coerce_text(previous_updated_at.get(field_name))
        if old_timestamp:
            refreshed.setdefault("field_updated_at", {})
            refreshed["field_updated_at"].setdefault(field_name, old_timestamp)
    return refreshed


def _entity_matches_focus(entity: dict[str, Any], focus_text: str, fresh_identifiers: set[str]) -> bool:
    focus = _coerce_text(focus_text)
    canonical_id = _coerce_text(entity.get("canonical_id"))
    display_name = _coerce_text(entity.get("display_name"))
    if canonical_id and canonical_id in fresh_identifiers:
        return True
    if display_name and display_name in focus:
        return True
    if canonical_id and canonical_id in focus:
        return True
    return False


def build_structured_fallback_payload(
    *,
    previous_payload: dict[str, Any] | None,
    source_rows: Sequence[Message],
    latest_focus: str = "",
    fresh_identifiers: Sequence[str] | None = None,
) -> dict[str, Any]:
    base = _normalize_summary_payload(previous_payload)
    payload = _normalize_summary_payload(base_payload=base, payload={})
    source_text = " ".join(_coerce_text(row.content) for row in source_rows if _coerce_text(row.content))
    focus_text = "\n".join(item for item in (latest_focus, source_text) if item).strip()
    if latest_focus and not payload["session_record_summary"]:
        payload["session_record_summary"] = latest_focus[:800]
    elif source_text:
        payload["session_record_summary"] = source_text[:800]

    if not payload["open_loops"]:
        payload["open_loops"] = _truncate_list(
            [latest_focus] if latest_focus else [],
            max_items=3,
            max_len=160,
        )

    fresh_identifier_set = {item for item in (fresh_identifiers or []) if item}
    active_entities = [
        entity
        for entity in list(payload.get("active_entities") or [])
        if isinstance(entity, dict) and _entity_matches_focus(entity, focus_text, fresh_identifier_set)
    ]
    for identifier in fresh_identifiers or []:
        if _STOCK_CODE_RE.fullmatch(identifier):
            active_entities.append(
                {
                    "canonical_id": identifier,
                    "display_name": "",
                    "entity_type": "symbol",
                    "confidence": "high",
                    "status": "active",
                    "source": "fallback_identifier",
                    "evidence_text": identifier,
                }
            )
    payload["active_entities"] = _normalize_active_entities({"active_entities": active_entities})
    payload["summary_quality"] = {
        "mode": "fallback",
        "source": "fallback_builder",
        "audit_reasons": [],
    }
    for field_name in ("active_entities", "open_loops", "session_record_summary"):
        _mark_field_updated(payload, field_name)
    return payload


def build_structured_fallback_summary(
    *,
    previous_payload: dict[str, Any] | None,
    source_rows: Sequence[Message],
    latest_focus: str = "",
    fresh_identifiers: Sequence[str] | None = None,
) -> str:
    payload = build_structured_fallback_payload(
        previous_payload=previous_payload,
        source_rows=source_rows,
        latest_focus=latest_focus,
        fresh_identifiers=fresh_identifiers,
    )
    return _render_summary_payload_to_markdown(payload)


def _build_prompt_active_entities(current_user_message: str, recent_user_messages: Sequence[str]) -> str:
    recent_text = "\n".join(f"- {item}" for item in recent_user_messages if item)
    return (
        "任务目标：抽取当前仍 active 的讨论实体。\n"
        "输入来源与优先级：当前用户消息 > 最近用户消息 > 历史字段。\n"
        "Do：只保留当前继续回答仍需要的标的/主题；如果用户明确说“把第二家公司换成 X / 把 A 换成 B”，必须按替换理解并删除被替换实体；如果用户说“把它和招行放一起”，要继承上一题主实体再补入新实体。\n"
        "Don't：禁止把数字、百分比、日期误识别为实体。\n"
        "输出 schema：JSON object，字段仅包含 active_entities，且每个元素至少包含 canonical_id 或 display_name。\n"
        "正例：{\"active_entities\": [{\"canonical_id\": \"688981.SH\", \"display_name\": \"中芯国际\", \"entity_type\": \"stock\", \"confidence\": \"high\", \"status\": \"active\", \"source\": \"user_explicit\"}]}\n"
        "正例：{\"active_entities\": [{\"canonical_id\": \"300750.SZ\", \"display_name\": \"宁德时代\"}, {\"canonical_id\": \"300274.SZ\", \"display_name\": \"阳光电源\"}]}  # 当前消息是“把第二家公司换成阳光电源”\n"
        "反例：{\"active_entities\": [\"688981.SH\", \"2025-03-31\"]}  # 把日期或裸字符串当实体\n\n"
        f"当前用户消息：{current_user_message}\n"
        f"最近用户消息：\n{recent_text}"
    )


def _build_prompt_constraints(current_user_message: str, recent_user_messages: Sequence[str]) -> str:
    recent_text = "\n".join(f"- {item}" for item in recent_user_messages if item)
    return (
        "任务目标：提炼用户明确提出的回答约束。\n"
        "输入来源与优先级：当前用户消息 > 最近用户消息 > 历史字段。\n"
        "Do：仅保留市场范围、禁项、风格限制。\n"
        "Don't：禁止输出模型建议或空泛常识。\n"
        "输出 schema：JSON object，字段仅包含 constraints，值为字符串数组。\n"
        "正例：{\"constraints\": [\"当前只看 A 股口径\", \"回答中不展开技术面分析\"]}\n"
        "反例：{\"constraints\": \"建议关注半导体板块\"}  # 不能输出建议，也不能输出非数组\n\n"
        f"当前用户消息：{current_user_message}\n"
        f"最近用户消息：\n{recent_text}"
    )


def _build_prompt_reply_preference_hint(current_user_message: str, recent_user_messages: Sequence[str]) -> str:
    recent_text = "\n".join(f"- {item}" for item in recent_user_messages if item)
    return (
        "任务目标：提炼用户明确表达的回答偏好。\n"
        "输入来源与优先级：当前用户消息 > 最近用户消息 > 历史字段。\n"
        "Do：只保留先给结论/简洁/风险优先等明确偏好。\n"
        "Don't：禁止猜测用户偏好。\n"
        "输出 schema：JSON object，字段仅包含 reply_preference_hint，值为字符串。\n"
        "正例：{\"reply_preference_hint\": \"先给结论，再展开；风险提示优先\"}\n"
        "反例：{\"reply_preference_hint\": [\"你应该长期持有\"]}  # 不能输出数组，也不能夹带投资建议\n\n"
        f"当前用户消息：{current_user_message}\n"
        f"最近用户消息：\n{recent_text}"
    )


async def extract_hot_summary_fields(
    *,
    current_user_message: str,
    recent_user_messages: Sequence[str],
    previous_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    text = "\n".join([_coerce_text(current_user_message), *[_coerce_text(item) for item in recent_user_messages]])
    payload = _empty_hot_fields_payload()
    payload["active_entities"] = await _resolve_hot_active_entities(
        current_user_message=current_user_message,
        recent_user_messages=recent_user_messages,
        previous_payload=previous_payload,
    )
    payload["constraints"] = _extract_constraints_from_text(text)
    payload["reply_preference_hint"] = _extract_reply_preference_hint(text)
    return payload


async def _call_hot_field_extractor(
    *,
    llm: Any,
    prompt: str,
    field_name: str,
) -> tuple[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    response = await llm.ainvoke(
        [
            SystemMessage(content="你是 rolling summary 热更新字段抽取器。只输出合法 JSON object。"),
            HumanMessage(content=prompt),
        ]
    )
    response_text = _coerce_text(getattr(response, "content", ""))
    parsed = json.loads(response_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"hot field {field_name} returned invalid object")
    gate = run_summary_schema_gate(parsed, stage="hot_update", field_name=field_name)
    if not gate["pass"]:
        raise ValueError(f"hot field {field_name} failed gate: {','.join(gate['reasons'])}")
    return field_name, gate["payload"].get(field_name)


async def extract_hot_summary_fields_parallel(
    *,
    current_user_message: str,
    recent_user_messages: Sequence[str],
    previous_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    heuristic_payload = await extract_hot_summary_fields(
        current_user_message=current_user_message,
        recent_user_messages=recent_user_messages,
        previous_payload=previous_payload,
    )
    try:
        llm = _build_hot_update_llm()
        field_results = await asyncio.gather(
            _call_hot_field_extractor(
                llm=llm,
                prompt=_build_prompt_active_entities(current_user_message, recent_user_messages),
                field_name="active_entities",
            ),
            _call_hot_field_extractor(
                llm=llm,
                prompt=_build_prompt_constraints(current_user_message, recent_user_messages),
                field_name="constraints",
            ),
            _call_hot_field_extractor(
                llm=llm,
                prompt=_build_prompt_reply_preference_hint(current_user_message, recent_user_messages),
                field_name="reply_preference_hint",
            ),
            return_exceptions=True,
        )
    except Exception:
        field_results = []

    merged = _normalize_summary_payload(heuristic_payload)
    llm_overrides = 0
    for item in field_results:
        if isinstance(item, Exception):
            continue
        field_name, value = item
        merged[field_name] = value
        llm_overrides += 1
    merged["active_entities"] = await _resolve_hot_active_entities(
        current_user_message=current_user_message,
        recent_user_messages=recent_user_messages,
        previous_payload=previous_payload,
        candidate_entities=merged.get("active_entities") or [],
    )
    merged["summary_quality"] = {
        "mode": "hot_update",
        "source": "llm_hot_update" if llm_overrides else "heuristic",
        "audit_reasons": [],
    }
    return merged


async def commit_hot_summary_fields_with_cas(
    db: AsyncSession,
    session: Session,
    *,
    pending_user_message: str,
    recent_user_messages: Sequence[str],
) -> tuple[dict[str, Any], list[str]]:
    previous_payload = _normalize_summary_payload(
        session.running_summary_state or _extract_summary_payload(session.running_summary or "")
    )
    hot_payload = await extract_hot_summary_fields_parallel(
        current_user_message=pending_user_message,
        recent_user_messages=recent_user_messages,
        previous_payload=previous_payload,
    )
    gate = run_summary_schema_gate(hot_payload, stage="hot_update")
    if not gate["pass"]:
        logger.info(
            "event=hot_update_skipped session=%s reasons=%s",
            session.id,
            ",".join(gate["reasons"]),
        )
        return previous_payload, []

    merged_payload, updated_fields = merge_hot_summary_fields(previous_payload, gate["payload"])
    if not updated_fields:
        return previous_payload, []

    merged_payload["summary_version"] = int(session.summary_version or 0) + 1
    merged_payload["summary_quality"] = {
        "mode": "hot_update",
        "source": hot_payload.get("summary_quality", {}).get("source", "heuristic"),
        "audit_reasons": [],
    }
    session.summary_version = merged_payload["summary_version"]
    session.running_summary_state = merged_payload
    session.running_summary = _render_running_summary_from_state(merged_payload)
    session.running_summary_mode = "hot_update"
    await db.flush()
    await db.commit()
    await db.refresh(session)
    logger.info(
        "event=running_summary_state_updated session=%s summary_version=%s updated_fields=%s",
        session.id,
        session.summary_version,
        ",".join(updated_fields),
    )
    return merged_payload, updated_fields


def _summarize_source_rows_for_prompt(source_rows: Sequence[Message]) -> str:
    lines: list[str] = []
    for row in source_rows:
        role = _coerce_text(getattr(row, "role", "")) or "unknown"
        content = _coerce_text(getattr(row, "content", ""))
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_chunk_prompt(
    *,
    source_rows: Sequence[Message],
    previous_payload: dict[str, Any],
    hot_fields_payload: dict[str, Any],
) -> str:
    transcript = _summarize_source_rows_for_prompt(source_rows)
    return (
        "你是金融问答 rolling summary 压缩器。请根据给定对话生成结构化 JSON object。\n"
        "要求：\n"
        "1. reply_preference_hint / active_entities / constraints 仅允许轻度清洗，不要推翻用户刚表达的信息。\n"
        "2. open_loops 只保留仍未完成、后续可能继续追问的事项。\n"
        "3. session_record_summary 只写本段对话发生了什么，不要写待办标题。\n"
        "4. 如果旧 identifiers 与当前焦点无关，不要带入。\n"
        "5. 相对时间改写成绝对时间。\n"
        "6. 不要把 Markdown section 标题写进字段值。\n"
        "输出 schema：{schema_version, summary_version, reply_preference_hint, active_entities, constraints, open_loops, session_record_summary, field_updated_at, evidence_refs, source_span, noise_flags, summary_quality}\n"
        "反例：{\"session_record_summary\": \"## Decisions\\n- ...\", \"open_loops\": [\"已完成的事项\"]}\n\n"
        f"当前热更新字段：{json.dumps(hot_fields_payload, ensure_ascii=False)}\n"
        f"上一版摘要：{json.dumps(previous_payload, ensure_ascii=False)}\n"
        f"待压缩对话：\n{transcript}\n"
    )


def _build_prompt_open_loops(source_rows: Sequence[Message]) -> str:
    return (
        "任务目标：只提炼未回答问题和后续高概率继续追问的事项。\n"
        "输出 JSON object，字段仅包含 open_loops。\n\n"
        f"{_summarize_source_rows_for_prompt(source_rows)}"
    )


def _build_prompt_session_record_summary(source_rows: Sequence[Message]) -> str:
    return (
        "任务目标：按时间顺序总结本段对话，覆盖用户问了什么、助手答了什么。\n"
        "输出 JSON object，字段仅包含 session_record_summary。\n\n"
        f"{_summarize_source_rows_for_prompt(source_rows)}"
    )


def _build_summary_llm():
    from langchain_openai import ChatOpenAI

    model = _coerce_text(settings.stm_compaction_model) or _coerce_text(settings.openai_compatible_model)
    api_key = _coerce_text(settings.stm_compaction_api_key) or _coerce_text(settings.openai_compatible_api_key)
    base_url = _coerce_text(settings.stm_compaction_base_url) or _coerce_text(settings.openai_compatible_base_url)
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=1200,
    )


def _build_hot_update_llm():
    from langchain_openai import ChatOpenAI

    model = _coerce_text(settings.stm_hot_update_model) or _coerce_text(settings.openai_compatible_model)
    api_key = _coerce_text(settings.stm_hot_update_api_key) or _coerce_text(settings.openai_compatible_api_key)
    base_url = _coerce_text(settings.stm_hot_update_base_url) or _coerce_text(settings.openai_compatible_base_url)
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=400,
    )


async def _call_summary_model(
    *,
    source_rows: Sequence[Message],
    previous_payload: dict[str, Any],
    hot_fields_payload: dict[str, Any],
) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _build_summary_llm()
    prompt = _build_chunk_prompt(
        source_rows=source_rows,
        previous_payload=previous_payload,
        hot_fields_payload=hot_fields_payload,
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content="你是金融问答总结器。优先输出合法 JSON object。"),
            HumanMessage(content=prompt),
        ]
    )
    response_text = _coerce_text(getattr(response, "content", ""))
    try:
        parsed = json.loads(response_text)
    except Exception as exc:
        raise ValueError("summary model returned non_json_output") from exc
    if not isinstance(parsed, dict):
        raise ValueError("summary model returned invalid_json_object")
    return _normalize_summary_payload(parsed)


async def _write_summary_audit_log(
    db: AsyncSession,
    *,
    session_id: str,
    task_kind: str,
    status: str,
    trigger: str | None,
    reason: str,
    source_rows: Sequence[Message],
    summary_id: int | None = None,
    summary_version: int | None = None,
    summary_mode: str | None = None,
    audit_reasons: Sequence[str] | None = None,
    model_name: str | None = None,
    counting_mode: str | None = None,
) -> None:
    input_text = _summarize_source_rows_for_prompt(source_rows)
    input_tokens, _ = count_text_tokens(input_text)
    row = SummaryAuditLog(
        session_id=session_id,
        task_kind=task_kind,
        status=status,
        trigger=trigger,
        reason=reason,
        source_start_message_id=(source_rows[0].id if source_rows else None),
        source_end_message_id=(source_rows[-1].id if source_rows else None),
        source_start_created_at=(source_rows[0].created_at if source_rows else None),
        source_end_created_at=(source_rows[-1].created_at if source_rows else None),
        input_message_count=len(source_rows),
        input_token_estimate=input_tokens,
        output_summary_id=summary_id,
        output_summary_version=summary_version,
        output_summary_mode=summary_mode,
        audit_reasons_json=list(audit_reasons or []),
        model_name=model_name,
        counting_mode=counting_mode,
    )
    db.add(row)
    await db.flush()


async def try_commit_summary_with_cas(
    db: AsyncSession,
    session_id: str,
    *,
    base_summary_version: int,
    new_summary: str,
    compressed_message_ids: Sequence[int],
    trigger: str,
    total_message_count: int,
    summary_payload: dict[str, Any] | None = None,
    summary_mode: str = "normal",
    source_rows: Sequence[Message] | None = None,
) -> bool:
    session = await db.get(Session, session_id)
    if session is None:
        return False
    if int(session.summary_version or 0) != int(base_summary_version):
        return False

    payload = _normalize_summary_payload(summary_payload or _extract_summary_payload(new_summary))
    payload["summary_version"] = int(base_summary_version) + 1
    payload["summary_quality"] = payload.get("summary_quality") or {}
    payload["summary_quality"]["mode"] = summary_mode

    session.summary_version = payload["summary_version"]
    session.running_summary = new_summary
    session.running_summary_state = payload
    session.running_summary_mode = "compaction_fallback" if summary_mode == "fallback" else "compaction"
    session.last_compress_at = _utc_now()
    session.compression_status = "idle"

    if compressed_message_ids:
        result = await db.execute(
            select(Message).where(
                Message.session_id == session_id,
                Message.id.in_(list(compressed_message_ids)),
            )
        )
        for message in result.scalars().all():
            message.is_compressed = True

    snapshot = SessionSummary(
        session_id=session_id,
        summary=new_summary,
        summary_payload=payload,
        summary_mode=summary_mode,
        summary_trigger=trigger,
        compressed_message_count=len(list(compressed_message_ids)),
        total_message_count=int(total_message_count or 0),
    )
    db.add(snapshot)
    await db.flush()

    await _write_summary_audit_log(
        db,
        session_id=session_id,
        task_kind="compaction",
        status="success",
        trigger=trigger,
        reason="ok",
        source_rows=list(source_rows or []),
        summary_id=snapshot.id,
        summary_version=payload["summary_version"],
        summary_mode=summary_mode,
        audit_reasons=payload.get("summary_quality", {}).get("audit_reasons") or [],
        model_name=_coerce_text(settings.stm_compaction_model) or _coerce_text(settings.openai_compatible_model),
    )
    await db.commit()
    return True


def _extract_latest_user_message_text(source_rows: Sequence[Message]) -> str:
    for row in reversed(source_rows):
        if _coerce_text(getattr(row, "role", "")) == "user":
            return _coerce_text(getattr(row, "content", ""))
    return ""


def _estimate_prompt_overhead(*, system_prompt_text: str, memory_prompt_text: str, pending_user_message: str) -> int:
    total = 0
    for chunk in (system_prompt_text, memory_prompt_text, pending_user_message):
        total += count_text_tokens(chunk or "")[0]
    return total


def should_run_preflight_summary_compaction(
    session: Session,
    pending_user_message: str,
    *,
    system_prompt_text: str = "",
    memory_prompt_text: str = "",
) -> PreflightSummaryDecision:
    threshold_tokens = max(
        0,
        int(settings.chat_context_window_tokens or 0)
        - int(settings.stm_summary_reserve_tokens_floor or 0)
        - int(settings.stm_summary_soft_threshold_tokens or 0),
    )
    pending_message_tokens = count_message_tokens("user", pending_user_message or "")[0]
    prompt_overhead_tokens = _estimate_prompt_overhead(
        system_prompt_text=system_prompt_text,
        memory_prompt_text=memory_prompt_text,
        pending_user_message=pending_user_message,
    )
    projected_tokens = int(session.context_token_count or 0) + pending_message_tokens + prompt_overhead_tokens
    should_compact = projected_tokens >= threshold_tokens > 0
    return PreflightSummaryDecision(
        should_compact=should_compact,
        threshold_tokens=threshold_tokens,
        projected_tokens=projected_tokens,
        pending_message_tokens=pending_message_tokens,
        prompt_overhead_tokens=prompt_overhead_tokens,
        reason="threshold_reached" if should_compact else "threshold_not_reached",
    )


async def run_summary_compaction(
    db: AsyncSession,
    session: Session,
    *,
    source_rows: Sequence[Message],
    cutoff_message_id: int | None,
    trigger: str,
) -> SummaryCompactionResult:
    del cutoff_message_id
    rows = list(source_rows or [])
    if not rows:
        return SummaryCompactionResult(compacted=False, reason="no_source_rows")

    base_version = int(session.summary_version or 0)
    previous_payload = _normalize_summary_payload(
        session.running_summary_state or _extract_summary_payload(session.running_summary or "")
    )
    hot_fields_payload = _normalize_summary_payload(previous_payload)
    current_focus = _extract_latest_user_message_text(rows)
    identifiers = extract_summary_identifiers(source_rows=rows, previous_payload=previous_payload)

    final_strategy = "model_summary"
    schema_reasons: list[str] = []
    try:
        candidate_payload = await _call_summary_model(
            source_rows=rows,
            previous_payload=previous_payload,
            hot_fields_payload=hot_fields_payload,
        )
        candidate_payload["summary_quality"] = {
            "mode": "normal",
            "source": "model_summary",
            "audit_reasons": [],
        }
        gate = run_summary_schema_gate(candidate_payload, stage="compaction")
        if gate["pass"]:
            payload = gate["payload"]
        else:
            schema_reasons = list(gate["reasons"])
            final_strategy = "reuse_last_good_on_schema_fail"
            payload = _normalize_summary_payload(previous_payload)
            payload["summary_quality"] = {
                "mode": "normal",
                "source": final_strategy,
                "audit_reasons": schema_reasons,
            }
    except Exception as exc:
        logger.warning(
            "event=summary_model_error session=%s trigger=%s error=%s",
            session.id,
            trigger,
            exc,
        )
        final_strategy = "fallback_on_error"
        payload = build_structured_fallback_payload(
            previous_payload=previous_payload,
            source_rows=rows,
            latest_focus=current_focus,
            fresh_identifiers=identifiers,
        )
        payload["summary_quality"]["audit_reasons"] = ["model_error"]

    payload = _refresh_field_updated_at(
        previous_payload,
        _normalize_summary_payload(payload, base_payload=previous_payload),
        fields=(
            "reply_preference_hint",
            "active_entities",
            "constraints",
            "open_loops",
            "session_record_summary",
        ),
    )
    payload["source_span"] = {
        "start_message_id": rows[0].id,
        "end_message_id": rows[-1].id,
    }
    payload["summary_quality"]["mode"] = "fallback" if final_strategy == "fallback_on_error" else "normal"
    payload["summary_quality"]["source"] = final_strategy
    payload["summary_version"] = base_version + 1
    summary_text = _render_summary_payload_to_markdown(payload)

    committed = await try_commit_summary_with_cas(
        db,
        session.id,
        base_summary_version=base_version,
        new_summary=summary_text,
        compressed_message_ids=[int(row.id) for row in rows],
        trigger=trigger,
        total_message_count=len(rows),
        summary_payload=payload,
        summary_mode="fallback" if final_strategy == "fallback_on_error" else "normal",
        source_rows=rows,
    )
    if not committed:
        await db.rollback()
        return SummaryCompactionResult(
            compacted=False,
            reason="cas_conflict",
            summary_text=summary_text,
            summary_payload=payload,
            compressed_message_count=len(rows),
            total_message_count=len(rows),
            final_strategy=final_strategy,
            schema_reasons=schema_reasons,
        )

    await db.refresh(session)
    summary_id: int | None = None
    snapshot_result = await db.execute(
        select(SessionSummary)
        .where(SessionSummary.session_id == session.id)
        .order_by(SessionSummary.id.desc())
        .limit(1)
    )
    snapshot = snapshot_result.scalar_one_or_none()
    if snapshot is not None:
        summary_id = int(snapshot.id)

    logger.info(
        "event=summary_snapshot session=%s trigger=%s summary_version=%s strategy=%s summary_id=%s",
        session.id,
        trigger,
        session.summary_version,
        final_strategy,
        summary_id,
    )
    return SummaryCompactionResult(
        compacted=True,
        reason="ok",
        summary_text=summary_text,
        summary_payload=payload,
        summary_id=summary_id,
        summary_mode="fallback" if final_strategy == "fallback_on_error" else "normal",
        summary_trigger=trigger,
        compressed_message_count=len(rows),
        total_message_count=len(rows),
        final_strategy=final_strategy,
        summary_version_after=int(session.summary_version or 0),
        schema_reasons=schema_reasons,
    )


async def maybe_run_preflight_summary_compaction(
    db: AsyncSession,
    session: Session,
    *,
    pending_user_message: str,
    system_prompt_text: str = "",
    memory_prompt_text: str = "",
    exclude_message_ids: set[int] | None = None,
    trigger: str = "preflight_budget_sync_chat",
    stream_status_emitter: Any | None = None,
) -> SummaryCompactionResult:
    del stream_status_emitter
    recent_user_result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(max(1, int(settings.stm_hot_recent_user_window or 1))),
    )
    recent_user_messages = [_coerce_text(msg.content) for msg in recent_user_result.scalars().all()]
    _, updated_fields = await commit_hot_summary_fields_with_cas(
        db,
        session,
        pending_user_message=pending_user_message,
        recent_user_messages=recent_user_messages,
    )

    await refresh_session_context_metrics(db, session)
    decision = should_run_preflight_summary_compaction(
        session,
        pending_user_message,
        system_prompt_text=system_prompt_text,
        memory_prompt_text=memory_prompt_text,
    )
    logger.info(
        "event=preflight_decision session=%s should_compact=%s threshold_tokens=%s projected_tokens=%s",
        session.id,
        decision.should_compact,
        decision.threshold_tokens,
        decision.projected_tokens,
    )
    if not decision.should_compact:
        rows: list[Message] = []
        await _write_summary_audit_log(
            db,
            session_id=session.id,
            task_kind="preflight",
            status="skipped",
            trigger=trigger,
            reason=decision.reason,
            source_rows=rows,
            audit_reasons=[decision.reason],
        )
        await db.commit()
        return SummaryCompactionResult(
            compacted=False,
            reason=decision.reason,
            final_strategy="hot_update_only",
            summary_text=session.running_summary,
            summary_payload=session.running_summary_state,
            summary_version_after=int(session.summary_version or 0),
            hot_updated_fields=updated_fields,
        )

    exclude_ids = {int(item) for item in (exclude_message_ids or set())}
    result = await db.execute(
        select(Message)
        .where(
            Message.session_id == session.id,
            Message.is_compressed == False,  # noqa: E712
        )
        .order_by(Message.created_at.asc())
    )
    uncompressed = [row for row in result.scalars().all() if int(row.id) not in exclude_ids]
    keep_recent = max(1, int(settings.stm_keep_recent or 1))
    if len(uncompressed) > keep_recent:
        source_rows = uncompressed[:-keep_recent]
    else:
        source_rows = uncompressed[:-1]
    if not source_rows:
        logger.info("event=preflight_result session=%s compacted=false reason=no_source_rows", session.id)
        await _write_summary_audit_log(
            db,
            session_id=session.id,
            task_kind="preflight",
            status="skipped",
            trigger=trigger,
            reason="no_preflight_source_rows",
            source_rows=[],
            audit_reasons=["no_preflight_source_rows"],
        )
        await db.commit()
        return SummaryCompactionResult(
            compacted=False,
            reason="no_preflight_source_rows",
            final_strategy="hot_update_only",
            summary_text=session.running_summary,
            summary_payload=session.running_summary_state,
            summary_version_after=int(session.summary_version or 0),
            hot_updated_fields=updated_fields,
        )

    result = await run_summary_compaction(
        db=db,
        session=session,
        source_rows=source_rows,
        cutoff_message_id=source_rows[-1].id if source_rows else None,
        trigger=trigger,
    )
    result.hot_updated_fields = updated_fields
    logger.info(
        "event=preflight_result session=%s compacted=%s reason=%s strategy=%s",
        session.id,
        result.compacted,
        result.reason,
        result.final_strategy,
    )
    return result
