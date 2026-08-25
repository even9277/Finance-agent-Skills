"""定义显式用户写入与可恢复删除的权威记忆应用合同。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.memory.contracts import (
    CandidateStatus,
    DerivedConsistencyStatus,
    MemoryRecordStatus,
    MemorySource,
    ProfileField,
    ProfileValue,
)


@dataclass(frozen=True, slots=True)
class AuthorityMutationResult:
    """返回权威写状态及派生索引一致性，不用布尔值掩盖部分完成。"""

    record_id: str
    status: MemoryRecordStatus
    consistency_status: DerivedConsistencyStatus
    version: int
    candidate_status: CandidateStatus | None = None


class AuthoritativeMemoryRepository(Protocol):
    """声明显式记忆写入、确认、拒绝和删除的事务边界。"""

    async def write_profile(
        self,
        *,
        user_id: str,
        field: ProfileField,
        value: ProfileValue,
        source: MemorySource,
        evidence_ref: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult:
        """写入用户确认的结构化画像并同步兼容画像表。"""
        ...

    async def add_text(
        self,
        *,
        user_id: str,
        category: str,
        content: str,
        source: MemorySource,
        evidence_ref: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult:
        """新增一条显式用户文本记忆。"""
        ...

    async def update_text(
        self,
        *,
        user_id: str,
        record_id: str,
        content: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult | None:
        """仅更新当前用户拥有的文本记忆。"""
        ...

    async def delete_record(
        self,
        *,
        user_id: str,
        record_id: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult | None:
        """软删除当前用户拥有的权威记录并返回一致性状态。"""
        ...

    async def confirm_candidate(
        self,
        *,
        user_id: str,
        candidate_id: str,
        trace_id: str | None = None,
    ) -> AuthorityMutationResult | None:
        """把需确认候选经用户动作写入权威记录。"""
        ...
