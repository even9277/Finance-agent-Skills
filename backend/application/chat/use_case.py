"""协调受控工作流与一轮聊天事务。"""

from __future__ import annotations

import logging

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
from .contracts import ChatCommand, ChatOutcome
from .ports import TransactionalConversationRepository

logger = logging.getLogger(__name__)


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
        try:
            prepared = await self._repository.prepare_turn(command)
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
                    await self._repository.commit()
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
                    return ChatOutcome(
                        reply=memory_result.user_message,
                        session_id=prepared.session_id,
                        status=terminal_status,
                        memory_profile=prepared.memory_profile,
                        working_state=prepared.working_state,
                        memory_command=memory_result,
                    )
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
            # 未启用 M6 时不向旧的测试替身/兼容 Port 传递新增关键字，保持边界兼容。
            if self._retrieval is not None:
                workflow_kwargs["memory_context"] = memory_context
            result = await self._workflow.run(request, **workflow_kwargs)
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
