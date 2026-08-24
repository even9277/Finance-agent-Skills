"""构建当前阶段所需的最小上下文包。"""

from __future__ import annotations

from src.memory.contracts import WorkingState

from .contracts import ContextPacket, ConversationRequest, Entity, EntityType


class ContextBuilder:
    """按当前轮优先原则裁剪上下文，不读取外部记忆实现。"""

    def build(
        self,
        request: ConversationRequest,
        *,
        recent_messages: tuple[str, ...] = (),
        running_summary: str | None = None,
        working_state: WorkingState | None = None,
    ) -> ContextPacket:
        """构造不会覆盖当前轮指令的上下文包。

        Args:
            request: 已校验的当前轮请求。
            recent_messages: 由 Application 读取并裁剪的最近消息摘要。
            running_summary: 只覆盖 protected tail 之前历史的 last-good 摘要。
            working_state: PostgreSQL 权威的会话级热状态。

        Returns:
            当前轮问题优先的不可变上下文包。
        """
        reset_segment = _requests_segment_reset(request.message)
        state = WorkingState() if reset_segment else (working_state or WorkingState())
        return ContextPacket(
            current_message=request.message.strip(),
            recent_messages=tuple(item for item in recent_messages if item.strip()),
            running_summary=running_summary.strip() if running_summary else None,
            confirmed_constraints=state.constraints,
            reply_preference_hint=state.reply_preference_hint,
            working_entity=_to_conversation_entity(state.active_entity),
            working_candidates=tuple(
                item
                for candidate in state.candidate_entities
                if (item := _to_conversation_entity(candidate)) is not None
            ),
            reset_working_segment=reset_segment,
        )


def _to_conversation_entity(entity: object) -> Entity | None:
    """把 Memory 实体映射为受控工作流实体，拒绝未知实体类型。"""
    if entity is None:
        return None
    try:
        return Entity(
            symbol=str(getattr(entity, "symbol")),
            name=str(getattr(entity, "name")),
            entity_type=EntityType(str(getattr(entity, "entity_type"))),
        )
    except (AttributeError, ValueError):
        return None


def _requests_segment_reset(text: str) -> bool:
    """识别用户明确结束当前话题段的指令，作为临时状态确定性过期点。"""
    normalized = (text or "").replace(" ", "")
    return any(
        marker in normalized
        for marker in ("重新开始", "开始新话题", "换个新话题", "清空当前上下文")
    )
