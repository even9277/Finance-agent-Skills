"""编排受控对话阶段和唯一的有界补证反馈环。"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.skills.contracts import DegradePolicy
    from src.skills.loader import LoadedSkillContext, SkillLoader, SynthesisSkillView

from src.memory.contracts import (
    MemorySource,
    StateOperation,
    WorkingEntity,
    WorkingState,
    WorkingStateUpdate,
)

from .context import ContextBuilder
from .contracts import (
    AnswerContextPack,
    ControllerAction,
    ControllerDecision,
    ControllerRuntimeState,
    ConstraintOperation,
    ConversationRequest,
    ConversationResult,
    ConversationRunContext,
    ConversationState,
    Entity,
    EntityResolutionResult,
    ErrorCode,
    EvidenceDimension,
    EventAttribute,
    ExecutedPlanStep,
    MemoryContextItem,
    RouteDecision,
    RouteFamily,
    RouteSource,
    RouteStage1Outcome,
    PreferenceOperation,
    RewriteKind,
    RewriteResult,
    RunBudget,
    RunPhase,
    StageName,
    StageStatus,
    SkillCatalogSnapshot,
    TerminalStatus,
    ToolPlan,
    ToolObservation,
    VerificationResult,
    WorkflowEvent,
)
from .control import RuleController
from .entity import AuthoritativeEntityResolver
from .errors import StepBudgetExceededError
from .execution import ControlledExecutor
from .permissions import ControlledPermissionResolver
from .planning import ControlledPlanner
from .ports import ModelPort, SkillRerankerPort, ToolPort, TraceSink
from .replanning import BoundedEvidenceReplanner
from .rewriting import RouteAwareRewriter
from .routing import TwoStageRouter
from .synthesis import ControlledSynthesizer, build_skill_synthesis_guidance
from .tool_governance import ToolGovernanceCatalog
from .validation import PlanValidator
from .verification import EvidenceVerifier

logger = logging.getLogger(__name__)


def _route_trace_attributes(
    route: RouteDecision,
    catalog: SkillCatalogSnapshot,
) -> tuple[EventAttribute, ...]:
    """构造不含查询和候选正文的低基数路由版本链。"""
    skill_version = ""
    if route.skill_name is not None:
        skill_version = catalog.require(route.skill_name).version
    confidence_band = {
        RouteStage1Outcome.HIT_HIGH: "high",
        RouteStage1Outcome.HIT_LOW: "mid",
        RouteStage1Outcome.MISS: "low",
    }[route.stage1_outcome]
    return (
        EventAttribute(key="route_family", value=route.family.value),
        EventAttribute(key="confidence", value=route.confidence),
        EventAttribute(key="confidence_band", value=confidence_band),
        EventAttribute(key="route_source", value=route.route_source.value),
        EventAttribute(key="selected_skill", value=route.skill_name or ""),
        EventAttribute(key="skill_version", value=skill_version),
        EventAttribute(
            key="registry_snapshot_hash",
            value=catalog.registry_snapshot_hash or catalog.snapshot_hash,
        ),
        EventAttribute(key="candidate_count", value=len(route.shortlist)),
        EventAttribute(key="candidate_names", value="|".join(route.shortlist)),
    )


def _reference_trace_attributes(
    prefix: str,
    loaded: LoadedSkillContext | None,
) -> tuple[EventAttribute, ...]:
    """把有界 reference 列表投影为独立 path/hash 标量，避免正文和截断。"""
    if loaded is None:
        return (EventAttribute(key=f"{prefix}_reference_count", value=0),)
    attributes: list[EventAttribute] = [
        EventAttribute(key=f"{prefix}_reference_count", value=len(loaded.references))
    ]
    for index, reference in enumerate(loaded.references, start=1):
        attributes.extend(
            (
                EventAttribute(
                    key=f"{prefix}_reference_{index}_path",
                    value=reference.path,
                ),
                EventAttribute(
                    key=f"{prefix}_reference_{index}_hash",
                    value=reference.content_hash,
                ),
            )
        )
    return tuple(attributes)


def _web_search_plan_trace_attributes(plan: ToolPlan) -> tuple[EventAttribute, ...]:
    """只记录 Web Search 是否触发和最小查询 hash，不记录查询本身。"""
    web_steps = tuple(item for item in plan.steps if item.tool_name == "search_web_news")
    queries = sorted(
        {
            str(argument.value)
            for step in web_steps
            for argument in step.arguments
            if argument.name == "query"
        }
    )
    query_hash = hashlib.sha256("\n".join(queries).encode("utf-8")).hexdigest() if queries else ""
    return (
        EventAttribute(key="web_search_triggered", value=bool(web_steps)),
        EventAttribute(key="web_search_step_count", value=len(web_steps)),
        EventAttribute(key="web_query_hash", value=query_hash),
    )


def _web_source_trace_attributes(
    verification: VerificationResult,
) -> tuple[EventAttribute, ...]:
    """统计 Web 弱证据的来源和裁决数量，不暴露 URL、标题或摘要。"""
    accepted = tuple(
        item
        for item in verification.accepted
        if item.evidence_dimension is EvidenceDimension.WEB_NEWS
    )
    rejected = tuple(
        item
        for item in verification.rejected
        if item.evidence_dimension is EvidenceDimension.WEB_NEWS
    )
    sources = {item.source for item in (*accepted, *rejected)}
    return (
        EventAttribute(key="web_source_count", value=len(sources)),
        EventAttribute(key="web_accepted_count", value=len(accepted)),
        EventAttribute(key="web_rejected_count", value=len(rejected)),
    )


def _build_working_state_update(
    entity_result: EntityResolutionResult,
    rewrite: RewriteResult | None = None,
    *,
    reset_segment: bool = False,
) -> WorkingStateUpdate:
    """把理解链结果收敛为 Memory 域允许持久化的窄更新。"""
    resolved = entity_result.resolved_entities or (
        (entity_result.entity,) if entity_result.entity is not None else ()
    )
    candidates = entity_result.candidates or resolved
    if entity_result.entity is not None and not entity_result.inherited:
        active_operation = StateOperation.SET
    else:
        active_operation = (
            StateOperation.EXPIRE if reset_segment else StateOperation.NOOP
        )
    if candidates and not entity_result.inherited:
        candidate_operation = StateOperation.SET
    else:
        candidate_operation = (
            StateOperation.EXPIRE if reset_segment else StateOperation.NOOP
        )
    constraint_operation = (
        StateOperation.EXPIRE if reset_segment else StateOperation.NOOP
    )
    constraints: tuple[str, ...] = ()
    preference_operation = (
        StateOperation.EXPIRE if reset_segment else StateOperation.NOOP
    )
    preference_hint = ""
    confidence = entity_result.confidence
    if rewrite is not None:
        constraints = rewrite.constraints.items
        if rewrite.constraints.operation is ConstraintOperation.MERGE:
            constraint_operation = (
                StateOperation.SET if reset_segment else StateOperation.MERGE
            )
        elif rewrite.constraints.operation is ConstraintOperation.CLEAR:
            constraint_operation = StateOperation.CLEAR
        preference_hint = rewrite.reply_preference.hint
        if rewrite.reply_preference.operation is PreferenceOperation.REPLACE:
            preference_operation = StateOperation.SET
        elif rewrite.reply_preference.operation is PreferenceOperation.CLEAR:
            preference_operation = StateOperation.CLEAR
        confidence = max(
            confidence,
            rewrite.constraints.confidence,
            rewrite.reply_preference.confidence,
        )

    return WorkingStateUpdate(
        active_entity=(
            WorkingEntity(
                symbol=entity_result.entity.symbol,
                name=entity_result.entity.name,
                entity_type=entity_result.entity.entity_type.value,
            )
            if entity_result.entity is not None
            else None
        ),
        candidate_entities=tuple(
            WorkingEntity(
                symbol=item.symbol,
                name=item.name,
                entity_type=item.entity_type.value,
            )
            for item in candidates
        ),
        active_entity_operation=active_operation,
        candidate_entities_operation=candidate_operation,
        constraints=constraints,
        constraints_operation=constraint_operation,
        reply_preference_hint=preference_hint,
        reply_preference_operation=preference_operation,
        source=MemorySource.USER_MESSAGE,
        confidence=confidence,
    )


@dataclass(frozen=True, slots=True)
class _WorkflowServices:
    """集中保存无运行态的阶段实现，避免在流程中临时构造依赖。"""

    context: ContextBuilder
    entity: AuthoritativeEntityResolver
    router: TwoStageRouter
    rewriter: RouteAwareRewriter
    permissions: ControlledPermissionResolver
    planner: ControlledPlanner
    validator: PlanValidator
    executor: ControlledExecutor
    verifier: EvidenceVerifier
    controller: RuleController
    replanner: BoundedEvidenceReplanner
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
        skill_catalog: SkillCatalogSnapshot | None = None,
        skill_loader: SkillLoader | None = None,
        skill_reranker: SkillRerankerPort | None = None,
        skill_rerank_top_k: int | None = None,
    ) -> None:
        self._trace = trace
        self._budget = budget or RunBudget()
        self._skill_loader = skill_loader
        catalog = skill_catalog or SkillCatalogSnapshot.empty()
        self._skill_catalog = catalog
        tool_catalog = ToolGovernanceCatalog.default()
        self._services = _WorkflowServices(
            context=ContextBuilder(),
            entity=AuthoritativeEntityResolver(),
            router=TwoStageRouter(
                catalog,
                reranker=skill_reranker,
                rerank_top_k=skill_rerank_top_k,
            ),
            rewriter=RouteAwareRewriter(catalog, skill_loader=skill_loader),
            permissions=ControlledPermissionResolver(
                catalog=tool_catalog,
                skill_catalog=catalog,
            ),
            planner=ControlledPlanner(catalog=tool_catalog),
            validator=PlanValidator(),
            executor=ControlledExecutor(tool),
            verifier=EvidenceVerifier(),
            controller=RuleController(),
            replanner=BoundedEvidenceReplanner(catalog=tool_catalog),
            synthesizer=ControlledSynthesizer(model),
        )

    async def run(
        self,
        request: ConversationRequest,
        *,
        recent_messages: tuple[str, ...] = (),
        running_summary: str | None = None,
        working_state: WorkingState | None = None,
        memory_context: tuple[MemoryContextItem, ...] = (),
    ) -> ConversationResult:
        """执行一轮受控对话并返回唯一终态。

        Args:
            request: 已由调用边界构造并校验的请求。
            recent_messages: 可选、已裁剪的会话尾窗。
            running_summary: 可选会话摘要；当前轮问题始终优先。
            working_state: 当前会话版本化热状态；仅作为受门控继承候选。
            memory_context: 已经由 Application 召回并通过 PostgreSQL 后过滤的历史记忆；
                只允许进入上下文和合成阶段。

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
                working_state=working_state,
                memory_context=memory_context,
            )
            state.transition(RunPhase.PREFLIGHTED)
            self._emit(
                events,
                context,
                StageName.CONTEXT,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="memory_hit_count", value=len(packet.retrieved_memories)),
                    EventAttribute(
                        key="memory_token_count",
                        value=sum(max(1, (len(item.content) + 3) // 4) for item in packet.retrieved_memories),
                    ),
                    EventAttribute(
                        key="memory_context_status",
                        value="USED" if packet.retrieved_memories else "EMPTY",
                    ),
                ),
            )

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

            # ENTITY_REQUIRED 可由 Skill input contract 给出更具体的槽位问题；实体歧义仍优先。
            route_started = time.perf_counter()
            route = self._services.router.route(
                packet,
                entity_result,
                explicit_skill=request.explicit_skill,
            )
            invalid_explicit_skill = (
                request.explicit_skill is not None
                and route.route_source is RouteSource.USER_EXPLICIT
                and route.family is RouteFamily.FALLBACK
            )
            if invalid_explicit_skill:
                state.transition(RunPhase.ROUTED)
                self._emit(
                    events,
                    context,
                    StageName.ROUTE,
                    StageStatus.SUCCEEDED,
                    route_started,
                    error_code=ErrorCode.INVALID_REQUEST,
                    attributes=_route_trace_attributes(route, self._skill_catalog),
                )
                state.terminate(TerminalStatus.NEEDS_CLARIFICATION)
                decision = ControllerDecision(
                    action=ControllerAction.CLARIFY,
                    reason="explicit skill is unavailable in the request snapshot",
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
                    error_code=ErrorCode.INVALID_REQUEST,
                    attributes=(EventAttribute(key="action", value=decision.action.value),),
                )
                self._emit_terminal(
                    events,
                    context,
                    TerminalStatus.NEEDS_CLARIFICATION,
                    ErrorCode.INVALID_REQUEST,
                )
                return ConversationResult(
                    status=TerminalStatus.NEEDS_CLARIFICATION,
                    reply="所选分析 Skill 不存在或当前不可用，请重新选择。",
                    context=context,
                    events=tuple(events),
                    entity=entity_result.entity,
                    route=route,
                    controller=decision,
                    error_code=ErrorCode.INVALID_REQUEST,
                    working_state_update=_build_working_state_update(
                        entity_result,
                        reset_segment=packet.reset_working_segment,
                    ),
                )
            defer_entity_clarification = (
                entity_result.error_code is ErrorCode.ENTITY_REQUIRED
                and route.family is RouteFamily.FINANCIAL_SOP
            )
            ignore_entity_requirement = (
                entity_result.error_code is ErrorCode.ENTITY_REQUIRED
                and route.family is RouteFamily.FALLBACK
            )
            if (
                entity_result.clarification
                and not defer_entity_clarification
                and not ignore_entity_requirement
            ):
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
                    working_state_update=_build_working_state_update(
                        entity_result,
                        reset_segment=packet.reset_working_segment,
                    ),
                )

            state.transition(RunPhase.ROUTED)
            self._emit(
                events,
                context,
                StageName.ROUTE,
                StageStatus.SUCCEEDED,
                route_started,
                attributes=_route_trace_attributes(route, self._skill_catalog),
            )

            if route.requires_confirmation:
                candidate_names = "、".join(
                    item.skill_name for item in route.skill_confirmation.candidates
                ) if route.skill_confirmation else "候选分析 Skill"
                state.terminate(TerminalStatus.NEEDS_CLARIFICATION)
                decision = ControllerDecision(
                    action=ControllerAction.CLARIFY,
                    reason="low-confidence SOP route requires user confirmation",
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
                    attributes=(EventAttribute(key="action", value=decision.action.value),),
                )
                self._emit_terminal(
                    events,
                    context,
                    TerminalStatus.NEEDS_CLARIFICATION,
                    ErrorCode.ROUTE_CONFIRMATION_REQUIRED,
                )
                return ConversationResult(
                    status=TerminalStatus.NEEDS_CLARIFICATION,
                    reply=f"我识别到相邻的专业分析任务：{candidate_names}。请确认后继续。",
                    context=context,
                    events=tuple(events),
                    entity=entity_result.entity,
                    route=route,
                    controller=decision,
                    error_code=ErrorCode.ROUTE_CONFIRMATION_REQUIRED,
                    skill_confirmation=route.skill_confirmation,
                    working_state_update=_build_working_state_update(
                        entity_result,
                        reset_segment=packet.reset_working_segment,
                    ),
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
            if rewrite.needs_clarification:
                state.terminate(TerminalStatus.NEEDS_CLARIFICATION)
                decision = ControllerDecision(
                    action=ControllerAction.CLARIFY,
                    reason=rewrite.entity_conflict or rewrite.route_mismatch,
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
                    error_code=ErrorCode.REWRITE_CLARIFICATION_REQUIRED,
                    attributes=(EventAttribute(key="action", value=decision.action.value),),
                )
                self._emit_terminal(
                    events,
                    context,
                    TerminalStatus.NEEDS_CLARIFICATION,
                    ErrorCode.REWRITE_CLARIFICATION_REQUIRED,
                )
                return ConversationResult(
                    status=TerminalStatus.NEEDS_CLARIFICATION,
                    reply=rewrite.clarification_question,
                    context=context,
                    events=tuple(events),
                    entity=rewrite.entity,
                    route=route,
                    controller=decision,
                    error_code=ErrorCode.REWRITE_CLARIFICATION_REQUIRED,
                    working_state_update=_build_working_state_update(
                        entity_result,
                        rewrite,
                        reset_segment=packet.reset_working_segment,
                    ),
                )

            if route.family is RouteFamily.FALLBACK:
                state.transition(RunPhase.SYNTHESIZING)
                state.terminate(TerminalStatus.UNSUPPORTED)
                reply = "当前受控数据链不处理静态知识问答；公开入口切换前继续由既有回答链处理。"
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
                    entity=rewrite.entity,
                    route=route,
                    working_state_update=_build_working_state_update(
                        entity_result,
                        rewrite,
                        reset_segment=packet.reset_working_segment,
                    ),
                )

            if rewrite.entity is None and route.family is RouteFamily.TUSHARE_DATA:
                return self._failed_result(
                    state=state,
                    events=events,
                    context=context,
                    error_code=ErrorCode.ENTITY_REQUIRED,
                    reply="执行前缺少明确股票实体。",
                    route=route,
                )

            planner_context: LoadedSkillContext | None = None
            synthesis_context: LoadedSkillContext | None = None
            degrade_policy: DegradePolicy | None = None
            if rewrite.kind is RewriteKind.FINANCIAL_SOP:
                if self._skill_loader is None or rewrite.skill_name is None:
                    raise RuntimeError("financial SOP requires a fixed SkillLoader snapshot")
                # Planner 与 Synthesis 分别加载最小视图，但固定在同一 RegistrySnapshot。
                planner_context = self._skill_loader.load_for_planner(
                    rewrite.skill_name,
                    query=rewrite.effective_query,
                )
                synthesis_context = self._skill_loader.load_for_synthesis(
                    rewrite.skill_name,
                    query=rewrite.effective_query,
                )
                synthesis_view = cast("SynthesisSkillView", synthesis_context.spec_view)
                degrade_policy = synthesis_view.degrade_policy

            started = time.perf_counter()
            permissions = self._services.permissions.resolve(
                rewrite,
                skill_context=planner_context,
            )
            self._emit(
                events,
                context,
                StageName.PERMISSION,
                StageStatus.SUCCEEDED,
                started,
                attributes=(
                    EventAttribute(key="tool_count", value=len(permissions.allowed_tools)),
                    EventAttribute(key="permission_hash", value=permissions.snapshot_hash),
                    EventAttribute(key="selected_skill", value=permissions.skill_name or ""),
                    EventAttribute(key="skill_version", value=permissions.skill_version),
                    EventAttribute(key="skill_spec_hash", value=permissions.skill_spec_hash),
                    EventAttribute(
                        key="registry_snapshot_hash",
                        value=permissions.registry_snapshot_hash,
                    ),
                )
                + _reference_trace_attributes("planner", planner_context),
            )

            started = time.perf_counter()
            plan = self._services.planner.plan(
                rewrite,
                permissions,
                trace_id=context.trace_id,
                skill_context=planner_context,
            )
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
                    EventAttribute(key="skill_spec_hash", value=plan.skill_spec_hash),
                )
                + _web_search_plan_trace_attributes(plan),
            )

            started = time.perf_counter()
            validation = self._services.validator.validate(
                plan,
                permissions,
                budget=context.budget,
            )
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

            current_validated = validation.validated_plan
            combined_plan = plan
            all_observations: tuple[ToolObservation, ...] = ()
            executed_steps: list[ExecutedPlanStep] = []
            total_tool_calls = 0
            attempted_fingerprints = {step.idempotency_key for step in plan.steps}
            runtime = ControllerRuntimeState()

            while True:
                started = time.perf_counter()
                state.transition(RunPhase.EXECUTING)
                execution = await self._services.executor.execute(current_validated, context)
                total_tool_calls += execution.tool_call_count
                all_observations += execution.observations
                is_replanned = runtime.replan_count > 0
                executed_steps.extend(
                    ExecutedPlanStep(
                        plan_id=current_validated.plan.plan_id,
                        step_id=item.step_id,
                        tool_name=item.tool_name,
                        status=item.status,
                        evidence_dimension=item.evidence_dimension,
                        replanned=is_replanned,
                    )
                    for item in execution.observations
                )
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
                        EventAttribute(key="batch_count", value=execution.batch_count),
                        EventAttribute(key="failed_count", value=execution.failed_count),
                        EventAttribute(
                            key="deduplicated_count",
                            value=execution.deduplicated_count,
                        ),
                        EventAttribute(key="replan_count", value=runtime.replan_count),
                    ),
                )

                started = time.perf_counter()
                state.transition(RunPhase.VERIFIED)
                verification = self._services.verifier.verify(
                    plan=combined_plan,
                    observations=all_observations,
                    as_of=date.today(),
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
                        ErrorCode.EVIDENCE_MISSING
                        if verification.missing_dimensions
                        else None
                    ),
                    attributes=(
                        EventAttribute(key="accepted_count", value=len(verification.accepted)),
                        EventAttribute(key="rejected_count", value=len(verification.rejected)),
                        EventAttribute(key="missing_count", value=len(verification.missing_requirements)),
                        EventAttribute(key="claim_level", value=verification.claim_level.value),
                        EventAttribute(key="evidence_score", value=verification.score.total),
                    )
                    + _web_source_trace_attributes(verification),
                )

                started = time.perf_counter()
                decision = self._services.controller.decide(
                    verification,
                    budget=context.budget,
                    runtime=runtime,
                    degrade_policy=degrade_policy,
                )
                self._emit_controller(events, context, decision, started)
                if decision.action is not ControllerAction.REPLAN:
                    break

                state.transition(RunPhase.REPLANNING)
                replan_started = time.perf_counter()
                attempt = runtime.replan_count + 1
                replan = self._services.replanner.replan(
                    root_plan=plan,
                    permissions=permissions,
                    verification=verification,
                    attempt=attempt,
                    attempted_fingerprints=frozenset(attempted_fingerprints),
                )
                self._emit(
                    events,
                    context,
                    StageName.REPLAN,
                    StageStatus.SUCCEEDED if replan.plan is not None else StageStatus.SKIPPED,
                    replan_started,
                    attributes=(
                        EventAttribute(key="attempt", value=attempt),
                        EventAttribute(key="reason", value=replan.reason),
                        EventAttribute(
                            key="added_step_count",
                            value=len(replan.plan.steps) if replan.plan is not None else 0,
                        ),
                    ),
                )
                if replan.plan is None:
                    runtime = ControllerRuntimeState(
                        replan_count=context.budget.max_replans,
                        previous_missing_requirements=verification.missing_requirements,
                    )
                    decision = self._services.controller.decide(
                        verification,
                        budget=context.budget,
                        runtime=runtime,
                        degrade_policy=degrade_policy,
                    )
                    self._emit_controller(
                        events,
                        context,
                        decision,
                        time.perf_counter(),
                    )
                    break

                replan_validation_started = time.perf_counter()
                replan_validation = self._services.validator.validate(
                    replan.plan,
                    permissions,
                    budget=context.budget,
                )
                state.transition(RunPhase.VALIDATED)
                self._emit(
                    events,
                    context,
                    StageName.VALIDATE,
                    StageStatus.SUCCEEDED
                    if replan_validation.is_valid
                    else StageStatus.FAILED,
                    replan_validation_started,
                    error_code=(
                        None if replan_validation.is_valid else ErrorCode.PLAN_INVALID
                    ),
                    attributes=(
                        EventAttribute(key="issue_count", value=len(replan_validation.issues)),
                        EventAttribute(key="replan_count", value=attempt),
                    ),
                )
                if replan_validation.validated_plan is None:
                    return self._failed_result(
                        state=state,
                        events=events,
                        context=context,
                        error_code=ErrorCode.PLAN_INVALID,
                        reply="补证计划未通过安全校验。",
                        entity=rewrite.entity,
                        route=route,
                        plan=combined_plan,
                        verification=verification,
                        controller=decision,
                        tool_call_count=total_tool_calls,
                    )
                combined_plan = replace(
                    combined_plan,
                    steps=combined_plan.steps + replan.plan.steps,
                )
                attempted_fingerprints.update(
                    item.idempotency_key for item in replan.plan.steps
                )
                runtime = ControllerRuntimeState(
                    replan_count=attempt,
                    previous_missing_requirements=verification.missing_requirements,
                )
                current_validated = replan_validation.validated_plan

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
                    tool_call_count=total_tool_calls,
                )
            if decision.terminal_status is TerminalStatus.NEEDS_CLARIFICATION:
                state.terminate(TerminalStatus.NEEDS_CLARIFICATION)
                self._emit_terminal(
                    events,
                    context,
                    TerminalStatus.NEEDS_CLARIFICATION,
                    ErrorCode.EVIDENCE_MISSING,
                )
                return ConversationResult(
                    status=TerminalStatus.NEEDS_CLARIFICATION,
                    reply="当前证据不足，请补充分析主体或时间范围后重试。",
                    context=context,
                    events=tuple(events),
                    entity=rewrite.entity,
                    route=route,
                    plan=combined_plan,
                    verification=verification,
                    controller=decision,
                    error_code=ErrorCode.EVIDENCE_MISSING,
                    missing_dimensions=tuple(
                        item.value for item in verification.missing_dimensions
                    ),
                    tool_call_count=total_tool_calls,
                )

            started = time.perf_counter()
            state.transition(RunPhase.SYNTHESIZING)
            if decision.terminal_status is None:
                raise RuntimeError("controller returned a non-terminal decision after evidence loop")
            skill_guidance = (
                build_skill_synthesis_guidance(
                    synthesis_context,
                    reply_preference=rewrite.reply_preference.hint,
                    degrade_stage=decision.degrade_stage or "primary",
                )
                if synthesis_context is not None
                else None
            )
            pack = AnswerContextPack.create(
                question=request.message,
                effective_query=rewrite.effective_query,
                entities=rewrite.entities,
                executed_plan=tuple(executed_steps),
                verification=verification,
                terminal_status=decision.terminal_status,
                constraints=rewrite.constraints.items,
                reply_preference=rewrite.reply_preference.hint,
                selected_skill=rewrite.skill_name,
                retrieved_memories=packet.retrieved_memories,
                skill_guidance=skill_guidance,
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
                attributes=(
                    EventAttribute(key="selected_skill", value=rewrite.skill_name or ""),
                    EventAttribute(
                        key="skill_version",
                        value=synthesis_context.skill_version if synthesis_context else "",
                    ),
                    EventAttribute(
                        key="skill_spec_hash",
                        value=synthesis_context.spec_hash if synthesis_context else "",
                    ),
                    EventAttribute(
                        key="registry_snapshot_hash",
                        value=(
                            synthesis_context.registry_snapshot_hash
                            if synthesis_context
                            else self._skill_catalog.registry_snapshot_hash
                            or self._skill_catalog.snapshot_hash
                        ),
                    ),
                    EventAttribute(key="claim_level", value=verification.claim_level.value),
                    EventAttribute(
                        key="degrade_stage",
                        value=decision.degrade_stage or "primary",
                    ),
                )
                + _reference_trace_attributes("synthesis", synthesis_context),
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
                plan=combined_plan,
                verification=verification,
                controller=decision,
                error_code=error_code,
                missing_dimensions=tuple(
                    item.value for item in verification.missing_dimensions
                ),
                tool_call_count=total_tool_calls,
                working_state_update=_build_working_state_update(
                    entity_result,
                    rewrite,
                    reset_segment=packet.reset_working_segment,
                ),
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
        if any(
            item.source_error_code is ErrorCode.TOOL_TIMEOUT
            for item in verification.rejected
        ):
            return ErrorCode.TOOL_TIMEOUT
        return ErrorCode.EVIDENCE_MISSING

    def _emit_controller(
        self,
        events: list[WorkflowEvent],
        context: ConversationRunContext,
        decision: ControllerDecision,
        started: float,
    ) -> None:
        """记录不含证据载荷的稳定 Controller 决策事件。"""
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
                EventAttribute(key="degrade_stage", value=decision.degrade_stage or ""),
            ),
        )

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
