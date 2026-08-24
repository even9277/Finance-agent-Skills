"""根据 VerificationResult 和冻结预算产生有限控制动作。"""

from __future__ import annotations

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
    ) -> ControllerDecision:
        """在冻结 replan 预算内裁定下一动作。

        Args:
            verification: Verifier 的唯一证据结论。
            budget: 本轮不可变运行预算。
            runtime: 已执行补证次数和上一轮缺口。

        Returns:
            非终态 `REPLAN` 或带唯一终态的停止决定。
        """
        remaining = max(0, budget.max_replans - runtime.replan_count)
        if verification.claim_level is ClaimLevel.ANALYTICAL:
            return ControllerDecision(
                action=ControllerAction.STOP,
                reason="all required evidence accepted",
                terminal_status=TerminalStatus.SUCCEEDED,
                retries_remaining=0,
                replans_remaining=remaining,
            )
        if verification.recoverable and remaining > 0:
            return ControllerDecision(
                action=ControllerAction.REPLAN,
                reason="required evidence is missing and bounded supplementation remains",
                terminal_status=None,
                retries_remaining=0,
                replans_remaining=remaining,
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
            )
        return ControllerDecision(
            action=ControllerAction.FAIL,
            reason="no evidence passed verification",
            terminal_status=TerminalStatus.FAILED,
            retries_remaining=0,
            replans_remaining=remaining,
        )
