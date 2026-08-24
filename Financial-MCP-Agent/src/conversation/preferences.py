"""抽取只影响表达结构、不改变事实与权限的回答偏好。"""

from __future__ import annotations

from .contracts import PreferenceOperation, ReplyPreference


class ReplyPreferenceExtractor:
    """按明确优先级识别结论、风险、简洁或详细偏好。"""

    def extract(self, text: str) -> ReplyPreference:
        """返回当前轮显式回答偏好。

        Args:
            text: 当前用户问题。

        Returns:
            单一高置信偏好；没有明确信号时不更新。
        """
        query = text or ""
        if any(
            token in query
            for token in ("取消回答偏好", "按默认回答", "不用简洁了", "不用详细了")
        ):
            return ReplyPreference(
                operation=PreferenceOperation.CLEAR,
                confidence=0.9,
            )
        if any(token in query for token in ("先说风险", "先讲风险", "风险优先")):
            return _preference("风险提示优先", 0.92)
        if any(token in query for token in ("先给结论", "结论先行", "直接说结论")):
            return _preference("先给结论，再展开", 0.92)
        if any(token in query for token in ("简单", "简短", "简洁")):
            return _preference("回答简洁", 0.88)
        if any(token in query for token in ("详细", "展开讲", "说细一点")):
            return _preference("适当展开解释", 0.88)
        return ReplyPreference()


def _preference(hint: str, confidence: float) -> ReplyPreference:
    return ReplyPreference(
        hint=hint,
        operation=PreferenceOperation.REPLACE,
        confidence=confidence,
    )
