from __future__ import annotations

from typing import Any, Literal
import json

from pydantic import BaseModel, Field

ClaimLevel = Literal["advisory", "analytical", "descriptive", "refuse"]


class EvidenceRef(BaseModel):
    evidence_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    evidence_type: str = ""
    symbol: str | None = None
    source_api: str = ""
    trade_date: str | None = None
    summary: str = ""


class AnswerContextPack(BaseModel):
    user_intent: str
    executed_plan_summary: list[dict[str, Any]] = Field(default_factory=list)
    accepted_evidences: list[EvidenceRef] = Field(default_factory=list)
    rejected_evidences: list[EvidenceRef] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    allowed_claim_level: ClaimLevel = "descriptive"
    constraints: list[str] = Field(default_factory=list)
    reply_preference_hint: str = ""
    ltm_context: str = ""
    skill_id: str = ""

    def prompt_json(self, *, max_chars: int = 12000) -> str:
        payload = self.model_dump() if hasattr(self, "model_dump") else self.dict()
        text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...<truncated>..."


def normalize_evidence_ref(raw: Any) -> EvidenceRef:
    if isinstance(raw, EvidenceRef):
        return raw
    payload = _as_dict(raw)
    summary_source = payload.get("payload_summary") or payload.get("summary") or payload.get("error_message") or ""
    return EvidenceRef(
        evidence_id=str(payload.get("evidence_id") or ""),
        step_id=str(payload.get("step_id") or ""),
        tool_name=str(payload.get("tool_name") or ""),
        evidence_type=str(payload.get("evidence_type") or ""),
        symbol=payload.get("symbol"),
        source_api=str(payload.get("source_api") or ""),
        trade_date=payload.get("trade_date"),
        summary=_compact_text(summary_source),
    )


def build_executed_plan_summary(tool_data: dict[str, Any]) -> list[dict[str, Any]]:
    trace = _as_dict((tool_data or {}).get("executor_trace"))
    plan_steps = (tool_data or {}).get("plan_steps") or trace.get("plan_steps") or []
    if plan_steps:
        return [
            {
                "step_id": str(_as_dict(step).get("step_id") or ""),
                "tool_name": str(_as_dict(step).get("tool_name") or ""),
                "goal": str(_as_dict(step).get("goal") or ""),
                "status": str(_as_dict(step).get("status") or "planned"),
            }
            for step in plan_steps
        ]
    results = (tool_data or {}).get("results") or []
    return [
        {
            "step_id": str(_as_dict(item).get("step_id") or f"s{index}"),
            "tool_name": str(_as_dict(item).get("tool_name") or ""),
            "status": "succeeded" if _as_dict(item).get("ok", True) else "failed",
        }
        for index, item in enumerate(results, start=1)
    ]


def pack_from_tool_data(
    *,
    user_intent: str,
    tool_data: dict[str, Any] | None = None,
    answer_policy_context: str = "",
    ltm_context: str = "",
    skill_id: str = "",
    default_claim_level: ClaimLevel = "descriptive",
) -> AnswerContextPack:
    tool_data = tool_data or {}
    verification = _as_dict(tool_data.get("verification") or tool_data.get("verification_result"))
    accepted_raw = verification.get("accepted_evidences") or tool_data.get("accepted_evidences") or []
    rejected_raw = verification.get("rejected_evidences") or tool_data.get("rejected_evidences") or []
    if not accepted_raw:
        accepted_raw = _accepted_from_legacy_results(tool_data)
    allowed = str(verification.get("allowed_claim_level") or tool_data.get("allowed_claim_level") or default_claim_level)
    if allowed not in {"advisory", "analytical", "descriptive", "refuse"}:
        allowed = default_claim_level
    return AnswerContextPack(
        user_intent=user_intent,
        executed_plan_summary=build_executed_plan_summary(tool_data),
        accepted_evidences=[normalize_evidence_ref(item) for item in accepted_raw],
        rejected_evidences=[normalize_evidence_ref(item) for item in rejected_raw],
        missing_dimensions=list(verification.get("missing_dimensions") or tool_data.get("missing_dimensions") or []),
        allowed_claim_level=allowed,  # type: ignore[arg-type]
        constraints=_extract_constraints(answer_policy_context),
        reply_preference_hint=answer_policy_context or "",
        ltm_context=ltm_context or "",
        skill_id=skill_id or "",
    )


def build_synthesis_prompt(*, pack: AnswerContextPack, mode: str, extra_contract: str = "") -> str:
    level_rules = {
        "analytical": "可以给出基于证据的分析判断，但必须标明数据口径与限制。",
        "descriptive": "只能做事实描述和保守解释，不得写强因果、确定性预测或买卖结论。",
        "advisory": "可以给一般性建议，但必须把风险和不确定性前置。",
        "refuse": "证据不足时应说明无法完成该分析，并列出缺失维度。",
    }
    return (
        "[角色]\n你是A股投研助手总结器，只能依据结构化证据回答。\n\n"
        f"[mode]\n{mode}\n\n"
        f"[allowed_claim_level]\n{pack.allowed_claim_level}: {level_rules.get(pack.allowed_claim_level, '')}\n\n"
        "[AnswerContextPack]\n"
        f"{pack.prompt_json()}\n\n"
        f"{extra_contract.strip()}\n\n"
        "[硬性约束]\n"
        "- 只能使用 accepted_evidences 中出现的信息；rejected_evidences 只能用于说明限制。\n"
        "- 不得编造证据包中不存在的数值、日期、来源或工具结论。\n"
        "- missing_dimensions 非空时必须显式说明缺失导致的限制。\n"
        "- allowed_claim_level=descriptive/refuse 时，不得输出强因果、确定性预测、保证收益或明确买卖指令。\n"
    )


def _accepted_from_legacy_results(tool_data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(tool_data.get("results") or [], start=1):
        payload = _as_dict(item)
        if payload.get("ok", True) is False:
            continue
        out.append(
            {
                "step_id": str(payload.get("step_id") or f"s{index}"),
                "tool_name": str(payload.get("tool_name") or payload.get("source_api") or ""),
                "evidence_id": str(payload.get("evidence_id") or ""),
                "evidence_type": str(payload.get("evidence_type") or ""),
                "symbol": payload.get("symbol"),
                "source_api": str(payload.get("source_api") or ""),
                "trade_date": payload.get("trade_date"),
                "summary": _compact_text(payload.get("payload") or payload),
            }
        )
    return out


def _extract_constraints(text: str) -> list[str]:
    lines = [line.strip("- ").strip() for line in (text or "").splitlines()]
    return [line for line in lines if line][:8]


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _compact_text(value: Any, *, max_chars: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[:max_chars] + "...<truncated>"


__all__ = [
    "AnswerContextPack",
    "ClaimLevel",
    "EvidenceRef",
    "build_executed_plan_summary",
    "build_synthesis_prompt",
    "normalize_evidence_ref",
    "pack_from_tool_data",
]
