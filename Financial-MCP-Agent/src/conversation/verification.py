"""把工具观察转换为 accepted/rejected Evidence Envelope。"""

from __future__ import annotations

from .contracts import (
    ClaimLevel,
    Entity,
    ErrorCode,
    EvidenceDimension,
    EvidenceEnvelope,
    EvidenceStatus,
    StepStatus,
    ToolObservation,
    VerificationResult,
)


class EvidenceVerifier:
    """按主体、状态和非空事实对 M2 证据进行硬门控。"""

    def verify(
        self,
        *,
        entity: Entity,
        observations: tuple[ToolObservation, ...],
        required_dimensions: tuple[EvidenceDimension, ...],
    ) -> VerificationResult:
        """验收证据并计算缺失维度与允许结论强度。

        Args:
            entity: 当前轮权威实体。
            observations: Executor 归一化后的工具结果。
            required_dimensions: Rewrite/Plan 声明的必需证据。

        Returns:
            只允许 accepted evidence 进入 Synthesis 的验证结果。
        """
        accepted: list[EvidenceEnvelope] = []
        rejected: list[EvidenceEnvelope] = []
        for observation in observations:
            reason: str | None = None
            if observation.status is StepStatus.FAILED:
                reason = (observation.error_code or ErrorCode.TOOL_EXECUTION_FAILED).value
            elif observation.symbol != entity.symbol:
                reason = "ENTITY_MISMATCH"
            elif not observation.facts:
                reason = ErrorCode.TOOL_INVALID_RESULT.value

            envelope = EvidenceEnvelope(
                evidence_id=f"evidence-{observation.step_id}",
                step_id=observation.step_id,
                entity_symbol=observation.symbol,
                evidence_dimension=observation.evidence_dimension,
                facts=observation.facts,
                source=observation.source,
                observed_at=observation.observed_at,
                status=(
                    EvidenceStatus.REJECTED if reason is not None else EvidenceStatus.ACCEPTED
                ),
                rejection_reason=reason,
            )
            if reason is None:
                accepted.append(envelope)
            else:
                rejected.append(envelope)

        accepted_dimensions = {item.evidence_dimension for item in accepted}
        missing = tuple(
            dimension for dimension in required_dimensions if dimension not in accepted_dimensions
        )
        if not missing:
            claim_level = ClaimLevel.CURRENT_FACT
        elif accepted:
            claim_level = ClaimLevel.PARTIAL
        else:
            claim_level = ClaimLevel.NONE
        return VerificationResult(
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            missing_dimensions=missing,
            claim_level=claim_level,
            recoverable=bool(missing) and any(
                item.rejection_reason == ErrorCode.TOOL_TIMEOUT.value for item in rejected
            ),
        )
