from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from src.prompts.skill_routing import ROUTER_PROMPT as _ROUTER_PROMPT
from src.skills.skill_registry import get_skill_registry

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / "backend" / ".env", override=False)
except Exception:
    pass


class DetectedEntity(BaseModel):
    """Dead code placeholder kept for future rewrite module."""

    value: str = Field(default="")
    type: str = Field(default="")


@dataclass(slots=True)
class FollowUpResolution:
    """Dead code placeholder kept for future rewrite module."""

    effective_query: str
    is_follow_up: bool
    follow_up_confidence: float = 0.0
    inherited_entity: str = ""
    follow_up_dimension: str = ""
    query_rewrite_reason: str = ""
    route_state: dict[str, Any] | None = None
    inherited_entity_id: str = ""
    inherited_entity_display_name: str = ""
    inherited_entity_type: str = ""


def _resolve_follow_up(user_message: str, conversation_context: str) -> FollowUpResolution:
    """Follow-up handling is intentionally disabled in this phase."""

    _ = conversation_context
    return FollowUpResolution(
        effective_query=(user_message or "").strip(),
        is_follow_up=False,
        route_state={},
    )


class RouteSop(BaseModel):
    route: Literal["sop"]
    skill_id: str
    execution_policy: Literal["deterministic", "agentic"] = "deterministic"


class RouteTushare(BaseModel):
    route: Literal["tushare"]


class RouteFallback(BaseModel):
    route: Literal["fallback"]


RouteOutput = Annotated[
    Union[RouteTushare, RouteFallback],
    Field(discriminator="route"),
]


class _RouteOutputPayload(BaseModel):
    """LangChain structured-output compatibility payload."""

    route: Literal["sop", "tushare", "fallback"]
    skill_id: str | None = None
    execution_policy: Literal["deterministic", "agentic"] | None = None


@dataclass(slots=True)
class SkillRouteDecision:
    route: Literal["sop", "tushare", "fallback"]
    skill_id: str | None = None
    execution_policy: str = "deterministic"
    confidence: float = 0.0
    need_confirm: bool = False
    confirm_candidates: list[str] | None = None
    stage1: dict[str, Any] | None = None
    stage2: dict[str, Any] | None = None
    route_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = _build_executor_route_trace(self, "")
        data.update(
            {
                "route": self.route,
                "skill_id": self.skill_id,
                "execution_policy": self.execution_policy,
                "confidence": self.confidence,
                "need_confirm": self.need_confirm,
                "confirm_candidates": list(self.confirm_candidates or []),
                "route_stage1": self.stage1,
                "route_stage2": self.stage2,
                "route_source": self.route_source,
            }
        )
        return data


def skill_route_decision_from_dict(data: dict[str, Any]) -> SkillRouteDecision:
    route = str(data.get("route") or "fallback").strip()
    if route not in {"sop", "tushare", "fallback"}:
        route = "fallback"
    skill_id = data.get("skill_id")
    if skill_id is not None:
        skill_id = str(skill_id).strip() or None
    execution_policy = _coerce_execution_policy(str(data.get("execution_policy") or "deterministic"))
    if route != "sop":
        skill_id = None
        execution_policy = "deterministic"
    confidence = float(data.get("confidence") or data.get("route_confidence") or 0.0)
    return SkillRouteDecision(
        route=route,
        skill_id=skill_id,
        execution_policy=execution_policy,
        confidence=confidence,
        need_confirm=bool(data.get("need_confirm") or data.get("hitl_pending")),
        confirm_candidates=list(data.get("confirm_candidates") or []),
        stage1=data.get("route_stage1") if isinstance(data.get("route_stage1"), dict) else None,
        stage2=data.get("route_stage2") if isinstance(data.get("route_stage2"), dict) else None,
        route_source=str(data.get("route_source") or ""),
    )




