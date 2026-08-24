"""提供与数据库和模型供应商无关的上下文预算策略。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextTextItem:
    """表示一个带权威消息边界的原文上下文项。"""

    message_id: int
    text: str


@dataclass(frozen=True, slots=True)
class PackedContext:
    """表示在输入预算内完成裁剪的上下文结果。"""

    current_message: str
    recent_messages: tuple[ContextTextItem, ...]
    running_summary: str | None
    input_budget_tokens: int
    used_tokens: int
    dropped_message_count: int
    summary_dropped: bool


@dataclass(frozen=True, slots=True)
class ContextBudgetPolicy:
    """用保守估算保护当前问题、输出空间和最近原文尾窗。"""

    model_window_tokens: int
    output_reserve_tokens: int
    safety_margin_tokens: int
    stage_overhead_tokens: int

    @property
    def input_budget_tokens(self) -> int:
        """返回历史、摘要和当前输入共同可使用的最大 token 数。"""
        return max(
            1,
            self.model_window_tokens
            - self.output_reserve_tokens
            - self.safety_margin_tokens
            - self.stage_overhead_tokens,
        )

    def pack(
        self,
        *,
        current_message: str,
        recent_messages: tuple[ContextTextItem, ...],
        running_summary: str | None,
    ) -> PackedContext:
        """按当前轮 > 最近原文 > 旧摘要的优先级装配上下文。

        Args:
            current_message: 当前用户输入，永远不可被历史裁掉。
            recent_messages: 按消息主键升序排列的受保护候选尾窗。
            running_summary: 只代表更早历史的 last-good 摘要。

        Returns:
            不超过预算的上下文及可观测裁剪计数。

        Raises:
            ValueError: 当前输入本身已经超过可用输入预算。
        """
        budget = self.input_budget_tokens
        current_tokens = estimate_text_tokens(current_message)
        if current_tokens > budget:
            raise ValueError("current message exceeds the protected context budget")

        remaining = budget - current_tokens
        selected_reversed: list[ContextTextItem] = []
        for item in reversed(recent_messages):
            item_tokens = estimate_text_tokens(item.text)
            if item_tokens > remaining:
                # 原文尾窗必须是连续后缀，不能越过超预算的新消息去捞更旧内容。
                break
            selected_reversed.append(item)
            remaining -= item_tokens
        selected = tuple(reversed(selected_reversed))

        summary = (running_summary or "").strip() or None
        summary_dropped = False
        if summary:
            summary_tokens = estimate_text_tokens(summary)
            if summary_tokens <= remaining:
                remaining -= summary_tokens
            else:
                summary = None
                summary_dropped = True

        return PackedContext(
            current_message=current_message,
            recent_messages=selected,
            running_summary=summary,
            input_budget_tokens=budget,
            used_tokens=budget - remaining,
            dropped_message_count=len(recent_messages) - len(selected),
            summary_dropped=summary_dropped,
        )


def estimate_text_tokens(text: str) -> int:
    """以可复现的保守规则估算中英文混合文本 token 数。"""
    if not text:
        return 0
    chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars / 1.5 + other_chars / 4) + 1)
