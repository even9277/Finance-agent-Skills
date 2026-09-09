"""定义受控对话领域边界可稳定识别的异常。"""

from __future__ import annotations


class ConversationError(Exception):
    """受控对话领域异常的基类。"""


class ContractViolationError(ConversationError, ValueError):
    """输入或跨阶段对象违反已冻结合同。"""


class StateTransitionError(ConversationError, RuntimeError):
    """状态机发生越级、回退或重复终止。"""


class ToolTransientError(ConversationError, RuntimeError):
    """只读 Provider 的限流、连接抖动等可重试瞬时错误。"""


class ToolRateLimitError(ToolTransientError):
    """Provider 或本地配额拒绝调用，并可携带安全 Retry-After。"""

    def __init__(self, message: str, *, retry_after_ms: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class ToolCircuitOpenError(ToolTransientError):
    """工具熔断器拒绝调用；Executor 不得继续撞击下游。"""


class ToolPermanentError(ConversationError, RuntimeError):
    """参数、权限或稳定下游拒绝等不可重试工具错误。"""


class ToolTimeoutError(ToolTransientError, TimeoutError):
    """只读工具在单次调用预算内发生瞬时超时。"""


class StepBudgetExceededError(ConversationError, RuntimeError):
    """工作流在到达终态前耗尽允许的阶段事件预算。"""


class ModelSynthesisError(ConversationError, RuntimeError):
    """模型增量生成失败；该技术异常必须越过业务终态并触发事务回滚。"""


class EntityResolutionError(ConversationError, RuntimeError):
    """实体解析外部边界无法完成受控候选或目录校验。"""


class EntityModelUnavailableError(EntityResolutionError):
    """实体模型超时、限流或不可用，且不得泄露供应商异常原文。"""

    def __init__(
        self,
        message: str,
        *,
        model_calls: int = 0,
        repair_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.model_calls = model_calls
        self.repair_count = repair_count


class EntityModelContractError(EntityResolutionError):
    """实体模型在有界语法修复后仍不满足严格输出合同。"""

    def __init__(
        self,
        message: str,
        *,
        model_calls: int = 0,
        repair_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.model_calls = model_calls
        self.repair_count = repair_count


class EntityCatalogUnavailableError(EntityResolutionError):
    """权威实体目录不可用，长尾候选不得绕过校验。"""


class PersistenceError(ConversationError, RuntimeError):
    """应用层无法原子保存本轮最终结果。"""
