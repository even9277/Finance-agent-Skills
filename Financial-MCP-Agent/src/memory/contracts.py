"""定义记忆子系统跨领域、应用和基础设施边界的强类型合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

MEMORY_SCHEMA_VERSION = "memory-v1"
MEMORY_POLICY_VERSION = "memory-policy-v1"


class MemoryScope(StrEnum):
    """限定一条状态或记忆允许生效的时间与业务范围。"""

    THIS_TURN = "this_turn"
    SESSION_SEGMENT = "session_segment"
    SESSION = "session"
    USER = "user"


class MemoryValueKind(StrEnum):
    """区分结构化画像与可检索文本记忆。"""

    STRUCTURED_PROFILE = "structured_profile"
    TEXT = "text"


class MemorySource(StrEnum):
    """记录状态或记忆事实的可审计来源。"""

    USER_COMMAND = "user_command"
    USER_UI = "user_ui"
    USER_CONFIRMATION = "user_confirmation"
    USER_MESSAGE = "user_message"
    MODEL_INFERRED = "model_inferred"
    SYSTEM = "system"


class WorkingStateField(StrEnum):
    """Working State 允许变更的有限字段。"""

    ACTIVE_ENTITY = "active_entity"
    CONSTRAINTS = "constraints"
    REPLY_PREFERENCE_HINT = "reply_preference_hint"


class StateOperation(StrEnum):
    """Working State 事件的有限状态转换动作。"""

    SET = "set"
    MERGE = "merge"
    CLEAR = "clear"
    EXPIRE = "expire"
    NOOP = "noop"


class ProfileField(StrEnum):
    """由用户或确认流程拥有最终权威的投资画像字段。"""

    RISK_LEVEL = "risk_level"
    INVESTMENT_HORIZON = "investment_horizon"
    EXPECTED_RETURN_MIN = "expected_return_min"
    EXPECTED_RETURN_MAX = "expected_return_max"
    SECTORS = "sectors"
    WATCHLIST = "watchlist"
    CONSTRAINTS = "constraints"


class CandidateStatus(StrEnum):
    """长期记忆候选在治理流程中的稳定状态。"""

    PENDING = "PENDING"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class MemoryRecordStatus(StrEnum):
    """PostgreSQL 权威记忆记录的生命周期状态。"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"


class SummaryStatus(StrEnum):
    """Rolling Summary 生成与生效过程的稳定状态。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STALE = "STALE"


class ActivationSource(StrEnum):
    """说明候选为何可以成为有效记忆。"""

    EXPLICIT_USER = "explicit_user"
    USER_CONFIRMED = "user_confirmed"
    POLICY_AUTO = "policy_auto"


class OutboxTaskKind(StrEnum):
    """由 PostgreSQL 持久化并交给后台 Worker 的任务类型。"""

    TURN_COMMITTED = "TURN_COMMITTED"
    STATE_EXTRACT = "STATE_EXTRACT"
    SUMMARY_COMPACT = "SUMMARY_COMPACT"
    CANDIDATE_EXTRACT = "CANDIDATE_EXTRACT"
    INDEX_UPSERT = "INDEX_UPSERT"
    INDEX_DELETE = "INDEX_DELETE"
    CACHE_INVALIDATE = "CACHE_INVALIDATE"


class OutboxTaskStatus(StrEnum):
    """Outbox 任务的机器可消费生命周期。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRY = "RETRY"
    SUCCEEDED = "SUCCEEDED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


class ProviderReferenceStatus(StrEnum):
    """派生 Provider 映射相对权威记录的一致性状态。"""

    ACTIVE = "ACTIVE"
    STALE = "STALE"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"
    FAILED = "FAILED"


class MemoryCommandAction(StrEnum):
    """聊天入口允许识别的记忆控制动作。"""

    INSPECT = "INSPECT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    FORGET = "FORGET"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


class MemoryCommandStatus(StrEnum):
    """记忆控制命令的有限执行结果。"""

    NOT_A_COMMAND = "NOT_A_COMMAND"
    READY = "READY"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class RetrievalStatus(StrEnum):
    """混合召回面对空结果或依赖降级时的显式状态。"""

    SUCCEEDED = "SUCCEEDED"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class MemoryErrorCode(StrEnum):
    """跨层传播但不暴露底层异常文本的稳定错误码。"""

    INVALID_CONTRACT = "INVALID_CONTRACT"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    PERSISTENCE_CONSTRAINT_VIOLATION = "PERSISTENCE_CONSTRAINT_VIOLATION"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    TASK_LEASE_CONFLICT = "TASK_LEASE_CONFLICT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MemoryContractError(ValueError):
    """表示调用方构造了不满足记忆领域约束的合同。"""

    code = MemoryErrorCode.INVALID_CONTRACT


