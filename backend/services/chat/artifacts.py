import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Session
from backend.services.chat.constants import _unique_strings


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


def _profile_to_summary(profile: dict) -> str:
    if not profile:
        return ""

    summary_lines: list[str] = []
    for label, key in (
        ("风险偏好", "risk_level"),
        ("投资周期", "investment_horizon"),
        ("回答偏好", "response_pref"),
    ):
        value = profile.get(key)
        if value:
            summary_lines.append(f"{label}: {value}")

    sectors = profile.get("sectors") or []
    if sectors:
        summary_lines.append(f"关注板块: {', '.join(str(item) for item in sectors)}")

    return "\n".join(summary_lines)


def _profile_to_route_summary(profile: dict) -> str:
    if not profile:
        return ""

    summary_lines: list[str] = []
    for label, key in (
        ("风险偏好", "risk_level"),
        ("投资周期", "investment_horizon"),
        ("回答偏好", "response_pref"),
    ):
        value = profile.get(key)
        if value:
            summary_lines.append(f"{label}: {value}")

    return "\n".join(summary_lines)


def _trace_query_summary(text: str, limit: int = 120) -> str:
    summary = (text or "").strip().replace("\n", " ")
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3] + "..."


def _trace_root_metrics(skill_trace: dict | None) -> dict[str, object]:
    trace = skill_trace or {}
    executor = trace.get("executor") if isinstance(trace.get("executor"), dict) else {}
    metrics = {
        "route_confidence": round(float(trace.get("confidence") or 0.0), 4),
        "evidence_ok": bool(executor.get("evidence_ok", False)),
        "tool_batch_size": int(executor.get("tool_batch_size") or 0),
        "tool_failure_rate": float(executor.get("tool_failure_rate") or 0.0),
        "p95_latency": float(executor.get("p95_latency") or 0.0),
        "degrade_stage": str(executor.get("degrade_stage") or "none"),
        "policy_violation_count": int(executor.get("policy_violation_count") or 0),
    }
    return metrics


def _trace_root_payload(
    *,
    final_status: str,
    selected_skill_family: str,
    selected_skill: str,
    skill_name: str | None,
    analysis_mode: str,
    execution_policy: str,
    skill_trace: dict | None,
) -> dict[str, object]:
    executor = (skill_trace or {}).get("executor") if isinstance((skill_trace or {}).get("executor"), dict) else {}
    return {
        "final_status": final_status,
        "reply_mode": executor.get("reply_mode") or ("fallback" if selected_skill == "fallback" else "skill"),
        "final_selected_skill_family": selected_skill_family,
        "final_selected_skill": selected_skill,
        "final_skill_name": skill_name,
        "selected_skill_family": selected_skill_family,
        "selected_skill": selected_skill,
        "skill_name": skill_name,
        "analysis_mode": analysis_mode,
        "execution_policy": execution_policy,
        "degrade_stage_final": executor.get("degrade_stage"),
        "evidence_ok_final": executor.get("evidence_ok"),
        "claim_count_final": len(executor.get("claims") or []),
    }


def _trace_root_refs(skill_trace: dict | None) -> dict[str, object]:
    executor = (skill_trace or {}).get("executor") if isinstance((skill_trace or {}).get("executor"), dict) else {}
    return {
        "prompt_ref": executor.get("prompt_ref"),
        "reply_ref": executor.get("reply_ref"),
        "claim_ref": executor.get("claim_ref"),
        "payload_refs": executor.get("payload_refs") or [],
    }


def _route_summary_skill_label(
    *,
    skill_contract: str,
    skill_name: str | None,
    selected_skill_family: str,
    selected_skill: str,
) -> str:
    """用户可见技能名：优先 SOP 注册表 official_name，其次 skill id，避免只显示 tushare-data。"""
    sid = (skill_contract or (skill_name or "")).strip()
    if sid:
        meta = _chat_service_facade().get_skill_registry().get_skill(sid)
        if meta:
            on = (meta.official_name or "").strip()
            if on and on != sid:
                return on
        return sid
    if selected_skill == "fallback":
        return "普通对话"
    if selected_skill_family == "tushare-data" or selected_skill == "tushare-data":
        return "实时数据（Tushare）"
    return selected_skill_family or selected_skill


