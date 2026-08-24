"""定义聊天 Application 层依赖的持久化端口。"""

from __future__ import annotations

from typing import Protocol

from src.conversation.contracts import ConversationRequest, ConversationResult

from .contracts import (
    ChatCommand,
    ChatContextWindowData,
    ChatMessagesPage,
    ChatSessionRecord,
    ChatSummaryRecord,
    PreparedChatTurn,
)


class TransactionalConversationRepository(Protocol):
    """单轮聊天所需的事务型 Repository 合同。"""

    async def prepare_turn(self, command: ChatCommand) -> PreparedChatTurn:
        """加载或创建用户会话，并暂存当前用户消息。"""
        ...

    async def save_result(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> ChatContextWindowData:
        """暂存唯一终态和会话指标，不自行提交。"""
        ...

    async def commit(self) -> None:
        """提交由 Application 决定的完整一轮事务。"""
        ...

    async def rollback(self) -> None:
        """回滚当前完整一轮事务。"""
        ...


class ChatSessionRepository(Protocol):
    """会话查询和管理的持久化合同。"""

    async def list_sessions(self, user_id: str) -> list[ChatSessionRecord]: ...

    async def rename_session(self, session_id: str, user_id: str, title: str) -> bool: ...

    async def get_messages(self, session_id: str, user_id: str) -> ChatMessagesPage: ...

    async def get_summaries(self, session_id: str, user_id: str) -> list[ChatSummaryRecord]: ...

    async def delete_session(self, session_id: str, user_id: str) -> bool: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
