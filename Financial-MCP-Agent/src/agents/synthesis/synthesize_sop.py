from __future__ import annotations

from typing import Any

from src.agents.synthesis.answer_context_pack import build_synthesis_prompt, pack_from_tool_data
from src.tools.skill_trace import trace_span


def build_sop_synthesis_prompt(
    *,
    effective_query: str,
    tool_data: dict[str, Any] | None,
    answer_policy_context: str = "",
    ltm_full: str = "",
    skill_id: str = "",
    output_template: str = "",
    fallbacks: str = "",
    decision_rules: str = "",
) -> str:
    with trace_span(
        "synthesis",
        stage="synthesis",
        data={
            "mode": "financial-sop",
            "skill_id": skill_id,
            "accepted_evidence_count": len((tool_data or {}).get("accepted_evidences") or []),
            "query_preview": (effective_query or "")[:80],
        },
    ):
        pack = pack_from_tool_data(
            user_intent=effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_context=ltm_full,
            skill_id=skill_id,
            default_claim_level="descriptive",
        )
        contract = (
            "[SKILL 输出合同]\n"
            f"Output Template:\n{output_template or '无'}\n\n"
            f"Fallbacks:\n{fallbacks or '无'}\n\n"
            f"Decision Rules:\n{decision_rules or '无'}\n"
        )
        prompt = build_synthesis_prompt(pack=pack, mode="financial-sop", extra_contract=contract)
        return prompt


__all__ = ["build_sop_synthesis_prompt"]
