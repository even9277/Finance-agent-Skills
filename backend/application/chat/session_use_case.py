"""提供与对话执行解耦的会话查询和管理用例。"""

from __future__ import annotations

from .contracts import ChatMessagesPage, ChatSessionRecord, ChatSummaryRecord
from .ports import ChatSessionRepository


class ChatSessionUseCase:
    """集中会话读取、重命名和删除的事务时点。"""

    def __init__(self, repository: ChatSessionRepository) -> None:
        self._repository = repository

    async def list_sessions(self, user_id: str) -> list[ChatSessionRecord]:
        """返回指定用户的对话会话。"""
        return await self._repository.list_sessions(user_id)

    async def get_messages(self, session_id: str, user_id: str) -> ChatMessagesPage:
        """返回指定用户可访问的完整消息历史。"""
        return await self._repository.get_messages(session_id, user_id)

    async def get_summaries(
        self,
        session_id: str,
        user_id: str,
    ) -> list[ChatSummaryRecord]:
        """返回指定用户可访问的摘要快照。"""
        return await self._repository.get_summaries(session_id, user_id)

    async def rename_session(
        self,
        session_id: str,
        user_id: str,
        title: str,
    ) -> bool:
        """重命名会话并由用例提交；失败时回滚。"""
        try:
            changed = await self._repository.rename_session(session_id, user_id, title)
            await self._repository.commit()
            return changed
        except BaseException:
            await self._repository.rollback()
            raise

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """删除会话并由用例提交；失败时回滚。"""
        try:
            deleted = await self._repository.delete_session(session_id, user_id)
            await self._repository.commit()
            return deleted
        except BaseException:
            await self._repository.rollback()
            raise
