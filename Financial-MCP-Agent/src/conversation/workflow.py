"""编排 M2 全部确定性阶段并产生唯一终态。"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from .context import ContextBuilder
from .contracts import (
    AnswerContextPack,
    ControllerAction,
    ControllerDecision,
    ConversationRequest,
    ConversationResult,
    ConversationRunContext,
    ConversationState,
    Entity,
    ErrorCode,
    EventAttribute,
    RouteDecision,
    RunBudget,
    RunPhase,
    StageName,
    StageStatus,
    TerminalStatus,
    ToolPlan,
    VerificationResult,
    WorkflowEvent,
)
from .control import RuleController
from .entity import DeterministicEntityResolver
from .errors import StepBudgetExceededError
from .execution import ControlledExecutor
from .permissions import DeterministicPermissionResolver
from .planning import DeterministicPlanner
from .ports import ModelPort, ToolPort, TraceSink
from .rewriting import DeterministicRewriter
from .routing import DeterministicRouter
from .synthesis import ControlledSynthesizer
from .validation import PlanValidator
from .verification import EvidenceVerifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _WorkflowServices:
    """集中保存无运行态的阶段实现，避免在流程中临时构造依赖。"""

    context: ContextBuilder
    entity: DeterministicEntityResolver
    router: DeterministicRouter
    rewriter: DeterministicRewriter
    permissions: DeterministicPermissionResolver
    planner: DeterministicPlanner
    validator: PlanValidator
    executor: ControlledExecutor
    verifier: EvidenceVerifier
    controller: RuleController
    synthesizer: ControlledSynthesizer


class ControlledConversationWorkflow:
    """运行不依赖 Web/数据库框架的线性受控对话工作流。"""

    def __init__(
        self,
        *,
        model: ModelPort,
        tool: ToolPort,
        trace: TraceSink,
        budget: RunBudget | None = None,
    ) -> None:
        self._trace = trace
        self._budget = budget or RunBudget()
        self._services = _WorkflowServices(
            context=ContextBuilder(),
            entity=DeterministicEntityResolver(),
            router=DeterministicRouter(),
            rewriter=DeterministicRewriter(),
            permissions=DeterministicPermissionResolver(),
            planner=DeterministicPlanner(),
            validator=PlanValidator(),
            executor=ControlledExecutor(tool),
            verifier=EvidenceVerifier(),
            controller=RuleController(),
            synthesizer=ControlledSynthesizer(model),
        )

    async def run(
        self,
        request: ConversationRequest,
        *,
        recent_messages: tuple[str, ...] = (),
        running_summary: str | None = None,
    ) -> ConversationResult:
        """执行一轮受控对话并返回唯一终态。

        Args:
            request: 已由调用边界构造并校验的请求。
            recent_messages: 可选、已裁剪的会话尾窗。
            running_summary: 可选会话摘要；当前轮问题始终优先。

        Returns:
            包含阶段事件、证据门控和终态的不可变结果。
        """
        context = ConversationRunContext(
            trace_id=f"tr_{uuid.uuid4().hex}",
            run_id=f"run_{uuid.uuid4().hex}",
            session_id=request.session_id,
            request_id=request.request_id,
            turn_index=1,
            budget=self._budget,
        )
        state = ConversationState()
        events: list[WorkflowEvent] = []

        try:
            started = time.perf_counter()
            packet = self._services.context.build(
                request,
                recent_messages=recent_messages,
                running_summary=running_summary,
            )
            state.transition(RunPhase.PREFLIGHTED)
            self._emit(events, context, StageName.CONTEXT, StageStatus.SUCCEEDED, started)

            started = time.perf_counter()
            entity_result = self._services.entity.resolve(packet)
            state.transition(RunPhase.ENTITY_RESOLVED)
            self._emit(
                events,
                context,
                StageName.ENTITY_RESOLUTION,
                StageStatus.SUCCEEDED,
                started,
                error_code=entity_result.error_code,
                attributes=(
                    EventAttribute(key="candidate_count", value=len(entity_result.candidates)),
                    EventAttribute(key="confidence", value=entity_result.confidence),
                ),
            )
            if entity_result.clarification:
                state.terminate(TerminalStatus.NEEDS_CLARIFICATION)
                decision = ControllerDecision(
                    action=ControllerAction.CLARIFY,
                    reason="entity is ambiguous or missing",
                    terminal_status=TerminalStatus.NEEDS_CLARIFICATION,
                    retries_remaining=context.budget.max_tool_attempts,
                    replans_remaining=context.budget.max_replans,
                )
                self._emit(
                    events,
                    context,
                    StageName.CONTROLLER,
                    StageStatus.SUCCEEDED,
                    time.perf_counter(),
                    error_code=entity_result.error_code,
                    attributes=(EventAttribute(key="action", value=decision.action.value),),
                )
                self._emit_terminal(
                    events,
                    context,
                    TerminalStatus.NEEDS_CLARIFICATION,
                    entity_result.error_code,
                )
                return ConversationResult(
                    status=TerminalStatus.NEEDS_CLARIFICATION,
                    reply=entity_result.clarification,
                    context=context,
                    events=tuple(events),
                    controller=decision,
                    error_code=entity_result.error_code,
                )

            started = time.perf_counter()
            route = self._services.router.route(packet, entity_result)
            state.transition(RunPhase.ROUTED)
            self._emit(
                events,
                context,
                StageName.ROUTE,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="route_family", value=route.family.value),
                    EventAttribute(key="confidence", value=route.confidence),
                ),
            )

            if route.family.value == "fallback":
                state.transition(RunPhase.SYNTHESIZING)
                state.terminate(TerminalStatus.UNSUPPORTED)
                reply = "当前 M2 离线切片只实现单股只读快照；概念问答由后续入口切换保留原链路。"
                self._emit(
                    events,
                    context,
                    StageName.SYNTHESIS,
                    StageStatus.SKIPPED,
                    time.perf_counter(),
                )
                self._emit_terminal(events, context, TerminalStatus.UNSUPPORTED, None)
                return ConversationResult(
                    status=TerminalStatus.UNSUPPORTED,
                    reply=reply,
                    context=context,
                    events=tuple(events),
                    route=route,
                )

            started = time.perf_counter()
            rewrite = self._services.rewriter.rewrite(packet, entity_result, route)
            state.transition(RunPhase.REWRITTEN)
            self._emit(
                events,
                context,
                StageName.REWRITE,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="dimension_count", value=len(rewrite.requested_dimensions)),
                ),
            )
            if rewrite.entity is None:
                return self._failed_result(
                    state=state,
                    events=events,
                    context=context,
                    error_code=ErrorCode.ENTITY_REQUIRED,
                    reply="执行前缺少明确股票实体。",
                    route=route,
                )

            started = time.perf_counter()
            permissions = self._services.permissions.resolve(rewrite)
            self._emit(
                events,
                context,
                StageName.PERMISSION,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="tool_count", value=len(permissions.allowed_tools)),
                    EventAttribute(key="permission_hash", value=permissions.snapshot_hash),
                ),
            )

            started = time.perf_counter()
            plan = self._services.planner.plan(rewrite.entity, rewrite.requested_dimensions)
            state.transition(RunPhase.PLANNED)
            self._emit(
                events,
                context,
                StageName.PLAN,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="plan_id", value=plan.plan_id),
                    EventAttribute(key="step_count", value=len(plan.steps)),
                ),
            )

            started = time.perf_counter()
            validation = self._services.validator.validate(plan, permissions)
            state.transition(RunPhase.VALIDATED)
            self._emit(
                events,
                context,
                StageName.VALIDATE,
                StageStatus.SUCCEEDED if validation.is_valid else StageStatus.FAILED,
                started,
                error_code=None if validation.is_valid else ErrorCode.PLAN_INVALID,
                attributes=(EventAttribute(key="issue_count", value=len(validation.issues)),),
            )
            if validation.validated_plan is None:
                return self._failed_result(
                    state=state,
                    events=events,
                    context=context,
                    error_code=ErrorCode.PLAN_INVALID,
                    reply="工具计划未通过安全校验。",
                    entity=rewrite.entity,
                    route=route,
                    plan=plan,
                )

            started = time.perf_counter()
            state.transition(RunPhase.EXECUTING)
            execution = await self._services.executor.execute(validation.validated_plan, context)
            execute_status = (
                StageStatus.PARTIAL
                if any(item.error_code is not None for item in execution.observations)
                else StageStatus.SUCCEEDED
            )
            self._emit(
                events,
                context,
                StageName.EXECUTE,
                execute_status,
                started,
                attributes=(
                    EventAttribute(key="tool_call_count", value=execution.tool_call_count),
                ),
            )

            started = time.perf_counter()
            state.transition(RunPhase.VERIFIED)
            verification = self._services.verifier.verify(
                entity=rewrite.entity,
                observations=execution.observations,
                required_dimensions=rewrite.requested_dimensions,
            )
            self._emit(
                events,
                context,
                StageName.VERIFY,
                StageStatus.PARTIAL
                if verification.missing_dimensions
                else StageStatus.SUCCEEDED,
                started,
                error_code=(
                    ErrorCode.EVIDENCE_MISSING if verification.missing_dimensions else None
                ),
                attributes=(
                    EventAttribute(key="accepted_count", value=len(verification.accepted)),
                    EventAttribute(key="rejected_count", value=len(verification.rejected)),
                    EventAttribute(key="claim_level", value=verification.claim_level.value),
                ),
            )

            started = time.perf_counter()
            decision = self._services.controller.decide(verification, context)
            self._emit(
                events,
                context,
                StageName.CONTROLLER,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="action", value=decision.action.value),
                    EventAttribute(key="reason", value=decision.reason),
                    EventAttribute(key="replans_remaining", value=decision.replans_remaining),
                ),
            )
            if decision.terminal_status is TerminalStatus.FAILED:
                return self._failed_result(
                    state=state,
                    events=events,
                    context=context,
                    error_code=ErrorCode.EVIDENCE_MISSING,
                    reply="没有证据通过校验，无法形成可靠回答。",
                    entity=rewrite.entity,
                    route=route,
                    plan=plan,
                    verification=verification,
                    controller=decision,
                    tool_call_count=execution.tool_call_count,
                )

            started = time.perf_counter()
            state.transition(RunPhase.SYNTHESIZING)
            pack = AnswerContextPack(
                question=request.message,
                entity=rewrite.entity,
                accepted_evidence=verification.accepted,
                missing_dimensions=verification.missing_dimensions,
                claim_level=verification.claim_level,
                terminal_status=decision.terminal_status,
            )
            reply = await self._services.synthesizer.synthesize(pack)
            self._emit(
                events,
                context,
                StageName.SYNTHESIS,
                StageStatus.PARTIAL
                if decision.terminal_status is TerminalStatus.PARTIAL
                else StageStatus.SUCCEEDED,
                started,
            )
            state.terminate(decision.terminal_status)
            error_code = self._result_error_code(verification)
            self._emit_terminal(events, context, decision.terminal_status, error_code)
            return ConversationResult(
                status=decision.terminal_status,
                reply=reply,
                context=context,
                events=tuple(events),
                entity=rewrite.entity,
                route=route,
                plan=plan,
                verification=verification,
                controller=decision,
                error_code=error_code,
                missing_dimensions=tuple(
                    item.value for item in verification.missing_dimensions
                ),
                tool_call_count=execution.tool_call_count,
            )
        except StepBudgetExceededError:
            return self._failed_result(
                state=state,
                events=events,
                context=context,
                error_code=ErrorCode.STEP_BUDGET_EXHAUSTED,
                reply="受控对话已达到本轮步骤预算，已安全终止。",
            )
        except Exception as exc:
            # 领域兜底只记录异常类型，防止 Provider 原始消息绕过脱敏边界。
            logger.error(
                "controlled_chat.workflow_failed trace_id=%s stage=%s error_code=%s error_type=%s",
                context.trace_id,
                state.phase.value,
                ErrorCode.INTERNAL_ERROR.value,
                type(exc).__name__,
            )
            return self._failed_result(
                state=state,
                events=events,
                context=context,
                error_code=ErrorCode.INTERNAL_ERROR,
                reply="受控对话处理失败，请稍后重试。",
            )

    @staticmethod
    def _result_error_code(verification: VerificationResult) -> ErrorCode | None:
        if not verification.missing_dimensions:
            return None
        if any(item.rejection_reason == ErrorCode.TOOL_TIMEOUT.value for item in verification.rejected):
            return ErrorCode.TOOL_TIMEOUT
        return ErrorCode.EVIDENCE_MISSING

    def _failed_result(
        self,
        *,
        state: ConversationState,
        events: list[WorkflowEvent],
        context: ConversationRunContext,
        error_code: ErrorCode,
        reply: str,
        entity: Entity | None = None,
        route: RouteDecision | None = None,
        plan: ToolPlan | None = None,
        verification: VerificationResult | None = None,
        controller: ControllerDecision | None = None,
        tool_call_count: int = 0,
    ) -> ConversationResult:
        if not state.phase.is_terminal:
            state.terminate(TerminalStatus.FAILED)
        self._emit_terminal(events, context, TerminalStatus.FAILED, error_code)
        return ConversationResult(
            status=TerminalStatus.FAILED,
            reply=reply,
            context=context,
            events=tuple(events),
            entity=entity,
            route=route,
            plan=plan,
            verification=verification,
            controller=controller,
            error_code=error_code,
            tool_call_count=tool_call_count,
        )

    def _emit_terminal(
        self,
        events: list[WorkflowEvent],
        context: ConversationRunContext,
        status: TerminalStatus,
        error_code: ErrorCode | None,
    ) -> None:
        self._emit(
            events,
            context,
            StageName.TERMINATION,
            StageStatus.FAILED
            if status is TerminalStatus.FAILED
            else StageStatus.PARTIAL
            if status is TerminalStatus.PARTIAL
            else StageStatus.SUCCEEDED,
            time.perf_counter(),
            error_code=error_code,
            attributes=(EventAttribute(key="terminal_status", value=status.value),),
        )

    def _emit(
        self,
        events: list[WorkflowEvent],
        context: ConversationRunContext,
        stage: StageName,
        status: StageStatus,
        started: float,
        *,
        error_code: ErrorCode | None = None,
        attributes: tuple[EventAttribute, ...] = (),
    ) -> None:
        if stage is not StageName.TERMINATION and len(events) >= context.budget.max_steps:
            raise StepBudgetExceededError("workflow stage budget exhausted")
        event = WorkflowEvent(
            sequence=len(events) + 1,
            trace_id=context.trace_id,
            run_id=context.run_id,
            session_id=context.session_id,
            stage=stage,
            status=status,
            elapsed_ms=max(0.0, (time.perf_counter() - started) * 1000),
            error_code=error_code,
            attributes=attributes,
        )
        events.append(event)
        try:
            self._trace.emit(event)
        except Exception as exc:
            logger.warning(
                "controlled_chat.trace_sink_failed trace_id=%s stage=%s error_type=%s",
                context.trace_id,
                stage.value,
                type(exc).__name__,
            )
