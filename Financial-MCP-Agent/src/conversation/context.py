"""构建当前阶段所需的最小上下文包。"""

from __future__ import annotations

from .contracts import ContextPacket, ConversationRequest


class ContextBuilder:
    """按当前轮优先原则裁剪上下文，不读取外部记忆实现。"""

    def build(
        self,
        request: ConversationRequest,
        *,
        recent_messages: tuple[str, ...] = (),
        running_summary: str | None = None,
    ) -> ContextPacket:
        """构造不会覆盖当前轮指令的上下文包。

        Args:
            request: 已校验的当前轮请求。
            recent_messages: 由 Application 读取并裁剪的最近消息摘要。
            running_summary: 可选会话摘要；M2 不解释其内部结构。

        Returns:
            当前轮问题优先的不可变上下文包。
        """
        return ContextPacket(
            current_message=request.message.strip(),
            recent_messages=tuple(item for item in recent_messages[-6:] if item.strip()),
            running_summary=running_summary.strip() if running_summary else None,
        )
