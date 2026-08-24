"""定义受控对话主链唯一的强类型跨阶段合同。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from .errors import ContractViolationError, StateTransitionError

CONTRACT_VERSION = "controlled-chat-v1"
WORKFLOW_NAME = "controlled-conversation"


class TerminalStatus(StrEnum):
    """一轮对话唯一、机器可消费的业务终态。"""

    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"


class RunPhase(StrEnum):
    """工作流阶段以及与终态同名的终止节点。"""

    RECEIVED = "RECEIVED"
    PREFLIGHTED = "PREFLIGHTED"
    ENTITY_RESOLVED = "ENTITY_RESOLVED"
    ROUTED = "ROUTED"
    REWRITTEN = "REWRITTEN"
    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    EXECUTING = "EXECUTING"
    VERIFIED = "VERIFIED"
    SYNTHESIZING = "SYNTHESIZING"
    SUCCEEDED = TerminalStatus.SUCCEEDED
    PARTIAL = TerminalStatus.PARTIAL
    NEEDS_CLARIFICATION = TerminalStatus.NEEDS_CLARIFICATION
    REJECTED = TerminalStatus.REJECTED
    FAILED = TerminalStatus.FAILED
    CANCELLED = TerminalStatus.CANCELLED
    UNSUPPORTED = TerminalStatus.UNSUPPORTED

    @property
    def is_terminal(self) -> bool:
        """判断当前阶段是否已经结束本轮运行。"""
        return self.value in {status.value for status in TerminalStatus}


class StageName(StrEnum):
    """Trace 使用的稳定低基数阶段名称。"""

    CONTEXT = "context"
    ENTITY_RESOLUTION = "entity_resolution"
    ROUTE = "route"
    REWRITE = "rewrite"
    PERMISSION = "permission"
    PLAN = "plan"
    VALIDATE = "validate"
    EXECUTE = "execute"
    VERIFY = "verify"
    CONTROLLER = "controller"
    SYNTHESIS = "synthesis"
    TERMINATION = "termination"


class StageStatus(StrEnum):
    """阶段事件允许的执行状态。"""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PARTIAL = "PARTIAL"


class ErrorCode(StrEnum):
    """跨层传递但不暴露内部异常原文的稳定错误码。"""

    INVALID_REQUEST = "INVALID_REQUEST"
    AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
    ENTITY_REQUIRED = "ENTITY_REQUIRED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_INVALID_RESULT = "TOOL_INVALID_RESULT"
    PLAN_INVALID = "PLAN_INVALID"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    STEP_BUDGET_EXHAUSTED = "STEP_BUDGET_EXHAUSTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EntityType(StrEnum):
    """M2 支持的最小实体类型集合。"""

    STOCK = "stock"


class RouteFamily(StrEnum):
    """与现有入口兼容的三类顶层路由。"""

    FINANCIAL_SOP = "financial-sop"
    TUSHARE_DATA = "tushare-data"
    FALLBACK = "fallback"


class EvidenceDimension(StrEnum):
    """单股快照切片可请求和验收的证据维度。"""

    BASIC_PROFILE = "basic_profile"
    MARKET_SNAPSHOT = "market_snapshot"


class StepStatus(StrEnum):
    """工具步骤的归一化结果状态。"""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EvidenceStatus(StrEnum):
    """Verifier 对单条证据的验收状态。"""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ClaimLevel(StrEnum):
    """当前证据允许回答的最高结论强度。"""

    CURRENT_FACT = "CURRENT_FACT"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class ControllerAction(StrEnum):
    """规则 Controller 可输出的有限动作。"""

    STOP = "STOP"
    RESPOND_PARTIAL = "RESPOND_PARTIAL"
    CLARIFY = "CLARIFY"
    FAIL = "FAIL"


class ValidationIssueCode(StrEnum):
    """计划校验失败的结构化原因。"""

    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    DUPLICATE_STEP = "DUPLICATE_STEP"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
    CYCLIC_DEPENDENCY = "CYCLIC_DEPENDENCY"
    ENTITY_MISMATCH = "ENTITY_MISMATCH"
    MISSING_REQUIRED_EVIDENCE = "MISSING_REQUIRED_EVIDENCE"


@dataclass(frozen=True, slots=True)
class RunBudget:
    """限制单轮步骤和外部调用，防止隐式无限循环。

    Attributes:
        max_steps: 一轮最多记录的业务阶段数，不含终止事件。
        max_tool_attempts: 单个只读工具发生瞬时超时时的总尝试次数。
        max_replans: 后续里程碑可使用的最大重规划次数；M2 不执行重规划。
    """

    max_steps: int = 16
    max_tool_attempts: int = 2
    max_replans: int = 1

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tool_attempts < 1 or self.max_replans < 0:
            raise ContractViolationError("run budget values are outside the allowed range")


@dataclass(frozen=True, slots=True)
class ConversationRequest:
    """进入领域工作流前已经完成 API 校验的请求。

    Attributes:
        user_id: 已认证用户标识；只用于隔离和持久化，不写入 Trace 详情。
        session_id: 当前会话标识；M2 要求调用方显式提供。
        message: 当前轮原始问题，不由路由或历史上下文覆盖。
        request_id: 可选幂等/关联标识；不作为动态 Trace 名称。
        explicit_skill: 用户显式选择的 Skill；M2 仅保留合同，不执行 Skill 迁移。
    """

    user_id: str
    session_id: str
    message: str
    request_id: str | None = None
    explicit_skill: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("user_id", "session_id", "message"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ContractViolationError(f"{field_name} must not be blank")
        if len(self.message) > 10_000:
            raise ContractViolationError("message exceeds the 10000 character limit")


@dataclass(frozen=True, slots=True)
class ConversationRunContext:
    """本轮不可变关联信息、版本和执行预算。"""

    trace_id: str
    run_id: str
    session_id: str
    request_id: str | None
    turn_index: int
    contract_version: str = CONTRACT_VERSION
    workflow_name: str = WORKFLOW_NAME
    budget: RunBudget = field(default_factory=RunBudget)


@dataclass(frozen=True, slots=True)
class ContextPacket:
    """按当前阶段裁剪的上下文，不包含完整 LTM 或 Skill 正文。"""

    current_message: str
    recent_messages: tuple[str, ...] = ()
    running_summary: str | None = None
    confirmed_constraints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Entity:
    """经过权威解析后可进入工具计划的主实体。"""

    symbol: str
    name: str
    entity_type: EntityType


@dataclass(frozen=True, slots=True)
class EntityResolutionResult:
    """实体解析结果；歧义时不选择主实体。"""

    entity: Entity | None
    candidates: tuple[Entity, ...]
    inherited: bool
    confidence: float
    clarification: str | None = None
    error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """不修改实体的顶层路由决定。"""

    family: RouteFamily
    analysis_mode: str
    confidence: float
    reason: str
    skill_name: str | None = None
    requires_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class RewriteResult:
    """将原问题转换为计划器可消费的确定性执行合同。"""

    effective_query: str
    entity: Entity | None
    requested_dimensions: tuple[EvidenceDimension, ...]
    clarification: str | None = None


@dataclass(frozen=True, slots=True)
class ToolPermissionSnapshot:
    """Planner 可见的请求级只读工具权限快照。"""

    allowed_tools: tuple[str, ...]
    source: str
    version: str
    snapshot_hash: str

    @classmethod
    def create(
        cls,
        *,
        allowed_tools: tuple[str, ...],
        source: str,
        version: str,
    ) -> ToolPermissionSnapshot:
        """创建排序稳定且带 hash 的权限快照。

        Args:
            allowed_tools: 本轮允许执行的只读工具名。
            source: 权限规则来源，必须是稳定低基数字符串。
            version: 工具合同或注册表版本。

        Returns:
            可在计划和 Trace 中复核的权限快照。
        """
        normalized = tuple(sorted(set(allowed_tools)))
        raw = "|".join((source, version, *normalized)).encode()
        return cls(
            allowed_tools=normalized,
            source=source,
            version=version,
            snapshot_hash=hashlib.sha256(raw).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    """计划必须覆盖的证据维度。"""

    dimension: EvidenceDimension
    required: bool


@dataclass(frozen=True, slots=True)
class ToolPlanStep:
    """DAG 中的一个只读工具动作。"""

    step_id: str
    tool_name: str
    symbol: str
    evidence_dimension: EvidenceDimension
    required: bool
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolPlan:
    """未经校验、绝不允许直接执行的结构化工具计划。"""

    plan_id: str
    entity: Entity
    steps: tuple[ToolPlanStep, ...]
    requirements: tuple[EvidenceRequirement, ...]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """阻断执行的单个计划合同问题。"""

    code: ValidationIssueCode
    message: str
    step_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedToolPlan:
    """通过权限、实体、DAG 和证据覆盖校验的可执行计划。"""

    plan: ToolPlan
    permission_hash: str


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    """计划校验结果；只有 `validated_plan` 可交给 Executor。"""

    is_valid: bool
    issues: tuple[ValidationIssue, ...]
    validated_plan: ValidatedToolPlan | None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Executor 交给 Tool Port 的已授权调用。"""

    step_id: str
    tool_name: str
    symbol: str
    evidence_dimension: EvidenceDimension


