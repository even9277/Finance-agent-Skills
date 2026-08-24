"""定义受控对话主链唯一的强类型跨阶段合同。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from src.memory.contracts import WorkingStateUpdate

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
    REPLANNING = "REPLANNING"
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
    REPLAN = "replan"
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
    ROUTE_CONFIRMATION_REQUIRED = "ROUTE_CONFIRMATION_REQUIRED"
    REWRITE_CLARIFICATION_REQUIRED = "REWRITE_CLARIFICATION_REQUIRED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_TRANSIENT_FAILURE = "TOOL_TRANSIENT_FAILURE"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_INVALID_RESULT = "TOOL_INVALID_RESULT"
    TOOL_DEPENDENCY_FAILED = "TOOL_DEPENDENCY_FAILED"
    DUPLICATE_TOOL_ACTION = "DUPLICATE_TOOL_ACTION"
    EXECUTION_BUDGET_EXHAUSTED = "EXECUTION_BUDGET_EXHAUSTED"
    PLAN_INVALID = "PLAN_INVALID"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    STEP_BUDGET_EXHAUSTED = "STEP_BUDGET_EXHAUSTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EntityType(StrEnum):
    """理解链支持的金融实体类型。"""

    STOCK = "stock"
    FUND = "fund"
    SECTOR = "sector"
    INDEX = "index"


class RouteFamily(StrEnum):
    """与现有入口兼容的三类顶层路由。"""

    FINANCIAL_SOP = "financial-sop"
    TUSHARE_DATA = "tushare-data"
    FALLBACK = "fallback"


class RouteSource(StrEnum):
    """最终路由的可审计来源。"""

    USER_EXPLICIT = "user_explicit"
    STAGE1_HIGH = "stage1_high"
    STAGE1_LOW = "stage1_low"
    STAGE2 = "stage2"


class RouteStage1Outcome(StrEnum):
    """SOP 优先路由阶段的有限结果。"""

    HIT_HIGH = "sop_hit_high"
    HIT_LOW = "sop_hit_low"
    MISS = "sop_miss"


class RewriteKind(StrEnum):
    """三路 Rewrite 的稳定判别字段。"""

    FINANCIAL_SOP = "financial-sop"
    TUSHARE_DATA = "tushare-data"
    FALLBACK = "fallback"


class TimeScope(StrEnum):
    """Rewrite 从自然语言中抽取的有限时间范围。"""

    UNSPECIFIED = "unspecified"
    LATEST_TRADING_DAY = "latest_trading_day"
    RECENT_5_TRADING_DAYS = "recent_5_trading_days"


class ConstraintOperation(StrEnum):
    """本轮对既有约束的更新语义。"""

    MERGE = "merge"
    CLEAR = "clear"
    NO_UPDATE = "no_update"


class PreferenceOperation(StrEnum):
    """本轮回答偏好的更新语义。"""

    REPLACE = "replace"
    CLEAR = "clear"
    NO_UPDATE = "no_update"


class EvidenceDimension(StrEnum):
    """跨 Planner、Executor 和 Evidence 的稳定证据维度。"""

    BASIC_PROFILE = "basic_profile"
    MARKET_SNAPSHOT = "market_snapshot"
    FINANCIAL_INDICATOR = "financial_indicator"
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASHFLOW_STATEMENT = "cashflow_statement"
    FUND_BASIC = "fund_basic"
    ETF_BASIC = "etf_basic"
    FUND_NAV = "fund_nav"
    FUND_MARKET = "fund_market"
    FUND_SHARE = "fund_share"
    INDEX_DAILY = "index_daily"
    SECTOR_SNAPSHOT = "sector_snapshot"
    SECTOR_CONSTITUENTS = "sector_constituents"


class StepStatus(StrEnum):
    """工具步骤的归一化结果状态。"""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ToolArgumentKind(StrEnum):
    """工具参数 Schema 支持的有限标量类型。"""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"


class ToolSideEffect(StrEnum):
    """工具副作用等级；当前受控主链只允许只读工具。"""

    READ = "READ"
    WRITE = "WRITE"


class EvidenceStatus(StrEnum):
    """Verifier 对单条证据的验收状态。"""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EvidenceRole(StrEnum):
    """计划赋予证据的业务角色。"""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class EvidenceRejectionCode(StrEnum):
    """Verifier 拒绝单条证据时使用的稳定原因。"""

    STEP_FAILED = "STEP_FAILED"
    UNKNOWN_STEP = "UNKNOWN_STEP"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    ENTITY_MISMATCH = "ENTITY_MISMATCH"
    EMPTY_FACTS = "EMPTY_FACTS"
    INVALID_FACT = "INVALID_FACT"
    SOURCE_MISSING = "SOURCE_MISSING"
    STALE = "STALE"
    FUTURE_DATED = "FUTURE_DATED"
    CONFLICT = "CONFLICT"


class ClaimLevel(StrEnum):
    """当前证据允许回答的最高结论强度。"""

    ANALYTICAL = "ANALYTICAL"
    DESCRIPTIVE = "DESCRIPTIVE"
    REFUSE = "REFUSE"


class ControllerAction(StrEnum):
    """规则 Controller 可输出的有限动作。"""

    STOP = "STOP"
    REPLAN = "REPLAN"
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
    EMPTY_PLAN = "EMPTY_PLAN"
    STEP_LIMIT_EXCEEDED = "STEP_LIMIT_EXCEEDED"
    ARGUMENT_UNKNOWN = "ARGUMENT_UNKNOWN"
    ARGUMENT_REQUIRED = "ARGUMENT_REQUIRED"
    ARGUMENT_TYPE_MISMATCH = "ARGUMENT_TYPE_MISMATCH"
    ARGUMENT_OUT_OF_RANGE = "ARGUMENT_OUT_OF_RANGE"
    DUPLICATE_ACTION = "DUPLICATE_ACTION"
    WRITE_TOOL_FORBIDDEN = "WRITE_TOOL_FORBIDDEN"


@dataclass(frozen=True, slots=True)
class RunBudget:
    """限制单轮步骤和外部调用，防止隐式无限循环。

    Attributes:
        max_steps: 一轮最多记录的业务阶段数，不含终止事件。
        max_tool_attempts: 单个只读工具发生瞬时超时时的总尝试次数。
        max_replans: 证据缺口允许的最大补证重规划次数。
        max_plan_steps: 单个工具 DAG 允许的最大节点数。
        max_concurrency: 同一 DAG 层允许的最大并发只读调用数。
        per_tool_timeout_ms: 单次工具调用的超时毫秒数。
        total_tool_timeout_ms: 整个工具计划的总耗时预算毫秒数。
    """

    max_steps: int = 16
    max_tool_attempts: int = 2
    max_replans: int = 1
    max_plan_steps: int = 8
    max_concurrency: int = 4
    per_tool_timeout_ms: int = 8_000
    total_tool_timeout_ms: int = 25_000

    def __post_init__(self) -> None:
        if (
            self.max_steps < 1
            or self.max_tool_attempts < 1
            or self.max_replans < 0
            or self.max_plan_steps < 1
            or self.max_concurrency < 1
            or self.per_tool_timeout_ms < 1
            or self.total_tool_timeout_ms < self.per_tool_timeout_ms
        ):
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
    reply_preference_hint: str = ""
    working_entity: Entity | None = None
    working_candidates: tuple[Entity, ...] = ()
    reset_working_segment: bool = False


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
    resolved_entities: tuple[Entity, ...] = ()
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
    route_source: RouteSource = RouteSource.STAGE2
    stage1_outcome: RouteStage1Outcome = RouteStage1Outcome.MISS
    shortlist: tuple[str, ...] = ()
    requires_current_facts: bool = False
    fact_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    """从当前轮窄抽取、可与已确认约束合并的结果。"""

    items: tuple[str, ...] = ()
    operation: ConstraintOperation = ConstraintOperation.NO_UPDATE
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ReplyPreference:
    """只影响回答结构、不改变事实或权限的表达偏好。"""

    hint: str = ""
    operation: PreferenceOperation = PreferenceOperation.NO_UPDATE
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class SopRewriteResult:
    """Financial SOP 路由的结构化问题合同。"""

    effective_query: str
    entity: Entity | None
    entities: tuple[Entity, ...]
    requested_dimensions: tuple[EvidenceDimension, ...]
    skill_name: str | None
    data_requirements: tuple[str, ...]
    constraints: ConstraintSet
    reply_preference: ReplyPreference
    time_scope: TimeScope
    needs_clarification: bool = False
    clarification_question: str = ""
    route_mismatch: str = ""
    entity_conflict: str = ""
    kind: RewriteKind = RewriteKind.FINANCIAL_SOP


@dataclass(frozen=True, slots=True)
class TushareRewriteResult:
    """当前事实数据路由的结构化问题合同。"""

    effective_query: str
    entity: Entity | None
    entities: tuple[Entity, ...]
    requested_dimensions: tuple[EvidenceDimension, ...]
    data_requirements: tuple[str, ...]
    constraints: ConstraintSet
    reply_preference: ReplyPreference
    time_scope: TimeScope
    skill_name: str | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    route_mismatch: str = ""
    entity_conflict: str = ""
    kind: RewriteKind = RewriteKind.TUSHARE_DATA


@dataclass(frozen=True, slots=True)
class FallbackRewriteResult:
    """无需金融工具的解释或闲聊合同。"""

    effective_query: str
    entity: Entity | None
    entities: tuple[Entity, ...]
    requested_dimensions: tuple[EvidenceDimension, ...]
    constraints: ConstraintSet
    reply_preference: ReplyPreference
    time_scope: TimeScope
    data_requirements: tuple[str, ...] = ()
    skill_name: str | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    route_mismatch: str = ""
    entity_conflict: str = ""
    kind: RewriteKind = RewriteKind.FALLBACK


RewriteResult = SopRewriteResult | TushareRewriteResult | FallbackRewriteResult


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """从 Registry 冻结出的单个 Skill 安全元数据。"""

    name: str
    description: str
    version: str
    execution_mode: str
    allowed_tools: tuple[str, ...]
    reference_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillRoutingDescriptor:
    """Stage1 只可见的最小 Skill 路由视图。"""

    name: str
    description: str
    version: str
    execution_mode: str


@dataclass(frozen=True, slots=True)
class SkillExecutionView:
    """选中 Skill 后交给后续权限阶段的执行视图。"""

    name: str
    version: str
    execution_mode: str
    allowed_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillReferenceView:
    """渐进加载的引用路径视图；按合同不包含工具权限。"""

    skill_name: str
    version: str
    reference_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillCatalogSnapshot:
    """请求级不可变 Skill 元数据快照及其内容 hash。"""

    version: str
    skills: tuple[SkillDescriptor, ...]
    snapshot_hash: str

    @classmethod
    def create(
        cls,
        *,
        version: str,
        skills: tuple[SkillDescriptor, ...],
    ) -> SkillCatalogSnapshot:
        """排序、去重并创建可审计 Skill 快照。

        Args:
            version: 快照构建合同版本。
            skills: Registry 已校验的 Skill 描述。

        Returns:
            名称排序稳定且带内容 hash 的不可变快照。

        Raises:
            ContractViolationError: 名称重复、版本为空或 Skill 名为空。
        """
        if not version.strip():
            raise ContractViolationError("skill catalog version must not be blank")
        ordered = tuple(sorted(skills, key=lambda item: item.name))
        names = [item.name for item in ordered]
        if any(not name.strip() for name in names) or len(names) != len(set(names)):
            raise ContractViolationError("skill catalog contains blank or duplicate names")
        raw = "\n".join(
            "|".join(
                (
                    item.name,
                    item.description,
                    item.version,
                    item.execution_mode,
                    ",".join(item.allowed_tools),
                    ",".join(item.reference_paths),
                )
            )
            for item in ordered
        ).encode()
        return cls(
            version=version,
            skills=ordered,
            snapshot_hash=hashlib.sha256(raw).hexdigest(),
        )

    @classmethod
    def empty(cls) -> SkillCatalogSnapshot:
        """创建不暴露任何 SOP Skill 的安全默认快照。"""
        return cls.create(version="empty-v1", skills=())

    def require(self, name: str) -> SkillDescriptor:
        """返回已登记 Skill，否则以合同错误拒绝。"""
        for item in self.skills:
            if item.name == name:
                return item
        raise ContractViolationError(f"unknown skill: {name}")

    def routing_view(self) -> tuple[SkillRoutingDescriptor, ...]:
        """返回不含工具和引用正文的 Stage1 视图。"""
        return tuple(
            SkillRoutingDescriptor(
                name=item.name,
                description=item.description,
                version=item.version,
                execution_mode=item.execution_mode,
            )
            for item in self.skills
        )

    def execution_view(self, name: str) -> SkillExecutionView:
        """返回已选 Skill 的冻结执行白名单。"""
        item = self.require(name)
        return SkillExecutionView(
            name=item.name,
            version=item.version,
            execution_mode=item.execution_mode,
            allowed_tools=item.allowed_tools,
        )

    def reference_view(
        self,
        name: str,
        selected_paths: tuple[str, ...],
    ) -> SkillReferenceView:
        """只允许选择 Registry 已登记的引用路径。

        Args:
            name: 已选 Skill 名。
            selected_paths: 基于当前问题选出的引用相对路径。

        Returns:
            不携带工具权限的引用视图。

        Raises:
            ContractViolationError: 路径不属于该 Skill 的冻结索引。
        """
        item = self.require(name)
        if not set(selected_paths) <= set(item.reference_paths):
            raise ContractViolationError("reference path is outside the skill snapshot")
        return SkillReferenceView(
            skill_name=item.name,
            version=item.version,
            reference_paths=selected_paths,
        )


@dataclass(frozen=True, slots=True)
class SkillMatch:
    """Stage1 metadata-only Skill Discovery 的结构化输出。"""

    skill_name: str | None
    confidence: float
    outcome: RouteStage1Outcome
    shortlist: tuple[str, ...]
    reason: str


ToolArgumentValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class ToolArgument:
    """单个已结构化工具参数，不允许嵌套任意字典进入核心状态。"""

    name: str
    value: ToolArgumentValue


@dataclass(frozen=True, slots=True)
class ToolInputSpec:
    """Validator 使用的工具输入字段合同。"""

    name: str
    kind: ToolArgumentKind
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """从治理目录冻结到请求内的单工具只读执行政策。"""

    tool_name: str
    evidence_dimension: EvidenceDimension
    supported_entity_types: tuple[EntityType, ...]
    input_fields: tuple[ToolInputSpec, ...]
    api_family: str
    retryable: bool
    side_effect: ToolSideEffect = ToolSideEffect.READ


@dataclass(frozen=True, slots=True)
class ToolPermissionSnapshot:
    """Planner 与 Executor 共享的请求级只读工具权限快照。"""

    permissions: tuple[ToolPolicy, ...]
    source: str
    version: str
    snapshot_hash: str

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        """返回排序稳定的工具名，供 Planner 和 Trace 使用。"""
        return tuple(item.tool_name for item in self.permissions)

    def require(self, tool_name: str) -> ToolPolicy:
        """读取已冻结政策；未授权工具以合同错误拒绝。"""
        for item in self.permissions:
            if item.tool_name == tool_name:
                return item
        raise ContractViolationError(f"tool is not permitted: {tool_name}")

    @classmethod
    def create(
        cls,
        *,
        permissions: tuple[ToolPolicy, ...],
        source: str,
        version: str,
    ) -> ToolPermissionSnapshot:
        """创建排序、去重且包含参数 Schema 的权限快照。

        Args:
            permissions: 从治理目录选择出的只读工具政策。
            source: 权限规则来源，必须是稳定低基数字符串。
            version: 工具治理合同版本。

        Returns:
            可在计划、校验、执行和 Trace 中复核的不可变快照。

        Raises:
            ContractViolationError: 来源/版本为空、工具重名或包含写工具。
        """
        if not source.strip() or not version.strip():
            raise ContractViolationError("permission source and version must not be blank")
        ordered = tuple(sorted(permissions, key=lambda item: item.tool_name))
        names = tuple(item.tool_name for item in ordered)
        if len(names) != len(set(names)) or any(not name.strip() for name in names):
            raise ContractViolationError("permission snapshot contains duplicate or blank tools")
        if any(item.side_effect is not ToolSideEffect.READ for item in ordered):
            raise ContractViolationError("controlled conversation permits read-only tools only")
        raw = "\n".join(
            "|".join(
                (
                    item.tool_name,
                    item.evidence_dimension.value,
                    ",".join(entity.value for entity in item.supported_entity_types),
                    ",".join(
                        f"{field.name}:{field.kind.value}:{int(field.required)}:{field.minimum}:{field.maximum}"
                        for field in item.input_fields
                    ),
                    item.api_family,
                    str(int(item.retryable)),
                    item.side_effect.value,
                )
            )
            for item in ordered
        )
        payload = "|".join((source, version, raw)).encode()
        return cls(
            permissions=ordered,
            source=source,
            version=version,
            snapshot_hash=hashlib.sha256(payload).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    """计划必须覆盖的证据维度。"""

    dimension: EvidenceDimension
    required: bool
    entity_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class ToolPlanStep:
    """DAG 中的一个只读工具动作。"""

    step_id: str
    tool_name: str
    symbol: str
    evidence_dimension: EvidenceDimension
    required: bool
    arguments: tuple[ToolArgument, ...] = ()
    idempotency_key: str = ""
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolPlan:
    """未经校验、绝不允许直接执行的结构化工具计划。"""

    plan_id: str
    entity: Entity | None
    steps: tuple[ToolPlanStep, ...]
    requirements: tuple[EvidenceRequirement, ...]
    trace_id: str = ""
    route_family: RouteFamily = RouteFamily.TUSHARE_DATA
    objective: str = ""
    entities: tuple[Entity, ...] = ()


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
    permissions: ToolPermissionSnapshot
    execution_layers: tuple[tuple[str, ...], ...]

    @property
    def permission_hash(self) -> str:
        """返回校验时冻结的权限 hash。"""
        return self.permissions.snapshot_hash


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
    arguments: tuple[ToolArgument, ...] = ()
    idempotency_key: str = ""


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
    batch_count: int = 0
    deduplicated_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """Verifier 已验收或拒绝的证据信封。"""

    evidence_id: str
    plan_id: str
    step_id: str
    tool_name: str
    entity_symbol: str
    evidence_dimension: EvidenceDimension
    role: EvidenceRole
    facts: tuple[EvidenceFact, ...]
    source: str
    observed_at: date
    status: EvidenceStatus
    quality_score: int
    freshness_days: int
    rejection_code: EvidenceRejectionCode | None = None
    source_error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class EvidenceScoreBreakdown:
    """按主语、时效、覆盖、角色和质量计算的可解释评分。"""

    entity: int
    freshness: int
    coverage: int
    role: int
    quality: int
    total: int


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """证据门控结果和当前允许的结论强度。"""

    accepted: tuple[EvidenceEnvelope, ...]
    rejected: tuple[EvidenceEnvelope, ...]
    missing_dimensions: tuple[EvidenceDimension, ...]
    missing_requirements: tuple[EvidenceRequirement, ...]
    claim_level: ClaimLevel
    recoverable: bool
    score: EvidenceScoreBreakdown
    hard_gate_failures: tuple[EvidenceRejectionCode, ...] = ()


@dataclass(frozen=True, slots=True)
class ControllerRuntimeState:
    """Controller 决策所需的最小、有界循环状态。"""

    replan_count: int = 0
    previous_missing_requirements: tuple[EvidenceRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class ControllerDecision:
    """基于证据和剩余预算产生的有限控制动作。"""

    action: ControllerAction
    reason: str
    terminal_status: TerminalStatus | None
    retries_remaining: int
    replans_remaining: int


@dataclass(frozen=True, slots=True)
class ReplanResult:
    """一次补证规划的结构化结果；空计划表示不能安全补证。"""

    plan: ToolPlan | None
    reason: str
    attempt: int
    added_requirements: tuple[EvidenceRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutedPlanStep:
    """提供给 Synthesis 的无参数执行摘要。"""

    plan_id: str
    step_id: str
    tool_name: str
    status: StepStatus
    evidence_dimension: EvidenceDimension
    replanned: bool


@dataclass(frozen=True, slots=True)
class RejectedEvidenceSummary:
    """不包含事实值、仅用于解释回答限制的拒绝摘要。"""

    step_id: str
    tool_name: str
    evidence_dimension: EvidenceDimension
    rejection_code: EvidenceRejectionCode
    facts: tuple[EvidenceFact, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerContextPack:
    """Synthesis 唯一允许消费的、只含 accepted evidence 的上下文。"""

    question: str
    effective_query: str
    entities: tuple[Entity, ...]
    executed_plan: tuple[ExecutedPlanStep, ...]
    accepted_evidence: tuple[EvidenceEnvelope, ...]
    rejected_evidence: tuple[EvidenceEnvelope, ...]
    rejection_summaries: tuple[RejectedEvidenceSummary, ...]
    missing_dimensions: tuple[EvidenceDimension, ...]
    claim_level: ClaimLevel
    terminal_status: TerminalStatus
    constraints: tuple[str, ...]
    reply_preference: str
    selected_skill: str | None

    @property
    def entity(self) -> Entity | None:
        """返回主实体；无实体任务保持为空而不是伪造 symbol。"""
        return self.entities[0] if self.entities else None

    @classmethod
    def create(
        cls,
        *,
        question: str,
        effective_query: str,
        entities: tuple[Entity, ...],
        executed_plan: tuple[ExecutedPlanStep, ...],
        verification: VerificationResult,
        terminal_status: TerminalStatus,
        constraints: tuple[str, ...],
        reply_preference: str,
        selected_skill: str | None,
    ) -> AnswerContextPack:
        """从 Verifier 结果构造不含 rejected facts 的回答包。

        Args:
            question: 用户当前轮原始问题。
            effective_query: Rewrite 后的执行意图。
            entities: 本轮权威实体集合。
            executed_plan: 不暴露参数和载荷的执行摘要。
            verification: 唯一证据验收结果。
            terminal_status: Controller 裁定的最终回答状态。
            constraints: 本轮已确认的业务约束摘要。
            reply_preference: 本轮回答风格提示。
            selected_skill: 可选的已确认 Skill 名称。

        Returns:
            仅含 accepted facts 和无事实拒绝摘要的不可变上下文。
        """
        summaries = tuple(
            RejectedEvidenceSummary(
                step_id=item.step_id,
                tool_name=item.tool_name,
                evidence_dimension=item.evidence_dimension,
                rejection_code=item.rejection_code or EvidenceRejectionCode.CONTRACT_MISMATCH,
            )
            for item in verification.rejected
        )
        return cls(
            question=question,
            effective_query=effective_query,
            entities=entities,
            executed_plan=executed_plan,
            accepted_evidence=verification.accepted,
            rejected_evidence=(),
            rejection_summaries=summaries,
            missing_dimensions=verification.missing_dimensions,
            claim_level=verification.claim_level,
            terminal_status=terminal_status,
            constraints=constraints,
            reply_preference=reply_preference,
            selected_skill=selected_skill,
        )


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
    working_state_update: WorkingStateUpdate | None = None


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
        {
            RunPhase.PLANNED,
            RunPhase.SYNTHESIZING,
            RunPhase.NEEDS_CLARIFICATION,
            RunPhase.FAILED,
        }
    ),
    RunPhase.PLANNED: frozenset({RunPhase.VALIDATED, RunPhase.FAILED}),
    RunPhase.VALIDATED: frozenset({RunPhase.EXECUTING, RunPhase.REJECTED, RunPhase.FAILED}),
    RunPhase.EXECUTING: frozenset({RunPhase.VERIFIED, RunPhase.CANCELLED, RunPhase.FAILED}),
    RunPhase.VERIFIED: frozenset(
        {RunPhase.REPLANNING, RunPhase.SYNTHESIZING, RunPhase.FAILED}
    ),
    RunPhase.REPLANNING: frozenset({RunPhase.VALIDATED, RunPhase.SYNTHESIZING, RunPhase.FAILED}),
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
