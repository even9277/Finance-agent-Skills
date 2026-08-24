"""协调受控工作流与一轮聊天事务。"""

from __future__ import annotations

from src.conversation.contracts import ConversationRequest
from src.conversation.workflow import ControlledConversationWorkflow

from .contracts import ChatCommand, ChatOutcome
from .ports import TransactionalConversationRepository


class ControlledChatUseCase:
    """执行公开入口唯一的受控聊天用例。"""

    def __init__(
        self,
        *,
        workflow: ControlledConversationWorkflow,
        repository: TransactionalConversationRepository,
    ) -> None:
        self._workflow = workflow
        self._repository = repository

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
            result = await self._workflow.run(
                request,
                recent_messages=prepared.recent_messages,
                running_summary=prepared.running_summary,
            )
            context_window = await self._repository.save_result(request, result)
            await self._repository.commit()
        except BaseException:
            # CancelledError 不属于 Exception；显式覆盖它才能保证断连无半写。
            await self._repository.rollback()
            raise

        return ChatOutcome(
            reply=result.reply,
            session_id=prepared.session_id,
            status=result.status,
            error_code=result.error_code,
            memory_profile=prepared.memory_profile,
            context_window=context_window,
            workflow_result=result,
        )
