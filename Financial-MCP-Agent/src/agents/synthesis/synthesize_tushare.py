from __future__ import annotations

from typing import Any

from src.agents.synthesis.answer_context_pack import build_synthesis_prompt, pack_from_tool_data


def build_tushare_synthesis_prompt(
    *,
    effective_query: str,
    tool_data: dict[str, Any] | None,
    answer_policy_context: str = "",
    ltm_full: str = "",
) -> str:
    pack = pack_from_tool_data(
        user_intent=effective_query,
        tool_data=tool_data,
        answer_policy_context=answer_policy_context,
        ltm_context=ltm_full,
        default_claim_level="descriptive",
    )
    return build_synthesis_prompt(pack=pack, mode="tushare-data")


__all__ = ["build_tushare_synthesis_prompt"]