def _build_route_summary(skill_trace: dict | None) -> dict | None:
    trace = skill_trace or {}
    if not trace:
        return None
    executor = trace.get("executor") if isinstance(trace.get("executor"), dict) else {}
    accepted_evidences = executor.get("accepted_evidences") if isinstance(executor.get("accepted_evidences"), list) else []
    evidence_tools = [
        item.get("tool_name")
        for item in accepted_evidences
        if isinstance(item, dict) and item.get("tool_name")
    ]
    attempted_tools = executor.get("prefetched_tool_names") if isinstance(executor.get("prefetched_tool_names"), list) else []
    planned_tools = executor.get("planned_tools") if isinstance(executor.get("planned_tools"), list) else []
    notes = executor.get("missing_evidence_reasons") if isinstance(executor.get("missing_evidence_reasons"), list) else []

    selected_skill_family = str(trace.get("selected_skill_family") or executor.get("selected_skill_family") or "fallback")
    selected_skill = str(trace.get("selected_skill") or executor.get("selected_skill") or selected_skill_family or "fallback")
    if selected_skill_family == "fallback" and selected_skill == "fallback" and executor:
        selected_skill_family = str(executor.get("selected_skill_family") or selected_skill_family)

    route_kind = str(trace.get("route_kind") or executor.get("route_kind") or "")
    grounding_policy = str(trace.get("grounding_policy") or executor.get("grounding_policy") or "")
    claim_policy = str(trace.get("claim_policy") or executor.get("claim_policy") or "")
    skill_contract = str(trace.get("skill_contract") or executor.get("skill_contract") or "")
    failure_code = str(executor.get("failure_code") or "")
    sn = str(trace.get("skill_name") or executor.get("skill_name") or "").strip() or None
    verification = executor.get("verification") if isinstance(executor.get("verification"), dict) else {}
    verification_status = str(verification.get("status") or "")
    evidence_status = "ok" if bool(executor.get("evidence_ok")) else "missing"
    if verification_status == "partial":
        evidence_status = "partial"
    elif verification_status == "insufficient":
        evidence_status = "missing"

    user_facing = {
        "skill_label": _route_summary_skill_label(
            skill_contract=skill_contract,
            skill_name=sn,
            selected_skill_family=selected_skill_family,
            selected_skill=selected_skill,
        ),
        "analysis_mode": str(trace.get("analysis_mode") or executor.get("analysis_mode") or "general_chat"),
        "evidence_status": evidence_status,
        "failure_hint": failure_code if failure_code else "",
    }
    debug = {
        "route_kind": route_kind,
        "grounding_policy": grounding_policy,
        "claim_policy": claim_policy,
        "skill_contract": skill_contract,
        "evidence_tier": str(executor.get("evidence_tier") or ""),
        "evidence_missing_dimensions": list(executor.get("evidence_missing_dimensions") or verification.get("missing_dimensions") or []),
        "evidence_allowed_claim_level": str(executor.get("evidence_allowed_claim_level") or verification.get("allowed_claim_level") or ""),
        "failure_code": failure_code,
    }

    return {
        "selected_skill_family": selected_skill_family or "fallback",
        "selected_skill": selected_skill or "fallback",
        "skill_name": sn,
        "analysis_mode": str(trace.get("analysis_mode") or executor.get("analysis_mode") or "general_chat"),
        "execution_policy": str(trace.get("execution_policy") or executor.get("execution_policy") or "agentic"),
        "reply_mode": str(executor.get("reply_mode") or ("fallback" if selected_skill == "fallback" else "skill")),
        "route_confidence": round(float(trace.get("confidence") or 0.0), 4),
        "used_tools": bool(executor.get("used_tools") or evidence_tools or attempted_tools),
        "evidence_ok": bool(executor.get("evidence_ok")),
        "tools_used": _unique_strings(evidence_tools),
        "tools_attempted": _unique_strings(list(attempted_tools) + list(planned_tools)),
        "notes": _unique_strings(notes, limit=3),
        "route_kind": route_kind,
        "grounding_policy": grounding_policy,
        "claim_policy": claim_policy,
        "skill_contract": skill_contract,
        "failure_code": failure_code,
        "user_facing": user_facing,
        "debug": debug,
        # FIX-3: entity info from executor
        "resolved_company": str(executor.get("resolved_company") or ""),
        "resolved_symbol": str(executor.get("resolved_symbol") or ""),
    }


def _persistable_route_summary(route_summary: dict | None) -> dict | None:
    """Extract the user-facing portion of route_summary for persistence.

    Debug information is deliberately excluded from stored messages
    to keep history payloads lean and avoid leaking internal details.
    """
    if not route_summary:
        return None
    kept_keys = {
        "selected_skill_family", "selected_skill", "skill_name",
        "analysis_mode", "execution_policy", "reply_mode",
        "route_confidence", "used_tools", "evidence_ok",
        "tools_used", "tools_attempted", "notes",
        "user_facing", "resolved_company", "resolved_symbol",
    }
    return {k: v for k, v in route_summary.items() if k in kept_keys}


