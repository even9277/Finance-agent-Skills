"""协调受控工作流与一轮聊天事务。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import dataclass, replace

from src.conversation.contracts import ConversationRequest, MemoryContextItem
from src.conversation.workflow import ControlledConversationWorkflow

from backend.application.memory.retrieval import MemoryRetrievalRequest, MemoryRetrievalUseCase
from backend.application.memory.commands import MemoryCommandUseCase, parse_memory_command
from backend.application.memory.observability import (
    MemoryObservation,
    MemoryObserver,
    MemoryStage,
    MemoryStatus,
    emit_memory_observation,
)
from src.conversation.contracts import TerminalStatus
from .contracts import (
    ChatCommand,
    ChatContentDelta,
    ChatOutcome,
    ChatStreamCompleted,
    ChatStreamEvent,
    ChatStreamFailed,
    ChatStreamFailureCode,
    ChatStreamStarted,
)
from .ports import TransactionalConversationRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _QueuedChatStreamEvent:
    """把一个应用事件与消费端发送完成确认绑定。"""

    event: ChatStreamEvent
    acknowledged: asyncio.Future[None]


class _ChatStreamObserver:
    """在单轮事务内累计增量，并把传输背压传播回模型。"""

    def __init__(self, *, request_id: str, initial_session_id: str | None) -> None:
        self.request_id = request_id
        self.session_id = initial_session_id or "unavailable"
        self.queue: asyncio.Queue[_QueuedChatStreamEvent] = asyncio.Queue(maxsize=1)
        self.started_at = time.perf_counter()
        self.first_delta_at: float | None = None
        self._chunks: list[str] = []

    @property
    def chunk_count(self) -> int:
        """返回已被应用层接受的内容增量数。"""
        return len(self._chunks)

    @property
    def reply(self) -> str:
        """按原始顺序重建当前已发送回答。"""
        return "".join(self._chunks)

    @property
    def content_sha256(self) -> str:
        """返回不暴露正文的最终内容哈希。"""
        return hashlib.sha256(self.reply.encode("utf-8")).hexdigest()

    @property
    def ttft_ms(self) -> float | None:
        """返回从应用流启动到首个 delta 的毫秒耗时。"""
        if self.first_delta_at is None:
            return None
        return (self.first_delta_at - self.started_at) * 1000

    @property
    def elapsed_ms(self) -> float:
        """返回应用流启动后的总毫秒耗时。"""
        return (time.perf_counter() - self.started_at) * 1000

    async def on_started(self, session_id: str) -> None:
        """在 Repository 准备事务会话后发出唯一开始事件。"""
        self.session_id = session_id
        await self.emit(ChatStreamStarted(session_id=session_id, request_id=self.request_id))

    async def on_content_delta(self, content: str) -> None:
        """记录非空增量，并等待消费端确认已完成发送。"""
        if not content:
            return
        if self.first_delta_at is None:
            self.first_delta_at = time.perf_counter()
        self._chunks.append(content)
        await self.emit(
            ChatContentDelta(
                session_id=self.session_id,
                request_id=self.request_id,
                content=content,
                chunk_index=self.chunk_count,
            )
        )

    def validate_reply(self, reply: str) -> None:
        """在持久化前确认公开增量与权威终态正文完全一致。"""
        if self.reply != reply:
            raise RuntimeError("streamed reply does not match workflow result")

    async def emit(self, event: ChatStreamEvent) -> None:
        """发送一个事件并等待下一次消费，以形成端到端背压。"""
        acknowledged = asyncio.get_running_loop().create_future()
        await self.queue.put(_QueuedChatStreamEvent(event=event, acknowledged=acknowledged))
        await acknowledged


class ControlledChatUseCase:
    """执行公开入口唯一的受控聊天用例。"""

    def __init__(
        self,
        *,
        workflow: ControlledConversationWorkflow,
        repository: TransactionalConversationRepository,
        retrieval: MemoryRetrievalUseCase | None = None,
        retrieval_top_k: int = 8,
        retrieval_token_budget: int = 600,
        memory_commands: MemoryCommandUseCase | None = None,
        memory_observer: MemoryObserver | None = None,
    ) -> None:
        self._workflow = workflow
        self._repository = repository
        self._retrieval = retrieval
        self._retrieval_top_k = retrieval_top_k
        self._retrieval_token_budget = retrieval_token_budget
        self._memory_commands = memory_commands
        # 生产工厂显式注入 Trace Sink；测试替身不自动产生旁路事件，避免改变旧 Trace 合同。
        self._memory_observer = memory_observer

    async def execute(self, command: ChatCommand) -> ChatOutcome:
        """运行领域工作流并原子保存唯一终态。

        Args:
            command: 由 REST 或 WebSocket 边界构造的协议无关命令。

        Returns:
            两种公开协议共同消费的应用输出。

        Raises:
            BaseException: 工作流、持久化或取消异常会在回滚后原样传播。
        """
        return await self._execute(command)

    async def stream(self, command: ChatCommand) -> AsyncGenerator[ChatStreamEvent, None]:
        """通过同一执行核心产生带背压的协议无关流式事件。

        Args:
            command: 由 WebSocket 边界构造的聊天命令；缺少 request_id 时在此补全。

        Yields:
            Started、零到多个 ContentDelta，以及唯一 Completed 或 Failed 终态。

        Raises:
            asyncio.CancelledError: 消费端中止时取消运行任务，并由执行核心回滚未提交事务。
        """
        effective_command = (
            command
            if command.request_id
            else replace(command, request_id=f"req_{uuid.uuid4().hex}")
        )
        request_id = effective_command.request_id
        if request_id is None:  # pragma: no cover - replace 分支保证非空
            raise RuntimeError("stream request_id is unavailable")
        observer = _ChatStreamObserver(
            request_id=request_id,
            initial_session_id=effective_command.session_id,
        )

        async def run_execution() -> None:
            try:
                outcome = await self._execute(effective_command, stream_observer=observer)
                await observer.emit(
                    ChatStreamCompleted(
                        session_id=outcome.session_id,
                        request_id=request_id,
                        outcome=outcome,
                        chunk_count=observer.chunk_count,
                        content_sha256=observer.content_sha256,
                        ttft_ms=observer.ttft_ms,
                        elapsed_ms=observer.elapsed_ms,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "chat.stream.failed request_id=%s session_id=%s stage=%s status=%s "
                    "error_code=%s error_type=%s elapsed_ms=%.2f chunk_count=%d",
                    request_id,
                    observer.session_id,
                    "chat.stream",
                    "FAILED",
                    "CHAT_STREAM_FAILED",
                    type(exc).__name__,
                    observer.elapsed_ms,
                    observer.chunk_count,
                )
                await observer.emit(
                    ChatStreamFailed(
                        session_id=observer.session_id,
                        request_id=request_id,
                        error_code=ChatStreamFailureCode.STREAM_FAILED,
                        chunk_count=observer.chunk_count,
                        ttft_ms=observer.ttft_ms,
                        elapsed_ms=observer.elapsed_ms,
                    )
                )

        execution_task = asyncio.create_task(run_execution())
        try:
            while not execution_task.done() or not observer.queue.empty():
                receive_task = asyncio.create_task(observer.queue.get())
                done, _ = await asyncio.wait(
                    {execution_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receive_task in done:
                    queued = receive_task.result()
                    try:
                        yield queued.event
                    except GeneratorExit:
                        raise
                    else:
                        if not queued.acknowledged.done():
                            queued.acknowledged.set_result(None)
                    continue

                receive_task.cancel()
                with suppress(asyncio.CancelledError):
                    await receive_task
                await execution_task
        finally:
            if not execution_task.done():
                execution_task.cancel()
            with suppress(asyncio.CancelledError):
                await execution_task

    async def _execute(
        self,
        command: ChatCommand,
        *,
        stream_observer: _ChatStreamObserver | None = None,
    ) -> ChatOutcome:
        """运行共享聊天核心，并在流式模式下把提交受发送确认约束。"""
        try:
            prepared = await self._repository.prepare_turn(command)
            if stream_observer is not None:
                await stream_observer.on_started(prepared.session_id)
            self._observe(
                MemoryStage.PREFLIGHT,
                MemoryStatus.SUCCEEDED,
                trace_id=command.request_id or "chat-preflight",
                run_id=prepared.session_id,
            )
            if self._memory_commands is not None:
                intent = parse_memory_command(
                    command.message,
                    user_id=command.user_id,
                    session_id=prepared.session_id,
                )
                if intent is not None:
                    memory_result = await self._memory_commands.execute(intent)
                    command_stage = (
                        MemoryStage.DELETE
                        if intent.kind.value in {"DELETE", "FORGET", "CONFIRM"}
                        else MemoryStage.MUTATE
                    )
                    command_status = (
                        MemoryStatus.SUCCEEDED
                        if memory_result.status.value == "SUCCEEDED"
                        else MemoryStatus.REJECTED
                        if memory_result.status.value in {"REJECTED", "CANCELLED"}
                        else MemoryStatus.PARTIAL
                    )
                    self._observe(
                        command_stage,
                        command_status,
                        trace_id=command.request_id or intent.fingerprint[:16],
                        run_id=prepared.session_id,
                        reference=memory_result.command_ref,
                        affected_count=memory_result.affected_count,
                        error_code=memory_result.error_code,
                    )
                    terminal_status = _terminal_status_for_memory(memory_result.status.value)
                    outcome = ChatOutcome(
                        reply=memory_result.user_message,
                        session_id=prepared.session_id,
                        status=terminal_status,
                        memory_profile=prepared.memory_profile,
                        working_state=prepared.working_state,
                        memory_command=memory_result,
                    )
                    if stream_observer is not None and outcome.reply:
                        await stream_observer.on_content_delta(outcome.reply)
                        stream_observer.validate_reply(outcome.reply)
                    await self._repository.commit()
                    return outcome
            request = ConversationRequest(
                user_id=command.user_id,
                session_id=prepared.session_id,
                message=command.message,
                request_id=command.request_id,
                explicit_skill=command.explicit_skill,
            )
            memory_context: tuple[MemoryContextItem, ...] = ()
            if self._retrieval is not None:
                try:
                    retrieval_result = await self._retrieval.execute(
                        MemoryRetrievalRequest(
                            user_id=command.user_id,
                            query=command.message,
                            top_k=self._retrieval_top_k,
                            token_budget=self._retrieval_token_budget,
                        )
                    )
                    self._observe(
                        MemoryStage.RETRIEVE,
                        _retrieval_memory_status(retrieval_result.status.value),
                        trace_id=command.request_id or "chat-retrieval",
                        run_id=prepared.session_id,
                        affected_count=len(retrieval_result.items),
                        error_code=(
                            retrieval_result.error_code.value
                            if retrieval_result.error_code is not None
                            else None
                        ),
                    )
                    memory_context = tuple(
                        MemoryContextItem(
                            record_id=item.record_id,
                            category=item.category,
                            content=item.content,
                            score=item.score,
                            retrieval_reasons=item.retrieval_reasons,
                            memory_version=item.memory_version,
                        )
                        for item in retrieval_result.items
                    )
                    self._observe(
                        MemoryStage.INJECT,
                        MemoryStatus.SUCCEEDED if memory_context else MemoryStatus.SKIPPED,
                        trace_id=command.request_id or "chat-inject",
                        run_id=prepared.session_id,
                        affected_count=len(memory_context),
                    )
                except Exception as exc:
                    # 召回是增强能力；权威对话链必须在索引故障时继续运行。
                    logger.warning(
                        "memory.retrieval_failed stage=%s status=%s error_code=%s error_type=%s",
                        "memory.retrieval",
                        "DEGRADED",
                        "PROVIDER_UNAVAILABLE",
                        type(exc).__name__,
                    )
                    self._observe(
                        MemoryStage.RETRIEVE,
                        MemoryStatus.DEGRADED,
                        trace_id=command.request_id or "chat-retrieval",
                        run_id=prepared.session_id,
                        error_code="PROVIDER_UNAVAILABLE",
                    )
            workflow_kwargs = {
                "recent_messages": prepared.recent_messages,
                "running_summary": prepared.running_summary,
                "working_state": prepared.working_state,
            }
            # 仅注入当前运行实际启用的增强上下文和流式接收器，保持单一执行核心。
            if self._retrieval is not None:
                workflow_kwargs["memory_context"] = memory_context
            if stream_observer is not None:
                workflow_kwargs["on_content_delta"] = stream_observer.on_content_delta
            result = await self._workflow.run(request, **workflow_kwargs)
            if stream_observer is not None:
                if stream_observer.chunk_count == 0 and result.reply:
                    await stream_observer.on_content_delta(result.reply)
                stream_observer.validate_reply(result.reply)
            working_state = await self._repository.apply_working_state(request, result)
            context_window = await self._repository.save_result(request, result)
            await self._repository.commit()
        except BaseException:
            # CancelledError 不属于 Exception；显式覆盖它才能保证断连无半写。
            await self._repository.rollback()
            raise

        # 摘要排队属于已提交轮次的后台增强；失败只能降级，不能反转前台回答。
        try:
            queued = await self._repository.maybe_enqueue_compaction(request, result)
            if queued:
                await self._repository.commit()
        except Exception as exc:
            await self._repository.rollback()
            logger.warning(
                "memory.compaction_enqueue_failed trace_id=%s stage=%s status=%s "
                "error_code=%s error_type=%s",
                result.context.trace_id,
                "memory.compact",
                "FAILED",
                "INTERNAL_ERROR",
                type(exc).__name__,
            )

        return ChatOutcome(
            reply=result.reply,
            session_id=prepared.session_id,
            status=result.status,
            error_code=result.error_code,
            memory_profile=prepared.memory_profile,
            working_state=working_state,
            context_window=context_window,
            workflow_result=result,
            skill_confirmation=result.skill_confirmation,
        )

    def _observe(
        self,
        stage: MemoryStage,
        status: MemoryStatus,
        *,
        trace_id: str,
        run_id: str,
        reference: str | None = None,
        affected_count: int = 0,
        error_code: object | None = None,
    ) -> None:
        """发送旁路观测；任何适配器异常都不能影响聊天事务。"""
        if self._memory_observer is None:
            return
        emit_memory_observation(
            MemoryObservation(
                stage=stage,
                status=status,
                trace_id=trace_id,
                run_id=run_id,
                reference=reference,
                affected_count=affected_count,
                error_code=_error_code_text(error_code),
            ),
            observer=self._memory_observer,
        )


def _terminal_status_for_memory(status: str) -> TerminalStatus:
    """把记忆命令状态映射为受控聊天终态，保证命令分支立即结束。"""
    if status == "SUCCEEDED":
        return TerminalStatus.SUCCEEDED
    if status in {"PARTIAL"}:
        return TerminalStatus.PARTIAL
    if status in {"REJECTED", "CANCELLED", "EXPIRED"}:
        return TerminalStatus.REJECTED if status != "CANCELLED" else TerminalStatus.CANCELLED
    if status in {"CONFIRMATION_REQUIRED", "PENDING"}:
        return TerminalStatus.NEEDS_CLARIFICATION
    return TerminalStatus.FAILED


def _retrieval_memory_status(status: str) -> MemoryStatus:
    """把召回领域状态映射为统一记忆观测状态。"""
    if status == "SUCCEEDED":
        return MemoryStatus.SUCCEEDED
    if status in {"EMPTY", "PARTIAL"}:
        return MemoryStatus.PARTIAL
    return MemoryStatus.FAILED


def _error_code_text(error_code: object | None) -> str | None:
    """把领域枚举或字符串错误码收敛为安全文本。"""
    if error_code is None:
        return None
    value = getattr(error_code, "value", error_code)
    return str(value)