def _safe_getenv(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _router_model_name() -> str:
    return _safe_getenv("CHAT_ROUTER_MODEL") or _safe_getenv("OPENAI_COMPATIBLE_MODEL") or "kimi-k2.5"


def _available_sop_skill_ids() -> set[str]:
    return {item.name for item in get_skill_registry().discoverable_sop_skills()}


def _build_sop_catalog() -> str:
    skills = get_skill_registry().discoverable_sop_skills()
    if not skills:
        return "- 无可用 SOP 技能"
    return "\n".join(
        f"- {item.name}: {item.description}"
        for item in skills
    )


def _coerce_execution_policy(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"deterministic", "agentic"}:
        return normalized
    return "deterministic"


def _registry_execution_policy(skill_id: str) -> str:
    meta = get_skill_registry().get_skill(skill_id)
    if meta is None:
        return "deterministic"
    return _coerce_execution_policy(str(meta.execution_mode or ""))


def registry_execution_policy_for_skill(skill_id: str) -> str:
    return _registry_execution_policy(skill_id)


def user_explicit_sop_decision(skill_id: str) -> SkillRouteDecision | None:
    normalized_skill_id = str(skill_id or "").strip()
    if not normalized_skill_id:
        return None
    if normalized_skill_id not in _available_sop_skill_ids():
        return None
    return SkillRouteDecision(
        route="sop",
        skill_id=normalized_skill_id,
        execution_policy=_registry_execution_policy(normalized_skill_id),
    )


def _pydantic_validate(model_cls: Any, data: dict[str, Any]) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)
    return model_cls.parse_obj(data)


def _coerce_llm_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text_part = item.get("text")
                if text_part:
                    parts.append(str(text_part))
                    continue
            parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _extract_json_dict(raw_text: Any) -> dict[str, Any] | None:
    text = _coerce_llm_content_text(raw_text).strip()
    if not text:
        return None

    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _payload_to_route_output(payload: _RouteOutputPayload) -> RouteOutput | None:
    route = payload.route
    if route == "sop":
        logger.warning("router_returned_legacy_sop_route degrade_to=fallback")
        return RouteFallback(route="fallback")
    if route == "tushare":
        return RouteTushare(route="tushare")
    return RouteFallback(route="fallback")


def _validate_route_output(raw: RouteOutput) -> SkillRouteDecision:
    try:
        if isinstance(raw, RouteTushare):
            return SkillRouteDecision(route="tushare")

        return SkillRouteDecision(route="fallback")
    except Exception:
        logger.exception("route_validation_exception")
        return SkillRouteDecision(route="fallback")


async def _llm_route(
    user_message: str,
    conversation_context: str = "",
    profile_summary: str = "",
) -> RouteOutput | None:
    api_key = _safe_getenv("OPENAI_COMPATIBLE_API_KEY")
    base_url = _safe_getenv("OPENAI_COMPATIBLE_BASE_URL")
    model_name = _router_model_name()
    if not all([api_key, base_url, model_name]):
        logger.warning("route_parse_error reason=missing_router_env")
        return None

    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
    except Exception:
        logger.warning("route_parse_error reason=langchain_import_failed")
        return None

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=280,
    )
    prompt = _ROUTER_PROMPT.format(
        conversation_context=conversation_context or "无",
        profile_summary=profile_summary or "无",
        query=user_message,
    )
    messages = [HumanMessage(content=prompt)]

    try:
        result = await llm.ainvoke(messages)
    except Exception:
        logger.exception("route_parse_error")
        return None

    payload_raw = _extract_json_dict(getattr(result, "content", ""))
    if not isinstance(payload_raw, dict):
        raw_head = _coerce_llm_content_text(getattr(result, "content", ""))[:200].replace("\n", " ")
        logger.warning("route_parse_error reason=json_parse_failed raw_head=%s", raw_head)
        return None

    try:
        payload = _pydantic_validate(_RouteOutputPayload, payload_raw)
    except Exception:
        logger.warning("route_parse_error reason=schema_validate_failed payload=%s", payload_raw)
        return None

    return _payload_to_route_output(payload)


