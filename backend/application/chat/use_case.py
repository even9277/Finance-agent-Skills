"""协调受控工作流与最终结果持久化。"""

from __future__ import annotations

from src.conversation.contracts import ConversationRequest, ConversationResult
from src.conversation.ports import ConversationRepositoryPort
from src.conversation.workflow import ControlledConversationWorkflow


class ControlledChatUseCase:
    """Application 层单一聊天用例；M2 尚未接管公开路由。"""

    def __init__(
        self,
        *,
        workflow: ControlledConversationWorkflow,
        repository: ConversationRepositoryPort,
    ) -> None:
        self._workflow = workflow
        self._repository = repository

    async def execute(self, request: ConversationRequest) -> ConversationResult:
        """运行领域工作流并原子保存唯一终态。

        Args:
            request: 已校验的领域请求。

        Returns:
            领域工作流产生并已交给 Repository Port 保存的最终结果。

        Raises:
            Exception: Repository Port 保存失败时向调用方传播，由未来入口事务边界处理。
        """
        result = await self._workflow.run(request)
        await self._repository.save_result(request, result)
        return result
