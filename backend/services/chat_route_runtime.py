from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from backend.schemas.chat import ChatContextWindow

_STOCK_CODE_RE = re.compile(r"\b(?:sh|sz)?\.?(\d{6})\b", re.IGNORECASE)
_ENTITY_PATTERNS = [
    re.compile(r"(?:帮我|请|继续|分析|看看|看下|研究|跟踪|补充|回到|关于|聊聊)([\u4e00-\u9fffA-Za-z0-9\-]{2,20}(?:ETF|基金|指数|板块|行业)?)"),
    re.compile(r"(?:换成|改成|现在换成|现在看|改看|切到)([\u4e00-\u9fffA-Za-z0-9\-]{2,20}(?:ETF|基金|指数|板块|行业)?)"),
    re.compile(r"^([\u4e00-\u9fffA-Za-z0-9\-]{2,20})(?:\(|（|\s|：|:|，|,)"),
]
_ENTITY_STOPWORDS = {
    "继续",
    "风险",
    "估值",
    "中长线",
    "长线",
    "短线",
    "重新回答",
    "再补一下",
    "补一下",
    "现在",
    "这个",
}
_FOLLOW_UP_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "risk": ("风险",),
    "valuation": ("估值", "pe", "pb", "peg", "ps"),
    "mid_long_term": ("中长线", "长线", "长期"),
    "compare": ("对比", "比较", "哪个好", "哪个更好", "区别"),
    "selection": ("筛选", "推荐", "候选", "组合"),
}
_ROUTE_RUNTIME_TTL = timedelta(minutes=25)


@dataclass(slots=True)
class RouteRuntimeState:
    last_active_entity: str = ""
    last_analysis_mode: str = "general_chat"
    last_user_goal: str = ""
    last_followup_dimension: str = ""
    last_successful_tool_query: str = ""
    last_tool_status: str = "unknown"
    inherited_fail_streak: int = 0
    last_route_confidence: float = 0.0
    updated_at: str = ""
    # FIX-3: structured entity ledger
    active_entity_type: str = ""           # "stock" | "fund" | "sector" | ""
    active_entity_id: str = ""             # canonical symbol, e.g. "600519.SH"
    active_entity_display_name: str = ""   # e.g. "贵州茅台"
    entity_resolution_source: str = ""     # "llm" | "inherit" | "manual" | ""