class DuplicateOutboxTaskError(RuntimeError):
    """表示事务尝试写入已经存在的幂等 Outbox 任务。"""

    code = MemoryErrorCode.DUPLICATE_IDEMPOTENCY_KEY


def _require_nonblank(value: str, field_name: str) -> None:
    if not value.strip():
        raise MemoryContractError(f"{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class WorkingEntity:
    """保存会话 Working State 中可继承但不可冒充市场证据的实体。"""

    symbol: str
    name: str
    entity_type: str

    def __post_init__(self) -> None:
        _require_nonblank(self.symbol, "symbol")
        _require_nonblank(self.name, "name")
        _require_nonblank(self.entity_type, "entity_type")


@dataclass(frozen=True, slots=True)
class WorkingState:
    """表示一个会话当前可恢复、可版本比较的短期工作状态。"""

    active_entity: WorkingEntity | None = None
    candidate_entities: tuple[WorkingEntity, ...] = ()
    constraints: tuple[str, ...] = ()
    reply_preference_hint: str = ""
    scope: MemoryScope = MemoryScope.SESSION_SEGMENT
    state_version: int = 0
    schema_version: str = MEMORY_SCHEMA_VERSION
    source_message_id: int | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.state_version < 0:
            raise MemoryContractError("state_version must be non-negative")
        if self.source_message_id is not None and self.source_message_id <= 0:
            raise MemoryContractError("source_message_id must be positive")
        if len(self.constraints) > 8 or any(not item.strip() for item in self.constraints):
            raise MemoryContractError("constraints must contain 1-8 non-blank values")
        if len(self.reply_preference_hint) > 220:
            raise MemoryContractError("reply_preference_hint exceeds 220 characters")
        _require_nonblank(self.schema_version, "schema_version")


StateValue = WorkingEntity | tuple[WorkingEntity, ...] | tuple[str, ...] | str | None


@dataclass(frozen=True, slots=True)
class WorkingStateEvent:
    """记录一次可回放的 Working State 字段转换。"""

    session_id: str
    field: WorkingStateField
    operation: StateOperation
    old_value: StateValue
    new_value: StateValue
    source: MemorySource
    state_version: int
    schema_version: str = MEMORY_SCHEMA_VERSION
    message_id: int | None = None
    confidence: float = 1.0
    trace_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.session_id, "session_id")
        if self.state_version <= 0:
            raise MemoryContractError("event state_version must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise MemoryContractError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SummaryMetadata:
    """描述 Rolling Summary 的来源边界、版本和可恢复状态。"""

    session_id: str
    summary_version: int
    status: SummaryStatus
    source_start_message_id: int | None = None
    source_end_message_id: int | None = None
    source_message_count: int = 0
    input_token_estimate: int = 0
    output_token_count: int = 0
    prompt_version: str = ""
    schema_version: str = MEMORY_SCHEMA_VERSION
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.session_id, "session_id")
        _require_nonblank(self.status, "status")
        if min(
            self.summary_version,
            self.source_message_count,
            self.input_token_estimate,
            self.output_token_count,
        ) < 0:
            raise MemoryContractError("summary counters must be non-negative")


