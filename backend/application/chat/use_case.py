"""协调受控工作流与一轮聊天事务。"""

from __future__ import annotations

import logging

from src.conversation.contracts import ConversationRequest, MemoryContextItem
from src.conversation.workflow import ControlledConversationWorkflow

from backend.application.memory.retrieval import MemoryRetrievalRequest, MemoryRetrievalUseCase
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
    ) -> None:
        self._workflow = workflow
        self._repository = repository
        self._retrieval = retrieval
        self._retrieval_top_k = retrieval_top_k
        self._retrieval_token_budget = retrieval_token_budget

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
                except Exception as exc:
                    # 召回是增强能力；权威对话链必须在索引故障时继续运行。
                    logger.warning(
                        "memory.retrieval_failed stage=%s status=%s error_code=%s error_type=%s",
                        "memory.retrieval",
                        "DEGRADED",
                        "PROVIDER_UNAVAILABLE",
                        type(exc).__name__,
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