_ROUTE_RUNTIME_BY_SESSION: dict[str, RouteRuntimeState] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_entity(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""
    code_match = _STOCK_CODE_RE.search(clean)
    if code_match:
        return code_match.group(1)
    for pattern in _ENTITY_PATTERNS:
        match = pattern.search(clean)
        if not match:
            continue
        candidate = (match.group(1) if match.groups() else match.group(0)).strip("，。！？,.!?：:；;()（）[]【】 ")
        candidate = re.sub(r"^(请|帮我|继续|分析|看看|看下|研究|跟踪|补充|回到|关于|聊聊|换成|改成|现在换成|现在看|改看|切到)+", "", candidate).strip()
        if candidate and candidate not in _ENTITY_STOPWORDS and len(candidate) >= 2:
            return candidate
    return ""


def _followup_dimension(text: str) -> str:
    lowered = (text or "").lower()
    for dimension, hints in _FOLLOW_UP_DIMENSIONS.items():
        if any(hint.lower() in lowered for hint in hints):
            return dimension
    return ""


def _normalize_tool_status(reply_text: str, trace: dict[str, Any] | None) -> str:
    executor = (trace or {}).get("executor") if isinstance((trace or {}).get("executor"), dict) else {}
    if executor.get("evidence_ok") is True:
        return "success"
    if str(executor.get("degrade_stage") or "") == "graceful_decline":
        return "failed"
    text = (reply_text or "").strip()
    if any(token in text for token in ("不能可靠回答", "暂时无法获取", "未成功拿到足够的工具结果", "unable to resolve stock symbol", "数据获取失败")):
        return "failed"
    if any(token in text for token in ("数据来源", "数据时间", "财报期", "收盘价", "市盈率")):
        return "success"
    return "unknown"


def _route_state_from_dict(data: dict[str, Any]) -> RouteRuntimeState:
    state = RouteRuntimeState()
    for field in RouteRuntimeState.__dataclass_fields__.keys():
        if field in data and data[field] is not None:
            setattr(state, field, data[field])
    return state


def _resolved_entity_from_args(args: dict[str, Any]) -> dict[str, str]:
    hint = args.get("resolved_entity_hint")
    if isinstance(hint, dict):
        return {
            "asset_type": str(hint.get("asset_type") or "").strip(),
            "symbol": str(hint.get("symbol") or "").strip(),
            "display_name": str(hint.get("display_name") or "").strip(),
            "resolver_source": str(hint.get("resolver_source") or hint.get("resolver_stage") or "").strip(),
        }

    entities = args.get("entities")
    if isinstance(entities, list):
        for item in entities:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            asset_type = str(item.get("asset_type") or "").strip()
            if symbol or display_name:
                return {
                    "asset_type": asset_type,
                    "symbol": symbol,
                    "display_name": display_name,
                    "resolver_source": "rewriter_entities",
                }
    return {
        "asset_type": "",
        "symbol": "",
        "display_name": "",
        "resolver_source": "",
    }


def get_runtime_route_state(session_id: str) -> RouteRuntimeState | None:
    state = _ROUTE_RUNTIME_BY_SESSION.get(session_id)
    if state is None:
        return None
    try:
        updated_at = datetime.fromisoformat(state.updated_at)
    except Exception:
        updated_at = None
    if updated_at is None or (_utcnow() - updated_at.astimezone(timezone.utc)) > _ROUTE_RUNTIME_TTL:
        _ROUTE_RUNTIME_BY_SESSION.pop(session_id, None)
        return None
    return state


def build_route_state_payload(session_id: str, fallback_state: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = get_runtime_route_state(session_id)
    base = dict(fallback_state or {})
    if runtime is None:
        if base and "updated_at" not in base:
            base["updated_at"] = _utcnow().isoformat(timespec="seconds")
        return base
    payload = asdict(runtime)
    for key, value in base.items():
        if key not in payload or not payload.get(key):
            payload[key] = value
    return payload


def seed_route_runtime_from_summary_payload(
    payload: dict[str, Any] | None,
    existing_state: RouteRuntimeState | None = None,
) -> RouteRuntimeState | None:
    state = existing_state or RouteRuntimeState()
    if state.active_entity_id or state.active_entity_display_name:
        return state
    active_entities = payload.get("active_entities") if isinstance(payload, dict) else None
    if not isinstance(active_entities, list):
        return existing_state
    for item in active_entities:
        if not isinstance(item, dict):
            continue
        canonical_id = str(item.get("canonical_id") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        if not canonical_id and not display_name:
            continue
        seeded = RouteRuntimeState(**asdict(state))
        seeded.active_entity_id = canonical_id
        seeded.active_entity_display_name = display_name or canonical_id
        seeded.active_entity_type = str(item.get("entity_type") or "").strip()
        seeded.entity_resolution_source = str(item.get("source") or "summary_payload").strip() or "summary_payload"
        seeded.last_active_entity = seeded.active_entity_display_name
        seeded.updated_at = _utcnow().isoformat(timespec="seconds")
        return seeded
    return existing_state


def record_route_runtime_state(
    *,
    session_id: str,
    user_message: str,
    route_trace: dict[str, Any] | None,
    reply_text: str,
) -> RouteRuntimeState:
    existing = get_runtime_route_state(session_id) or RouteRuntimeState()
    args = (route_trace or {}).get("arguments") if isinstance((route_trace or {}).get("arguments"), dict) else {}
    selected_skill = str((route_trace or {}).get("selected_skill") or "")
    analysis_mode = str((route_trace or {}).get("analysis_mode") or existing.last_analysis_mode or "general_chat")
    effective_query = str(args.get("effective_query") or user_message or "").strip()
    inherited_entity = str(args.get("inherited_entity") or "").strip()
    direct_entity = _extract_entity(effective_query) or _extract_entity(user_message)
    active_entity = direct_entity or inherited_entity or existing.last_active_entity
    followup_dimension = str(args.get("follow_up_dimension") or _followup_dimension(effective_query) or existing.last_followup_dimension)
    tool_status = _normalize_tool_status(reply_text, route_trace)
    is_follow_up = bool(args.get("is_follow_up"))

    # FIX-3: extract resolved entity from executor trace
    executor = (route_trace or {}).get("executor") if isinstance((route_trace or {}).get("executor"), dict) else {}
    resolved_symbol = str(executor.get("resolved_symbol") or "").strip()
    resolved_company = str(executor.get("resolved_company") or "").strip()
    resolved_entity = _resolved_entity_from_args(args)
    resolved_entity_type = str(resolved_entity.get("asset_type") or "").strip()
    resolved_entity_symbol = str(resolved_entity.get("symbol") or "").strip()
    resolved_entity_name = str(resolved_entity.get("display_name") or "").strip()
    resolved_entity_source = str(resolved_entity.get("resolver_source") or "").strip()

    state = RouteRuntimeState(
        last_active_entity=existing.last_active_entity,
        last_analysis_mode=existing.last_analysis_mode,
        last_user_goal=existing.last_user_goal,
        last_followup_dimension=existing.last_followup_dimension,
        last_successful_tool_query=existing.last_successful_tool_query,
        last_tool_status=existing.last_tool_status,
        inherited_fail_streak=int(existing.inherited_fail_streak or 0),
        last_route_confidence=float((route_trace or {}).get("confidence") or existing.last_route_confidence or 0.0),
        updated_at=_utcnow().isoformat(timespec="seconds"),
        active_entity_type=existing.active_entity_type,
        active_entity_id=existing.active_entity_id,
        active_entity_display_name=existing.active_entity_display_name,
        entity_resolution_source=existing.entity_resolution_source,
    )

    if active_entity:
        state.last_active_entity = active_entity
    if analysis_mode:
        state.last_analysis_mode = analysis_mode
    if effective_query:
        state.last_user_goal = effective_query[:180]
    if followup_dimension:
        state.last_followup_dimension = followup_dimension
    if tool_status:
        state.last_tool_status = tool_status

    if selected_skill != "fallback" and tool_status == "success" and effective_query:
        state.last_successful_tool_query = effective_query[:180]

    if selected_skill == "fallback" and direct_entity:
        state.last_successful_tool_query = existing.last_successful_tool_query or effective_query[:180]

    if is_follow_up and inherited_entity and tool_status == "failed":
        state.inherited_fail_streak = int(existing.inherited_fail_streak or 0) + 1
    elif is_follow_up and inherited_entity and tool_status == "success":
        state.inherited_fail_streak = 0
    elif not is_follow_up:
        state.inherited_fail_streak = 0

    # FIX-3: update entity ledger from resolved entity
    if resolved_symbol:
        state.active_entity_type = "stock"
        state.active_entity_id = resolved_symbol
        state.active_entity_display_name = resolved_company or resolved_symbol
        state.entity_resolution_source = "llm"
        state.last_active_entity = resolved_company or resolved_symbol
    elif resolved_entity_symbol or resolved_entity_name:
        state.active_entity_type = resolved_entity_type or existing.active_entity_type
        state.active_entity_id = resolved_entity_symbol or existing.active_entity_id
        state.active_entity_display_name = (
            resolved_entity_name
            or resolved_entity_symbol
            or existing.active_entity_display_name
        )
        state.entity_resolution_source = resolved_entity_source or "resolver"
        state.last_active_entity = (
            resolved_entity_name
            or resolved_entity_symbol
            or state.last_active_entity
        )
    elif is_follow_up and existing.active_entity_id:
        state.entity_resolution_source = "inherit"

    _ROUTE_RUNTIME_BY_SESSION[session_id] = state
    return state


def enrich_context_window(window: ChatContextWindow | None, session_id: str) -> ChatContextWindow | None:
    if window is None:
        return None
    # Product: do not surface route-runtime follow-up / entity hints on context_window
    # (was memory_hint / "连续追问将优先继承…"). Session STM 现在仅通过 running summary 暴露。
    return window
