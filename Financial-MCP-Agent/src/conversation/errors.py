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


class ToolPermanentError(ConversationError, RuntimeError):
    """参数、权限或稳定下游拒绝等不可重试工具错误。"""


class ToolTimeoutError(ToolTransientError, TimeoutError):
    """只读工具在单次调用预算内发生瞬时超时。"""


class StepBudgetExceededError(ConversationError, RuntimeError):
    """工作流在到达终态前耗尽允许的阶段事件预算。"""


class PersistenceError(ConversationError, RuntimeError):
    """应用层无法原子保存本轮最终结果。"""