@dataclass(frozen=True, slots=True)
class EvidenceFact:
    """工具输出中的一个可审查标量事实。"""

    key: str
    value: str
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """Tool Port 返回并经 Executor 归一化的步骤结果。"""

    step_id: str
    tool_name: str
    symbol: str
    evidence_dimension: EvidenceDimension
    facts: tuple[EvidenceFact, ...]
    source: str
    observed_at: date
    attempts: int
    status: StepStatus = StepStatus.SUCCEEDED
    error_code: ErrorCode | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """一个 validated plan 的完整、有界执行结果。"""

    observations: tuple[ToolObservation, ...]
    tool_call_count: int


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """Verifier 已验收或拒绝的证据信封。"""

    evidence_id: str
    step_id: str
    entity_symbol: str
    evidence_dimension: EvidenceDimension
    facts: tuple[EvidenceFact, ...]
    source: str
    observed_at: date
    status: EvidenceStatus
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """证据门控结果和当前允许的结论强度。"""

    accepted: tuple[EvidenceEnvelope, ...]
    rejected: tuple[EvidenceEnvelope, ...]
    missing_dimensions: tuple[EvidenceDimension, ...]
    claim_level: ClaimLevel
    recoverable: bool


@dataclass(frozen=True, slots=True)
class ControllerDecision:
    """基于证据和剩余预算产生的有限控制动作。"""

    action: ControllerAction
    reason: str
    terminal_status: TerminalStatus
    retries_remaining: int
    replans_remaining: int


