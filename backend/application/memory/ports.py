"""定义记忆应用层面向权威存储的事务型端口。"""

from __future__ import annotations

from typing import Protocol

from src.memory.contracts import NewOutboxTask, OutboxTask, WorkingState


class TransactionalMemoryRepository(Protocol):
    """声明必须复用调用方事务的记忆持久化操作。"""

    async def load_or_create_working_state(
        self,
        *,
        user_id: str,
        session_id: str,
        source_message_id: int,
    ) -> WorkingState:
        """读取会话 Working State；不存在时暂存版本 0 的初始快照。"""
        ...

    async def enqueue_outbox(self, intent: NewOutboxTask) -> OutboxTask:
        """暂存幂等 Outbox 任务，但不提交当前数据库事务。"""
        ...
