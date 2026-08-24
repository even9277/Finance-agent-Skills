"""实现受控聊天和会话管理的 SQLAlchemy Repository。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.chat.contracts import (
    ChatCommand,
    ChatContextWindowData,
    ChatMessageRecord,
    ChatMessagesPage,
    ChatSessionRecord,
    ChatSummaryRecord,
    PreparedChatTurn,
)
from backend.application.memory.ports import TransactionalMemoryRepository
from backend.config import settings
from backend.db.models import Message, Session, SessionSummary, UserInvestProfile
from backend.infrastructure.memory.repository import SqlAlchemyMemoryRepository
from backend.services.stm_context_service import (
    build_context_window_payload,
    refresh_session_context_metrics,
)
from backend.services.token_counter import count_message_tokens
from src.conversation.contracts import ConversationRequest, ConversationResult
from src.memory.contracts import (
    NewOutboxTask,
    OutboxTaskKind,
    TurnCommittedPayload,
    WorkingState,
    build_turn_outbox_key,
)


def _context_data(session: Session, *, counting_mode: str | None = None) -> ChatContextWindowData:
    """把现有 Pydantic 上下文快照转换为 Application 数据。"""
    payload = build_context_window_payload(session, counting_mode=counting_mode)
    return ChatContextWindowData(**payload.model_dump())


class SqlAlchemyConversationRepository:
    """在调用方提供的 AsyncSession 中实现聊天持久化。"""

    def __init__(
        self,
        db: AsyncSession,
        memory_repository: TransactionalMemoryRepository | None = None,
    ) -> None:
        self._db = db
        self._prepared_sessions: dict[str, Session] = {}
        self._prepared_user_message_ids: dict[str, int] = {}
        self._prepared_working_states: dict[str, WorkingState] = {}
        self._memory = memory_repository or SqlAlchemyMemoryRepository(db)

    async def prepare_turn(self, command: ChatCommand) -> PreparedChatTurn:
        """隔离用户会话、读取尾窗并暂存当前用户消息。

        Args:
            command: 已通过公开协议边界校验的聊天命令。

        Returns:
            包含权威 session_id、裁剪历史和可选画像的输入快照。
        """
        # 同一会话的完整轮次串行化，避免首次状态初始化和 turn_count 丢失更新。
        session = await self._owned_session(
            command.session_id,
            command.user_id,
            lock=True,
        )
        if session is None:
            session = Session(user_id=command.user_id, mode="chat")
            self._db.add(session)
            await self._db.flush()

        history_result = await self._db.execute(
            select(Message)
            .where(Message.session_id == session.id, Message.is_compressed.is_(False))
            .order_by(Message.id.desc())
            .limit(max(1, int(settings.stm_keep_recent)))
        )
        recent = list(reversed(list(history_result.scalars().all())))
        token_count, _ = count_message_tokens("user", command.message)
        user_message = Message(
            session_id=session.id,
            role="user",
            content=command.message,
            token_count=token_count,
        )
        self._db.add(user_message)
        if not session.title:
            session.title = command.message[:30]
        await self._db.flush()
        working_state = await self._memory.load_or_create_working_state(
            user_id=command.user_id,
            session_id=session.id,
            source_message_id=user_message.id,
        )
        self._prepared_sessions[session.id] = session
        self._prepared_user_message_ids[session.id] = user_message.id
        self._prepared_working_states[session.id] = working_state

        return PreparedChatTurn(
            session_id=session.id,
            recent_messages=tuple(f"{item.role}: {item.content}" for item in recent),
            running_summary=session.running_summary,
            memory_profile=await self._load_memory_profile(command.user_id),
            working_state=working_state,
        )

    async def save_result(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> ChatContextWindowData:
        """暂存助手终态并刷新会话指标，不在 Repository 内提交。"""
        session = self._prepared_sessions.get(request.session_id)
        if session is None:
            session = await self._owned_session(request.session_id, request.user_id)
        if session is None:
            raise RuntimeError("prepared chat session is missing")

        token_count, _ = count_message_tokens("assistant", result.reply)
        assistant_message = Message(
            session_id=session.id,
            role="assistant",
            content=result.reply,
            token_count=token_count,
        )
        self._db.add(assistant_message)
        await self._db.flush()
        # 使用数据库表达式递增，SQLite 忽略 FOR UPDATE 时也不会发生丢失更新。
        await self._db.execute(
            update(Session)
            .where(Session.id == session.id)
            .values(
                turn_count=func.coalesce(Session.turn_count, 0) + 1,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
            .execution_options(synchronize_session=False)
        )
        await self._db.refresh(session, attribute_names=("turn_count", "updated_at"))
        context = await refresh_session_context_metrics(self._db, session)
        user_message_id = self._prepared_user_message_ids.get(session.id)
        working_state = self._prepared_working_states.get(session.id)
        if user_message_id is None or working_state is None:
            raise RuntimeError("prepared memory transaction context is missing")
        await self._memory.enqueue_outbox(
            NewOutboxTask(
                user_id=request.user_id,
                session_id=session.id,
                aggregate_type="chat_turn",
                aggregate_id=session.id,
                task_kind=OutboxTaskKind.TURN_COMMITTED,
                idempotency_key=build_turn_outbox_key(session.id, user_message_id),
                payload=TurnCommittedPayload(
                    session_id=session.id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message.id,
                    state_version=working_state.state_version,
                ),
                trace_id=result.context.trace_id,
            )
        )
        return ChatContextWindowData(**context.model_dump())

    async def commit(self) -> None:
        """提交完整一轮事务。"""
        await self._db.commit()

    async def rollback(self) -> None:
        """回滚完整一轮事务。"""
        await self._db.rollback()

    async def list_sessions(self, user_id: str) -> list[ChatSessionRecord]:
        """返回用户自己的聊天会话，按最近更新时间排序。"""
        result = await self._db.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.mode == "chat")
            .order_by(Session.updated_at.desc())
        )
        return [self._session_record(item) for item in result.scalars().all()]

    async def rename_session(self, session_id: str, user_id: str, title: str) -> bool:
        """仅重命名指定用户拥有的会话。"""
        session = await self._owned_session(session_id, user_id)
        if session is None:
            return False
        session.title = title
        session.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return True

    async def get_messages(self, session_id: str, user_id: str) -> ChatMessagesPage:
        """读取指定用户会话的完整消息历史。"""
        session = await self._owned_session(session_id, user_id)
        if session is None:
            return ChatMessagesPage(session_id=session_id)
        result = await self._db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.id)
        )
        return ChatMessagesPage(
            session_id=session_id,
            messages=tuple(
                ChatMessageRecord(
                    id=item.id,
                    session_id=item.session_id,
                    role=item.role,
                    content=item.content,
                    is_compressed=bool(item.is_compressed),
                    created_at=item.created_at,
                )
                for item in result.scalars().all()
            ),
            context_window=_context_data(session),
        )

    async def get_summaries(
        self,
        session_id: str,
        user_id: str,
    ) -> list[ChatSummaryRecord]:
        """读取指定用户会话的摘要历史。"""
        if await self._owned_session(session_id, user_id) is None:
            return []
        result = await self._db.execute(
            select(SessionSummary)
            .where(SessionSummary.session_id == session_id)
            .order_by(SessionSummary.created_at.desc())
        )
        return [
            ChatSummaryRecord(
                id=item.id,
                session_id=item.session_id,
                summary=item.summary,
                compressed_message_count=item.compressed_message_count,
                total_message_count=item.total_message_count,
                compressed_user_count=item.compressed_user_count,
                compressed_assistant_count=item.compressed_assistant_count,
                start_message_id=item.start_message_id,
                end_message_id=item.end_message_id,
                start_created_at=item.start_created_at,
                end_created_at=item.end_created_at,
                created_at=item.created_at,
            )
            for item in result.scalars().all()
        ]

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """仅删除指定用户拥有的会话。"""
        session = await self._owned_session(session_id, user_id)
        if session is None:
            return False
        await self._db.delete(session)
        return True

    async def _owned_session(
        self,
        session_id: str | None,
        user_id: str,
        *,
        lock: bool = False,
    ) -> Session | None:
        """按用户读取会话，并可为前台写事务取得行锁。"""
        if not session_id:
            return None
        statement = select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id,
        )
        if lock:
            statement = statement.with_for_update()
        result = await self._db.execute(statement)
        return result.scalar_one_or_none()

    async def _load_memory_profile(self, user_id: str) -> dict[str, object] | None:
        if not settings.enable_memory:
            return None
        result = await self._db.execute(
            select(UserInvestProfile).where(UserInvestProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            return None
        return {
            "risk_level": profile.risk_level,
            "investment_horizon": profile.investment_horizon,
            "expected_return_min": profile.expected_return_min,
            "expected_return_max": profile.expected_return_max,
            "sectors": list(profile.sectors or []),
            "constraints": list(profile.constraints or []),
            "response_pref": profile.response_pref,
        }

    @staticmethod
    def _session_record(session: Session) -> ChatSessionRecord:
        return ChatSessionRecord(
            session_id=session.id,
            mode=session.mode,
            title=session.title,
            running_summary=session.running_summary,
            context_window=_context_data(session),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
