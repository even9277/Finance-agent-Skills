"""根据 VerificationResult 和冻结预算产生有限控制动作。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.skills.contracts import DegradePolicy

from .contracts import (
    ClaimLevel,
    ControllerAction,
    ControllerDecision,
    ControllerRuntimeState,
    RunBudget,
    TerminalStatus,
    VerificationResult,
)


class RuleController:
    """把证据状态映射为补证、成功、降级或失败，不调用模型。"""

    def decide(
        self,
        verification: VerificationResult,
        *,
        budget: RunBudget,
        runtime: ControllerRuntimeState,
        degrade_policy: DegradePolicy | None = None,
    ) -> ControllerDecision:
        """在冻结 replan 预算内裁定下一动作。

        Args:
            verification: Verifier 的唯一证据结论。
            budget: 本轮不可变运行预算。
            runtime: 已执行补证次数和上一轮缺口。
            degrade_policy: 可选的 Skill 有限降级链；普通数据路由不使用。

        Returns:
            非终态 `REPLAN` 或带唯一终态的停止决定。
        """
        remaining = max(0, budget.max_replans - runtime.replan_count)
        primary_stage, partial_stage, terminal_stage = self._degrade_stages(degrade_policy)
        if verification.claim_level is ClaimLevel.ANALYTICAL:
            return ControllerDecision(
                action=ControllerAction.STOP,
                reason="all required evidence accepted",
                terminal_status=TerminalStatus.SUCCEEDED,
                retries_remaining=0,
                replans_remaining=remaining,
                degrade_stage=primary_stage,
            )
        if verification.recoverable and remaining > 0:
            return ControllerDecision(
                action=ControllerAction.REPLAN,
                reason="required evidence is missing and bounded supplementation remains",
                terminal_status=None,
                retries_remaining=0,
                replans_remaining=remaining,
                degrade_stage=partial_stage,
            )
        if verification.accepted:
            reason = (
                "replan budget exhausted without closing evidence gaps"
                if runtime.replan_count >= budget.max_replans
                else "no safe alternative can add evidence"
            )
            return ControllerDecision(
                action=ControllerAction.RESPOND_PARTIAL,
                reason=reason,
                terminal_status=TerminalStatus.PARTIAL,
                retries_remaining=0,
                replans_remaining=remaining,
                degrade_stage=partial_stage,
            )
        if degrade_policy is not None and degrade_policy.when_missing_evidence == "clarify":
            return ControllerDecision(
                action=ControllerAction.CLARIFY,
                reason="Skill evidence is absent and its degrade policy requires clarification",
                terminal_status=TerminalStatus.NEEDS_CLARIFICATION,
                retries_remaining=0,
                replans_remaining=remaining,
                degrade_stage=terminal_stage,
            )
        return ControllerDecision(
            action=ControllerAction.FAIL,
            reason="no evidence passed verification",
            terminal_status=TerminalStatus.FAILED,
            retries_remaining=0,
            replans_remaining=remaining,
            degrade_stage=terminal_stage,
        )

    @staticmethod
    def _degrade_stages(
        policy: DegradePolicy | None,
    ) -> tuple[str | None, str | None, str | None]:
        """从有终点的 Skill 降级链提取主、部分和终止阶段。"""
        if policy is None:
            return None, None, None
        primary = policy.stages[0].name
        partial = policy.stages[0].next_stage
        if partial in {None, "none"}:
            partial = primary
        terminal = next(
            (
                stage.name
                for stage in reversed(policy.stages)
                if stage.next_stage in {None, "none"}
            ),
            policy.stages[-1].name,
        )
        return primary, partial, terminal
