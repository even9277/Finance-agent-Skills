from __future__ import annotations

from src.agents.synthesis.answer_context_pack import AnswerContextPack, build_synthesis_prompt


def build_fallback_synthesis_prompt(
    *,
    effective_query: str,
    answer_policy_context: str = "",
    ltm_full: str = "",
) -> str:
    pack = AnswerContextPack(
        user_intent=effective_query,
        allowed_claim_level="advisory",
        constraints=[line.strip("- ").strip() for line in answer_policy_context.splitlines() if line.strip()][:8],
        reply_preference_hint=answer_policy_context or "",
        ltm_context=ltm_full or "",
    )
    return build_synthesis_prompt(
        pack=pack,
        mode="fallback",
        extra_contract="[要求]\n结合上下文给出直接回答；如果涉及实时行情或财务事实，说明需要进入数据技能链路验证。\n",
    )


__all__ = ["build_fallback_synthesis_prompt"]