def _record_route_runtime_with_log(
    *,
    session_id: str,
    user_message: str,
    route_trace: dict | None,
    reply_text: str,
) -> Any | None:
    if not route_trace:
        return None
    chat_service = _chat_service_facade()
    state = chat_service.record_route_runtime_state(
        session_id=session_id,
        user_message=user_message,
        route_trace=route_trace,
        reply_text=reply_text,
    )
    chat_service.logger.info(
        "[chat-route-state] session=%s entity=%s mode=%s tool_status=%s fail_streak=%s followup_dim=%s",
        session_id,
        state.last_active_entity or "",
        state.last_analysis_mode or "",
        state.last_tool_status or "",
        int(state.inherited_fail_streak or 0),
        state.last_followup_dimension or "",
    )
    return state


def _route_trace_to_summary_entities(route_trace: dict | None) -> list[dict[str, Any]]:
    if not isinstance(route_trace, dict):
        return []
    executor = route_trace.get("executor") if isinstance(route_trace.get("executor"), dict) else {}
    if str(route_trace.get("selected_skill") or "") == "fallback":
        return []
    if executor and executor.get("evidence_ok") is False:
        return []

    args = route_trace.get("arguments") if isinstance(route_trace.get("arguments"), dict) else {}
    candidates: list[dict[str, Any]] = []

    def _append_entity(raw: dict[str, Any] | None, *, source: str) -> None:
        if not isinstance(raw, dict):
            return
        canonical_id = str(
            raw.get("canonical_id")
            or raw.get("symbol")
            or raw.get("inherited_entity_id")
            or ""
        ).strip()
        display_name = str(
            raw.get("display_name")
            or raw.get("company_name")
            or raw.get("name")
            or raw.get("inherited_entity")
            or ""
        ).strip()
        entity_type = str(raw.get("entity_type") or raw.get("asset_type") or "stock").strip() or "stock"
        if not canonical_id and not display_name:
            return
        candidate = {
            "canonical_id": canonical_id,
            "display_name": display_name,
            "entity_type": entity_type,
            "status": "active",
            "confidence": "high",
            "source": source,
            "evidence_text": display_name or canonical_id,
        }
        if candidate not in candidates:
            candidates.append(candidate)

    _append_entity(args.get("resolved_entity_hint"), source="resolver_hint")
    for item in list(args.get("entities") or []):
        _append_entity(item, source="route_trace_entities")
    _append_entity(
        {
            "canonical_id": executor.get("resolved_symbol"),
            "display_name": executor.get("resolved_company"),
            "entity_type": "stock",
        },
        source="executor_trace",
    )
    return candidates


async def _apply_route_entities_to_stm_with_log(
    *,
    db: AsyncSession,
    session: Session,
    user_message: str,
    route_trace: dict | None,
) -> list[str]:
    if not settings.enable_stm or not route_trace:
        return []
    candidate_entities = _route_trace_to_summary_entities(route_trace)
    if not candidate_entities:
        return []
    chat_service = _chat_service_facade()
    _, updated_fields = await chat_service.apply_route_entity_hot_update(
        session,
        user_message=user_message,
        candidate_entities=candidate_entities,
    )
    if not updated_fields:
        return []
    await db.flush()
    chat_service.logger.info(
        "event=route_entities_synced_to_stm session=%s updated_fields=%s entities=%s",
        session.id,
        ",".join(updated_fields),
        ",".join(
            str(item.get("canonical_id") or item.get("display_name") or "").strip()
            for item in candidate_entities
            if isinstance(item, dict)
        ),
    )
    return updated_fields


def _strip_profile_actions_from_reply(reply_text: str) -> str:
    cleaned = (reply_text or "").strip()
    if not cleaned:
        return ""

    # 清理规范的 <action>...</action> 标签
    cleaned = re.sub(r"<action>.*?</action>", "", cleaned, flags=re.DOTALL).strip()

    # 清理模型裸输出的画像动作 JSON，例如 {"action":"sectors","value":["半导体"]}
    cleaned = re.sub(
        r'^\s*\{[\s\S]*?"action"\s*:\s*"(?:update_profile|risk_level|sectors|investment_horizon|response_pref)"[\s\S]*?\}\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r'\n?\s*\{[\s\S]*?"action"\s*:\s*"(?:update_profile|risk_level|sectors|investment_horizon|response_pref)"[\s\S]*?\}\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    return cleaned


async def _prepare_reply_for_user(
    reply_text: str,
    *,
    user_id: str,
    db: AsyncSession,
) -> str:
    processed = (reply_text or "").strip()
    if not processed:
        return ""
    if settings.enable_memory and user_id:
        await _chat_service_facade()._handle_profile_action_in_reply(processed, user_id, db)
    return _strip_profile_actions_from_reply(processed)
