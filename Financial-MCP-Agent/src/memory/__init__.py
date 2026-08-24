"""记忆领域入口。

当前 M2 只冻结 typed contracts、权威策略和 PostgreSQL 事务 Outbox 基础。
历史 ``MemoryService`` 仍为未迁移调用方保留，但不是新主链的唯一入口；新代码通过
application port 与 infrastructure repository 访问权威状态。Mem0/pgvector 同步和
长期记忆治理尚未启用，分别由后续里程碑实现。
"""

from .contracts import MEMORY_POLICY_VERSION, MEMORY_SCHEMA_VERSION, WorkingState
from .memory_service import MemoryService
from .policy import requires_user_confirmation

__all__ = [
    "MEMORY_POLICY_VERSION",
    "MEMORY_SCHEMA_VERSION",
    "MemoryService",
    "WorkingState",
    "requires_user_confirmation",
]