ProfileValue = str | float | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """表示 PostgreSQL 中可检查、可删除且按用户隔离的权威记忆。"""

    record_id: str
    user_id: str
    kind: MemoryValueKind
    category: str
    status: MemoryRecordStatus
    source: MemorySource
    version: int
    scope: MemoryScope = MemoryScope.USER
    profile_field: ProfileField | None = None
    value: ProfileValue | None = None
    content: str | None = None
    evidence_ref: str | None = None
    policy_version: str = MEMORY_POLICY_VERSION
    activation_source: ActivationSource = ActivationSource.EXPLICIT_USER
    expires_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.record_id, "record_id")
        _require_nonblank(self.user_id, "user_id")
        _require_nonblank(self.category, "category")
        if self.version <= 0:
            raise MemoryContractError("memory record version must be positive")
        if self.kind is MemoryValueKind.TEXT:
            if not (self.content or "").strip():
                raise MemoryContractError("text memory requires content")
            if self.profile_field is not None or self.value is not None:
                raise MemoryContractError("text memory cannot contain profile fields")
        if self.kind is MemoryValueKind.STRUCTURED_PROFILE:
            if self.profile_field is None or self.value is None:
                raise MemoryContractError(
                    "structured profile memory requires profile_field and value"
                )
            if self.content is not None:
                raise MemoryContractError(
                    "structured profile memory cannot contain text content"
                )
        if self.status is MemoryRecordStatus.ACTIVE and not (
            self.evidence_ref or ""
        ).strip():
            raise MemoryContractError("active memory requires evidence_ref")
        if (
            self.activation_source is ActivationSource.EXPLICIT_USER
            and self.source in {MemorySource.MODEL_INFERRED, MemorySource.SYSTEM}
        ):
            raise MemoryContractError(
                "explicit-user activation requires an explicit user source"
            )

        # 局部导入避免 contracts/policy 模块初始化环，同时保证任何构造路径都执行权威校验。
        from .policy import validate_record_authority

        validate_record_authority(self)


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """保存尚未取得权威效力的长期记忆候选及其证据。"""

    candidate_id: str
    user_id: str
    kind: MemoryValueKind
    category: str
    status: CandidateStatus
    source: MemorySource
    confidence: float
    fingerprint: str
    idempotency_key: str
    profile_field: ProfileField | None = None
    value: ProfileValue | None = None
    content: str | None = None
    evidence_ref: str | None = None
    conflict_group_id: str | None = None
    policy_version: str = MEMORY_POLICY_VERSION
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("candidate_id", self.candidate_id),
            ("user_id", self.user_id),
            ("category", self.category),
            ("fingerprint", self.fingerprint),
            ("idempotency_key", self.idempotency_key),
        ):
            _require_nonblank(value, field_name)
        if not 0.0 <= self.confidence <= 1.0:
            raise MemoryContractError("confidence must be between 0 and 1")
        if not (self.evidence_ref or "").strip():
            raise MemoryContractError("memory candidate requires evidence_ref")
        if self.kind is MemoryValueKind.TEXT:
            if not (self.content or "").strip():
                raise MemoryContractError("text candidate requires content")
            if self.profile_field is not None or self.value is not None:
                raise MemoryContractError("text candidate cannot contain profile fields")
        if self.kind is MemoryValueKind.STRUCTURED_PROFILE:
            if self.profile_field is None or self.value is None:
                raise MemoryContractError(
                    "structured profile candidate requires profile_field and value"
                )
            if self.content is not None:
                raise MemoryContractError(
                    "structured profile candidate cannot contain text content"
                )


class MemoryAuditAction(StrEnum):
    """权威记忆和候选生命周期允许记录的审计动作。"""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    CONFIRMED = "CONFIRMED"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    DELETE_REQUESTED = "DELETE_REQUESTED"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class MemoryAuditEvent:
    """保存不含原始对话正文的记忆状态变更审计事件。"""

    event_id: str
    user_id: str
    action: MemoryAuditAction
    actor: MemorySource
    record_id: str | None = None
    candidate_id: str | None = None
    before_status: CandidateStatus | MemoryRecordStatus | None = None
    after_status: CandidateStatus | MemoryRecordStatus | None = None
    reason_code: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.event_id, "event_id")
        _require_nonblank(self.user_id, "user_id")
        _require_nonblank(self.action, "action")
        if self.record_id is None and self.candidate_id is None:
            raise MemoryContractError("audit event requires record_id or candidate_id")


@dataclass(frozen=True, slots=True)
class TurnCommittedPayload:
    """通过行引用描述已提交对话轮次，不复制消息或画像正文。"""

    session_id: str
    user_message_id: int
    assistant_message_id: int
    state_version: int

    def __post_init__(self) -> None:
        _require_nonblank(self.session_id, "session_id")
        if self.user_message_id <= 0 or self.assistant_message_id <= 0:
            raise MemoryContractError("message ids must be positive")
        if self.user_message_id == self.assistant_message_id:
            raise MemoryContractError("user and assistant message ids must differ")
        if self.state_version < 0:
            raise MemoryContractError("state_version must be non-negative")