@dataclass(frozen=True, slots=True)
class AnswerContextPack:
    """Synthesis 唯一允许消费的、只含 accepted evidence 的上下文。"""

    question: str
    entity: Entity
    accepted_evidence: tuple[EvidenceEnvelope, ...]
    missing_dimensions: tuple[EvidenceDimension, ...]
    claim_level: ClaimLevel
    terminal_status: TerminalStatus


@dataclass(frozen=True, slots=True)
class ModelSynthesisRequest:
    """交给模型 Provider 的版本化 Prompt 与安全回答上下文。"""

    prompt_version: str
    system_prompt: str
    context: AnswerContextPack


@dataclass(frozen=True, slots=True)
class EventAttribute:
    """阶段事件允许携带的低风险标量属性。"""

    key: str
    value: str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    """REST/WS Presenter 和 Trace Adapter 可共享的版本化阶段事件。"""

    sequence: int
    trace_id: str
    run_id: str
    session_id: str
    stage: StageName
    status: StageStatus
    elapsed_ms: float
    error_code: ErrorCode | None = None
    attributes: tuple[EventAttribute, ...] = ()
    version: str = CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class ConversationResult:
    """一次受控对话运行的唯一终态输出。"""

    status: TerminalStatus
    reply: str
    context: ConversationRunContext
    events: tuple[WorkflowEvent, ...]
    entity: Entity | None = None
    route: RouteDecision | None = None
    plan: ToolPlan | None = None
    verification: VerificationResult | None = None
    controller: ControllerDecision | None = None
    error_code: ErrorCode | None = None
    missing_dimensions: tuple[str, ...] = ()
    tool_call_count: int = 0


