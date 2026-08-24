"""实现受控聊天和会话管理的 SQLAlchemy Repository。"""

from __future__ import annotations

import asyncio
import logging
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
from backend.application.memory.context import ContextBudgetPolicy, ContextTextItem
from backend.application.memory.cache import (
    CacheLookupStatus,
    CachedCompactProfile,
    CachedConversationContext,
    MemoryHotCache,
)
from backend.application.memory.ports import TransactionalMemoryRepository
from backend.config import settings
from backend.application.memory.summary import SUMMARY_PROMPT_VERSION
from backend.db.models import (
    MemoryOutboxTaskRow,
    Message,
    Session,
    SessionSummary,
    UserInvestProfile,
)
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
    OutboxTaskStatus,
    SummaryCompactPayload,
    TurnCommittedPayload,
    WorkingState,
    build_summary_outbox_key,
    build_turn_outbox_key,
)

logger = logging.getLogger(__name__)


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
        cache: MemoryHotCache | None = None,
    ) -> None:
        self._db = db
        self._cache = cache
        self._prepared_sessions: dict[str, Session] = {}
        self._prepared_user_ids: dict[str, str] = {}
        self._prepared_user_message_ids: dict[str, int] = {}
        self._prepared_working_states: dict[str, WorkingState] = {}
        self._prepared_contexts: dict[str, CachedConversationContext] = {}
        self._memory = memory_repository or SqlAlchemyMemoryRepository(db, cache=cache)

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

        context_snapshot = await self._load_context_snapshot(
            user_id=command.user_id,
            session=session,
        )
        packed = ContextBudgetPolicy(
            model_window_tokens=max(1, int(settings.stm_context_budget_tokens)),
            output_reserve_tokens=max(0, int(settings.stm_response_reserve_tokens)),
            safety_margin_tokens=max(
                0,
                int(settings.stm_context_safety_margin_tokens),
            ),
            stage_overhead_tokens=max(0, int(settings.stm_stage_overhead_tokens)),
        ).pack(
            current_message=command.message,
            recent_messages=tuple(
                ContextTextItem(
                    message_id=index,
                    text=text,
                )
                for index, text in enumerate(context_snapshot.recent_messages, start=1)
            ),
            running_summary=context_snapshot.running_summary,
        )
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
        self._prepared_user_ids[session.id] = command.user_id
        self._prepared_user_message_ids[session.id] = user_message.id
        self._prepared_working_states[session.id] = working_state
        self._prepared_contexts[session.id] = CachedConversationContext(
            turn_count=context_snapshot.turn_count,
            summary_version=context_snapshot.summary_version,
            running_summary=context_snapshot.running_summary,
            recent_messages=self._trim_context_messages(
                (*context_snapshot.recent_messages, f"user: {command.message}")
            ),
        )

        return PreparedChatTurn(
            session_id=session.id,
            recent_messages=tuple(item.text for item in packed.recent_messages),
            running_summary=packed.running_summary,
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
        prepared_context = self._prepared_contexts.get(session.id)
        if prepared_context is not None:
            self._prepared_contexts[session.id] = CachedConversationContext(
                turn_count=int(session.turn_count or 0),
                summary_version=int(session.summary_version or 0),
                running_summary=session.running_summary,
                recent_messages=self._trim_context_messages(
                    (*prepared_context.recent_messages, f"assistant: {result.reply}")
                ),
            )
        return ChatContextWindowData(**context.model_dump())

    async def apply_working_state(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> WorkingState:
        """在前台事务中以 CAS 暂存本轮状态和字段审计事件。"""
        current = self._prepared_working_states.get(request.session_id)
        source_message_id = self._prepared_user_message_ids.get(request.session_id)
        if current is None or source_message_id is None:
            raise RuntimeError("prepared working-state context is missing")
        if result.working_state_update is None:
            return current
        transition = await self._memory.apply_working_state(
            current=current,
            update=result.working_state_update,
            session_id=request.session_id,
            source_message_id=source_message_id,
            trace_id=result.context.trace_id,
        )
        self._prepared_working_states[request.session_id] = transition.state
        return transition.state

    async def maybe_enqueue_compaction(
        self,
        request: ConversationRequest,
        result: ConversationResult,
    ) -> bool:
        """按预算与 protected tail 幂等暂存 Rolling Summary 任务。

        该方法只在前台轮次已经提交后调用。失败会由 Application 回滚这次
        后台排队事务，不能影响已经返回所需的聊天结果。
        """
        if not settings.enable_stm:
            return False
        session = await self._owned_session(request.session_id, request.user_id, lock=True)
        if session is None:
            raise RuntimeError("committed chat session is missing")
        await refresh_session_context_metrics(self._db, session)

        messages = list(
            (
                await self._db.execute(
                    select(Message)
                    .where(
                        Message.session_id == request.session_id,
                        Message.is_compressed.is_(False),
                    )
                    .order_by(Message.id)
                )
            )
            .scalars()
            .all()
        )
        if not self._should_compact(session, len(messages)):
            return False
        keep_recent = max(1, int(settings.stm_keep_recent))
        if len(messages) <= keep_recent:
            return False

        active_task = await self._db.scalar(
            select(MemoryOutboxTaskRow.id).where(
                MemoryOutboxTaskRow.session_id == request.session_id,
                MemoryOutboxTaskRow.task_kind == OutboxTaskKind.SUMMARY_COMPACT.value,
                MemoryOutboxTaskRow.status.in_(
                    (
                        OutboxTaskStatus.PENDING.value,
                        OutboxTaskStatus.PROCESSING.value,
                        OutboxTaskStatus.RETRY.value,
                    )
                ),
            )
        )
        if active_task is not None:
            return False

        source_messages = messages[:-keep_recent]
        protected_tail = messages[-keep_recent:]
        payload = SummaryCompactPayload(
            session_id=request.session_id,
            expected_summary_version=int(session.summary_version or 0),
            source_start_message_id=source_messages[0].id,
            source_end_message_id=source_messages[-1].id,
            source_message_count=len(source_messages),
            protected_tail_start_message_id=protected_tail[0].id,
            input_token_estimate=sum(
                max(0, int(message.token_count or 0)) for message in source_messages
            ),
            prompt_version=SUMMARY_PROMPT_VERSION,
        )
        await self._memory.enqueue_outbox(
            NewOutboxTask(
                user_id=request.user_id,
                session_id=request.session_id,
                aggregate_type="chat_session",
                aggregate_id=request.session_id,
                task_kind=OutboxTaskKind.SUMMARY_COMPACT,
                idempotency_key=build_summary_outbox_key(
                    request.session_id,
                    payload.expected_summary_version,
                    payload.source_end_message_id,
                ),
                payload=payload,
                trace_id=result.context.trace_id,
            )
        )
        session.compression_status = "queued"
        return True

    @staticmethod
    def _should_compact(session: Session, uncompressed_count: int) -> bool:
        """按配置策略判断是否达到压缩水位，不执行外部调用。"""
        if settings.stm_compression_strategy == "legacy_count":
            return uncompressed_count >= int(settings.stm_legacy_count_threshold)
        budget = max(1, int(session.context_budget_tokens or settings.stm_context_budget_tokens))
        projected = (
            int(session.context_token_count or 0)
            + int(settings.stm_response_reserve_tokens)
            + int(settings.stm_memory_reserve_tokens)
        )
        return projected >= int(round(budget * float(settings.stm_context_target_ratio)))

    async def commit(self) -> None:
        """提交完整一轮事务，并在成功后发布可丢弃缓存快照。"""
        await self._db.commit()
        if self._cache is None:
            return
        try:
            for session_id, user_id in tuple(self._prepared_user_ids.items()):
                context = self._prepared_contexts.get(session_id)
                state = self._prepared_working_states.get(session_id)
                if context is not None:
                    await self._cache.set_context(user_id, session_id, context)
                if state is not None:
                    await self._cache.set_working_state(user_id, session_id, state)
        except Exception as exc:
            # 权威事务已经提交；缓存实现缺陷也不能把成功轮次伪装成失败。
            logger.warning(
                "memory_cache_publish_failed stage=%s status=%s error_code=%s "
                "error_type=%s",
                "memory.cache.publish",
                "DEGRADED",
                "UNAVAILABLE",
                type(exc).__name__,
            )
        finally:
            self._prepared_user_ids.clear()
            self._prepared_contexts.clear()

    async def rollback(self) -> None:
        """回滚完整一轮事务。"""
        await self._db.rollback()
        self._prepared_user_ids.clear()
        self._prepared_contexts.clear()

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
        profile_version = await self._db.scalar(
            select(UserInvestProfile.updated_at).where(UserInvestProfile.user_id == user_id)
        )
        if profile_version is None:
            return None
        version = profile_version.isoformat(timespec="microseconds")
        if self._cache is not None:
            cached = await self._cache.get_profile(
                user_id,
                expected_profile_version=version,
            )
            if cached.status is CacheLookupStatus.HIT and cached.value is not None:
                return cached.value.as_chat_mapping()
        result = await self._db.execute(
            select(UserInvestProfile).where(UserInvestProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            return None
        cached_profile = CachedCompactProfile(
            profile_version=version,
            risk_level=profile.risk_level,
            investment_horizon=profile.investment_horizon,
            expected_return_min=profile.expected_return_min,
            expected_return_max=profile.expected_return_max,
            sectors=tuple(profile.sectors or []),
            constraints=tuple(profile.constraints or []),
            response_pref=profile.response_pref,
        )
        if self._cache is not None:
            await self._cache.set_profile(user_id, cached_profile)
        return cached_profile.as_chat_mapping()

    async def _load_context_snapshot(
        self,
        *,
        user_id: str,
        session: Session,
    ) -> CachedConversationContext:
        """按权威会话版本 cache-aside 读取未压缩尾窗和摘要。"""
        expected_turn_count = int(session.turn_count or 0)
        expected_summary_version = int(session.summary_version or 0)
        lease_token: str | None = None
        if self._cache is not None:
            cached = await self._cache.get_context(
                user_id,
                session.id,
                expected_turn_count=expected_turn_count,
                expected_summary_version=expected_summary_version,
            )
            if cached.status is CacheLookupStatus.HIT and cached.value is not None:
                return cached.value
            if cached.status is not CacheLookupStatus.DEGRADED:
                lease_token = await self._cache.acquire_fill_lease(
                    "context", user_id, session.id
                )
                if lease_token is None:
                    # 只等待一个极短、配置化窗口；超时后各自回源以保证前台可用。
                    await asyncio.sleep(self._cache.config.singleflight_wait_ms / 1000)
                    retry = await self._cache.get_context(
                        user_id,
                        session.id,
                        expected_turn_count=expected_turn_count,
                        expected_summary_version=expected_summary_version,
                    )
                    if retry.status is CacheLookupStatus.HIT and retry.value is not None:
                        return retry.value

        try:
            history_result = await self._db.execute(
                select(Message)
                .where(Message.session_id == session.id, Message.is_compressed.is_(False))
                .order_by(Message.id.desc())
                .limit(max(1, int(settings.stm_keep_recent)))
            )
            recent = list(reversed(list(history_result.scalars().all())))
            snapshot = CachedConversationContext(
                turn_count=expected_turn_count,
                summary_version=expected_summary_version,
                running_summary=session.running_summary,
                recent_messages=tuple(f"{item.role}: {item.content}" for item in recent),
            )
            if self._cache is not None and session.id and expected_turn_count > 0:
                await self._cache.set_context(user_id, session.id, snapshot)
            return snapshot
        finally:
            if self._cache is not None and lease_token is not None:
                await self._cache.release_fill_lease(
                    "context", user_id, session.id, lease_token
                )

    @staticmethod
    def _trim_context_messages(messages: tuple[str, ...]) -> tuple[str, ...]:
        """保持与数据库读取相同的 protected-tail 条数上限。"""
        keep_recent = max(1, int(settings.stm_keep_recent))
        return messages[-keep_recent:]

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