@dataclass(frozen=True, slots=True)
class NewOutboxTask:
    """表示尚未持久化、必须与业务状态同事务写入的任务意图。"""

    user_id: str
    aggregate_type: str
    aggregate_id: str
    task_kind: OutboxTaskKind
    idempotency_key: str
    payload: TurnCommittedPayload
    session_id: str | None = None
    trace_id: str | None = None
    schema_version: str = MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name, value in (
            ("user_id", self.user_id),
            ("aggregate_type", self.aggregate_type),
            ("aggregate_id", self.aggregate_id),
            ("idempotency_key", self.idempotency_key),
            ("schema_version", self.schema_version),
        ):
            _require_nonblank(value, field_name)
        if self.task_kind is OutboxTaskKind.TURN_COMMITTED:
            if self.session_id is None:
                raise MemoryContractError("turn-committed task requires session_id")
            if self.session_id != self.payload.session_id:
                raise MemoryContractError("outbox session_id must match payload")
            if self.aggregate_type != "chat_turn":
                raise MemoryContractError(
                    "turn-committed aggregate_type must be chat_turn"
                )
            if self.aggregate_id != self.payload.session_id:
                raise MemoryContractError("outbox aggregate_id must match payload session")
            expected_key = build_turn_outbox_key(
                self.payload.session_id,
                self.payload.user_message_id,
            )
            if self.idempotency_key != expected_key:
                raise MemoryContractError(
                    "outbox idempotency_key must match the committed user message"
                )


@dataclass(frozen=True, slots=True)
class OutboxTask:
    """表示已持久化且可被有限重试 Worker 领取的任务。"""

    task_id: str
    intent: NewOutboxTask
    status: OutboxTaskStatus = OutboxTaskStatus.PENDING
    attempt_count: int = 0
    available_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: MemoryErrorCode | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.task_id, "task_id")
        if self.attempt_count < 0:
            raise MemoryContractError("attempt_count must be non-negative")


@dataclass(frozen=True, slots=True)
class ProviderReference:
    """把权威记忆版本映射到可重建的外部派生索引记录。"""

    reference_id: str
    user_id: str
    memory_record_id: str
    provider: str
    provider_record_id: str
    memory_version: int
    status: ProviderReferenceStatus
    schema_version: str = MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name, value in (
            ("reference_id", self.reference_id),
            ("user_id", self.user_id),
            ("memory_record_id", self.memory_record_id),
            ("provider", self.provider),
            ("provider_record_id", self.provider_record_id),
        ):
            _require_nonblank(value, field_name)
        if self.memory_version <= 0:
            raise MemoryContractError("memory_version must be positive")


@dataclass(frozen=True, slots=True)
class MemoryCommand:
    """表示已分类但尚未执行的用户记忆控制意图。"""

    action: MemoryCommandAction
    user_id: str
    session_id: str
    target: str | None = None
    value: ProfileValue | None = None
    expected_version: int | None = None
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        _require_nonblank(self.user_id, "user_id")
        _require_nonblank(self.session_id, "session_id")
        if self.expected_version is not None and self.expected_version < 0:
            raise MemoryContractError("expected_version must be non-negative")


@dataclass(frozen=True, slots=True)
class MemoryCommandResult:
    """为 REST 与 WebSocket 提供协议无关的记忆命令结果。"""

    status: MemoryCommandStatus
    action: MemoryCommandAction | None = None
    affected_record_ids: tuple[str, ...] = ()
    pending_confirmation_id: str | None = None
    memory_version: int | None = None
    error_code: MemoryErrorCode | None = None


@dataclass(frozen=True, slots=True)
class RetrievalItem:
    """表示通过权威过滤后可进入上下文预算的单条记忆。"""

    record_id: str
    category: str
    content: str
    score: float
    retrieval_reasons: tuple[str, ...]
    memory_version: int

    def __post_init__(self) -> None:
        _require_nonblank(self.record_id, "record_id")
        _require_nonblank(self.category, "category")
        _require_nonblank(self.content, "content")
        if not 0.0 <= self.score <= 1.0:
            raise MemoryContractError("score must be between 0 and 1")
        if self.memory_version <= 0:
            raise MemoryContractError("memory_version must be positive")


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """表示有预算、可审计且显式降级的记忆召回结果。"""

    status: RetrievalStatus
    items: tuple[RetrievalItem, ...] = ()
    token_count: int = 0
    error_code: MemoryErrorCode | None = None
    degraded_providers: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.token_count < 0:
            raise MemoryContractError("token_count must be non-negative")


def build_turn_outbox_key(session_id: str, user_message_id: int) -> str:
    """构造同一用户消息只能出现一次的稳定 Outbox 幂等键。

    Args:
        session_id: 已持久化的会话标识。
        user_message_id: 当前轮用户消息主键。

    Returns:
        不包含消息正文或用户画像的稳定幂等键。

    Raises:
        MemoryContractError: 会话标识为空或消息主键无效。
    """
    _require_nonblank(session_id, "session_id")
    if user_message_id <= 0:
        raise MemoryContractError("user_message_id must be positive")
    return f"memory:turn-committed:{session_id}:{user_message_id}"
