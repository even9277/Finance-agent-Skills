"""根据 VerificationResult 产生有限且可证明终止的动作。"""

from __future__ import annotations

from .contracts import (
    ClaimLevel,
    ControllerAction,
    ControllerDecision,
    ConversationRunContext,
    TerminalStatus,
    VerificationResult,
)


class RuleController:
    """M2 不重规划，只在完整、部分和失败终态间做确定性选择。"""

    def decide(
        self,
        verification: VerificationResult,
        context: ConversationRunContext,
    ) -> ControllerDecision:
        """根据 accepted/missing evidence 决定唯一终态。

        Args:
            verification: Verifier 输出。
            context: 用于报告冻结的剩余预算。

        Returns:
            不会返回隐式循环动作的控制决定。
        """
        if verification.claim_level is ClaimLevel.CURRENT_FACT:
            return ControllerDecision(
                action=ControllerAction.STOP,
                reason="all required evidence accepted",
                terminal_status=TerminalStatus.SUCCEEDED,
                retries_remaining=0,
                replans_remaining=context.budget.max_replans,
            )
        if verification.accepted:
            return ControllerDecision(
                action=ControllerAction.RESPOND_PARTIAL,
                reason="some required evidence is missing or rejected",
                terminal_status=TerminalStatus.PARTIAL,
                retries_remaining=0,
                replans_remaining=context.budget.max_replans,
            )
        return ControllerDecision(
            action=ControllerAction.FAIL,
            reason="no evidence passed verification",
            terminal_status=TerminalStatus.FAILED,
            retries_remaining=0,
            replans_remaining=context.budget.max_replans,
        )
