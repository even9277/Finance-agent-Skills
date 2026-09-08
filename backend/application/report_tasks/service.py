"""编排报告任务幂等材料与数据库权威创建用例。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.application.report_tasks.contracts import (
    ReportTaskClaim,
    ReportTaskCreateResult,
    build_effective_idempotency_material,
    build_report_request_fingerprint,
    build_scoped_idempotency_digest,
)
from backend.application.report_tasks.ports import ReportTaskClaimRepository


class ReportTaskCreationService:
    """把公开请求收敛为低敏声明并交给 PostgreSQL 权威层。"""

    def __init__(
        self,
        repository: ReportTaskClaimRepository,
        *,
        digest_secret: str,
        ttl_seconds: int = 600,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds 必须为正整数")
        self._repository = repository
        self._digest_secret = digest_secret
        self._ttl_seconds = ttl_seconds

    async def create_or_reuse(
        self,
        *,
        user_id: str,
        command: str,
        client_key: str | None,
    ) -> ReportTaskCreateResult:
        """创建或复用同一用户意图对应的报告任务。

        Args:
            user_id: 已完成认证所有权校验的内部用户标识。
            command: 报告分析指令，仅用于生成不可逆指纹。
            client_key: 可选显式请求键；缺省时兼容命令哈希语义。

        Returns:
            数据库确认的唯一任务、报告、代次和幂等结果。

        Raises:
            ReportIdempotencyValidationError: 显式键不满足公开合同。
            ReportIdempotencyConflictError: 同一键已绑定其他请求指纹。
        """
        now = datetime.now(UTC)
        request_fingerprint = build_report_request_fingerprint(command)
        effective_material = build_effective_idempotency_material(command, client_key)
        key_digest = build_scoped_idempotency_digest(
            user_id=user_id,
            effective_material=effective_material,
            secret=self._digest_secret,
        )
        claim = ReportTaskClaim(
            user_id=user_id,
            key_digest=key_digest,
            request_fingerprint=request_fingerprint,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        return await self._repository.create_or_reuse(claim)
