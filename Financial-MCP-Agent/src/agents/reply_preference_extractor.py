from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ReplyPreferenceExtractionResult(BaseModel):
    reply_preference_hint: str = ""
    operation: Literal["replace", "clear", "no_update"] = "no_update"
    confidence: float = 0.0
    source: str = "rule"


def extract_reply_preference_rule(text: str) -> ReplyPreferenceExtractionResult:
    query = text or ""
    if any(token in query for token in ("先给结论", "结论先行", "直接说结论")):
        return ReplyPreferenceExtractionResult(reply_preference_hint="先给结论，再展开", operation="replace", confidence=0.9)
    if any(token in query for token in ("简单", "简短", "简洁")):
        return ReplyPreferenceExtractionResult(reply_preference_hint="回答简洁", operation="replace", confidence=0.85)
    if any(token in query for token in ("详细", "展开讲", "说细一点")):
        return ReplyPreferenceExtractionResult(reply_preference_hint="适当展开解释", operation="replace", confidence=0.85)
    if any(token in query for token in ("先讲风险", "风险优先", "先说风险")):
        return ReplyPreferenceExtractionResult(reply_preference_hint="风险提示优先", operation="replace", confidence=0.9)
    return ReplyPreferenceExtractionResult()


async def extract_reply_preference(ctx_packet: Any, rewrite_result: Any | None = None) -> ReplyPreferenceExtractionResult:
    text = getattr(ctx_packet, "user_query", "") if ctx_packet is not None else ""
    return extract_reply_preference_rule(str(text))


__all__ = ["ReplyPreferenceExtractionResult", "extract_reply_preference", "extract_reply_preference_rule"]