async def route_chat_skill(
    user_message: str,
    conversation_context: str = "",
    profile_summary: str = "",
    enable_route_v2: bool | None = None,
    active_entity: dict[str, Any] | None = None,
) -> SkillRouteDecision:
    if enable_route_v2 is None:
        enable_route_v2 = _safe_getenv("ENABLE_ROUTE_V2").lower() in {"1", "true", "yes", "on"}
    if enable_route_v2:
        try:
            from src.agents.router import route_v2

            decision_v2 = await route_v2(user_message, active_entity=active_entity)
            stage1 = decision_v2.stage1.model_dump() if decision_v2.stage1 is not None else None
            stage2 = decision_v2.stage2.model_dump() if decision_v2.stage2 is not None else None
            confidence = float((stage1 or {}).get("confidence") or (1.0 if decision_v2.route_source == "user_explicit" else 0.0))
            return SkillRouteDecision(
                route=decision_v2.legacy_route,
                skill_id=decision_v2.skill_id,
                execution_policy=decision_v2.execution_policy,
                confidence=confidence,
                need_confirm=decision_v2.need_confirm,
                confirm_candidates=list(decision_v2.confirm_candidates or []),
                stage1=stage1,
                stage2=stage2,
                route_source=decision_v2.route_source,
            )
        except Exception:
            logger.exception("route_v2_failed_fallback_to_legacy")
    raw = await _llm_route(
        user_message=user_message,
        conversation_context=conversation_context,
        profile_summary=profile_summary,
    )
    if raw is None:
        return SkillRouteDecision(route="fallback")
    return _validate_route_output(raw)


def _build_executor_route_trace(decision: SkillRouteDecision, user_message: str) -> dict[str, Any]:
    """Temporary adapter from minimal route decision to executor route_trace."""
    # DEPRECATED: replaced by rewrite pipeline (kept for compatibility path)

    query = (user_message or "").strip()
    args = {
        "query": query,
        "effective_query": query,
    }
    if decision.route == "sop":
        return {
            "selected_skill_family": "financial-sop",
            "selected_skill": "financial-sop",
            "skill_name": decision.skill_id,
            "execution_policy": _coerce_execution_policy(decision.execution_policy),
            "analysis_mode": "general_chat",
            "needs_realtime_data": False,
            "arguments": args,
            "confidence": decision.confidence,
            "need_confirm": decision.need_confirm,
            "confirm_candidates": list(decision.confirm_candidates or []),
            "route_stage1": decision.stage1,
            "route_stage2": decision.stage2,
            "route_source": decision.route_source,
        }
    if decision.route == "tushare":
        return {
            "selected_skill_family": "tushare-data",
            "selected_skill": "tushare-data",
            "skill_name": None,
            "execution_policy": "deterministic",
            "analysis_mode": "general_chat",
            "needs_realtime_data": True,
            "arguments": args,
            "confidence": decision.confidence,
            "need_confirm": decision.need_confirm,
            "confirm_candidates": list(decision.confirm_candidates or []),
            "route_stage1": decision.stage1,
            "route_stage2": decision.stage2,
            "route_source": decision.route_source,
        }
    return {
        "selected_skill_family": "fallback",
        "selected_skill": "fallback",
        "skill_name": None,
        "execution_policy": "deterministic",
        "analysis_mode": "general_chat",
        "needs_realtime_data": False,
        "arguments": args,
        "confidence": decision.confidence,
        "need_confirm": decision.need_confirm,
        "confirm_candidates": list(decision.confirm_candidates or []),
        "route_stage1": decision.stage1,
        "route_stage2": decision.stage2,
        "route_source": decision.route_source,
    }


async def rewrite_query_for_skill(*args: Any, **kwargs: Any) -> None:
    """Temporarily disabled in this phase."""

    _ = args, kwargs
    return None