_ALLOWED_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.RECEIVED: frozenset({RunPhase.PREFLIGHTED, RunPhase.FAILED, RunPhase.CANCELLED}),
    RunPhase.PREFLIGHTED: frozenset(
        {RunPhase.ENTITY_RESOLVED, RunPhase.REJECTED, RunPhase.FAILED}
    ),
    RunPhase.ENTITY_RESOLVED: frozenset(
        {
            RunPhase.ROUTED,
            RunPhase.NEEDS_CLARIFICATION,
            RunPhase.UNSUPPORTED,
            RunPhase.FAILED,
        }
    ),
    RunPhase.ROUTED: frozenset(
        {
            RunPhase.REWRITTEN,
            RunPhase.SYNTHESIZING,
            RunPhase.NEEDS_CLARIFICATION,
            RunPhase.FAILED,
        }
    ),
    RunPhase.REWRITTEN: frozenset(
        {RunPhase.PLANNED, RunPhase.NEEDS_CLARIFICATION, RunPhase.FAILED}
    ),
    RunPhase.PLANNED: frozenset({RunPhase.VALIDATED, RunPhase.FAILED}),
    RunPhase.VALIDATED: frozenset({RunPhase.EXECUTING, RunPhase.REJECTED, RunPhase.FAILED}),
    RunPhase.EXECUTING: frozenset({RunPhase.VERIFIED, RunPhase.CANCELLED, RunPhase.FAILED}),
    RunPhase.VERIFIED: frozenset({RunPhase.SYNTHESIZING, RunPhase.FAILED}),
    RunPhase.SYNTHESIZING: frozenset(
        {RunPhase.SUCCEEDED, RunPhase.PARTIAL, RunPhase.FAILED, RunPhase.UNSUPPORTED}
    ),
}


@dataclass(slots=True)
class ConversationState:
    """只允许按冻结转换表前进的工作流状态。"""

    phase: RunPhase = RunPhase.RECEIVED
    terminal_status: TerminalStatus | None = None

    def transition(self, next_phase: RunPhase) -> None:
        """执行一次合法的单向阶段转换。

        Args:
            next_phase: 目标阶段或终态。

        Raises:
            StateTransitionError: 当前已终止，或转换不在冻结表中。
        """
        if self.phase.is_terminal:
            raise StateTransitionError(f"terminal phase {self.phase.value} cannot transition")
        allowed = _ALLOWED_TRANSITIONS.get(self.phase, frozenset())
        if next_phase not in allowed:
            raise StateTransitionError(
                f"illegal transition {self.phase.value} -> {next_phase.value}"
            )
        self.phase = next_phase

    def terminate(self, status: TerminalStatus) -> None:
        """将当前状态设置为唯一终态。

        Args:
            status: 业务终态。

        Raises:
            StateTransitionError: 当前阶段不允许该终态或已经终止。
        """
        if self.terminal_status is not None:
            raise StateTransitionError("terminal status has already been assigned")
        terminal_phase = RunPhase(status.value)
        self.transition(terminal_phase)
        self.terminal_status = status
