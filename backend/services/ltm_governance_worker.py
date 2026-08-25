"""消费统一 Memory Outbox 的长期记忆候选抽取与治理任务。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.memory.candidates import (
    CANDIDATE_EXTRACTOR_SCHEMA_VERSION,
    CandidateExtractionRequest,
    CandidateExtractionUseCase,
    CandidateSourceMessage,
    CandidateStateSignal,
)
from backend.config import settings
from backend.db.database import AsyncSessionFactory
from backend.db.models import (
    MemoryOutboxTaskRow,
    MemoryStateEventRow,
    MemorySummaryMetadataRow,
    MemoryWorkingStateRow,
    Message,
    Session,
)
from backend.infrastructure.memory.governance_repository import (
    SqlAlchemyCandidateGovernanceRepository,
)
from src.memory.contracts import (
    MEMORY_SCHEMA_VERSION,
    CandidateExtractPayload,
    MemoryContractError,
    MemoryErrorCode,
    MemorySource,
    OutboxTaskKind,
    OutboxTaskStatus,
    SummaryStatus,
    build_candidate_outbox_key,
)

logger = logging.getLogger(__name__)


class CandidateTaskValidationError(ValueError):
    """表示持久任务身份、版本或用户证据边界不可信。"""


class _CandidateProviderCallError(RuntimeError):
    """隔离候选模型调用失败与数据库/编程错误。"""


@dataclass(frozen=True, slots=True)
class _ClaimedTask:
    """携带单次领取独有的 fencing token。"""

    task_id: str
    lease_token: str
    trace_id: str | None


@dataclass(frozen=True, slots=True)
class _CandidateTaskInput:
    """保存已脱离数据库会话的冻结 REM 输入。"""

    task_id: str
    lease_token: str
    user_id: str
    trace_id: str | None
    payload: CandidateExtractPayload
    request: CandidateExtractionRequest


class LongTermGovernanceWorker:
    """以租约 fencing、有限重试和幂等事务执行候选治理。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        extraction: CandidateExtractionUseCase,
        worker_id: str,
        max_attempts: int,
        lease_seconds: int,
    ) -> None:
        if not worker_id.strip() or max_attempts < 1 or lease_seconds < 1:
            raise ValueError("worker_id, max_attempts and lease_seconds must be positive")
        self._session_factory = session_factory
        self._extraction = extraction
        self._worker_id = worker_id
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    async def process_next(self) -> bool:
        """领取并处理一个候选任务；队列为空时返回 ``False``。"""
        claim = await self._claim_next()
        if claim is None:
            return False
        if not claim.lease_token:
            return True
        started = datetime.now(UTC)
        try:
            task_input = await self._load_input(claim.task_id, claim.lease_token)
            if task_input is None:
                return True
            try:
                drafts = await self._extraction.execute(request=task_input.request)
            except MemoryContractError:
                raise
            except Exception as exc:
                raise _CandidateProviderCallError(
                    "candidate provider call failed"
                ) from exc
            result = await self._apply(task_input, drafts)
            logger.info(
                "memory.candidate.govern task_id=%s trace_id=%s stage=%s status=%s "
                "elapsed_ms=%d extracted_count=%d created_count=%d promoted_count=%d "
                "confirmation_required_count=%d conflicted_count=%d",
                task_input.task_id,
                task_input.trace_id,
                "memory.candidate.govern",
                "SUCCEEDED" if result is not None else "SKIPPED",
                int((datetime.now(UTC) - started).total_seconds() * 1000),
                result.extracted_count if result else 0,
                result.created_count if result else 0,
                result.promoted_count if result else 0,
                result.confirmation_required_count if result else 0,
                result.conflicted_count if result else 0,
            )
        except Exception as exc:
            recorded = await self._record_failure(
                claim.task_id,
                claim.lease_token,
                exc,
            )
            logger.warning(
                "memory.candidate.govern task_id=%s trace_id=%s stage=%s status=%s "
                "elapsed_ms=%d error_code=%s error_type=%s",
                claim.task_id,
                claim.trace_id,
                "memory.candidate.govern",
                "FAILED" if recorded else "SKIPPED",
                int((datetime.now(UTC) - started).total_seconds() * 1000),
                _error_code(exc).value,
                type(exc).__name__,
            )
        return True

    async def _claim_next(self) -> _ClaimedTask | None:
        """以跳过锁定行的方式领取到期任务并回收过期租约。"""
        now = _utc_naive()
        async with self._session_factory() as db:
            task = await db.scalar(
                select(MemoryOutboxTaskRow)
                .where(
                    MemoryOutboxTaskRow.task_kind
                    == OutboxTaskKind.CANDIDATE_EXTRACT.value,
                    or_(
                        and_(
                            MemoryOutboxTaskRow.status.in_(
                                (
                                    OutboxTaskStatus.PENDING.value,
                                    OutboxTaskStatus.RETRY.value,
                                )
                            ),
                            MemoryOutboxTaskRow.available_at <= now,
                        ),
                        and_(
                            MemoryOutboxTaskRow.status
                            == OutboxTaskStatus.PROCESSING.value,
                            MemoryOutboxTaskRow.lease_expires_at.is_not(None),
                            MemoryOutboxTaskRow.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(MemoryOutboxTaskRow.created_at, MemoryOutboxTaskRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if task is None:
                return None
            if (
                task.status == OutboxTaskStatus.PROCESSING.value
                and int(task.attempt_count or 0) >= self._max_attempts
            ):
                task.status = OutboxTaskStatus.DEAD_LETTER.value
                task.last_error_code = MemoryErrorCode.TASK_LEASE_CONFLICT.value
                task.completed_at = now
                task.lease_owner = None
                task.lease_expires_at = None
                await db.commit()
                return _ClaimedTask(task.id, "", task.trace_id)
            lease_token = f"{self._worker_id}:{uuid.uuid4().hex}"
            task.status = OutboxTaskStatus.PROCESSING.value
            task.attempt_count = int(task.attempt_count or 0) + 1
            task.lease_owner = lease_token
            task.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            await db.commit()
            return _ClaimedTask(task.id, lease_token, task.trace_id)

    async def _load_input(
        self,
        task_id: str,
        lease_token: str,
    ) -> _CandidateTaskInput | None:
        """复核任务身份、租约、摘要版本及全部用户侧来源。"""
        async with self._session_factory() as db:
            task = await self._leased_task(db, task_id, lease_token)
            if task is None:
                return None
            payload = _candidate_payload(task.payload_json)
            _validate_task_identity(task, payload)
            session = await db.get(Session, payload.session_id)
            if session is None or session.user_id != task.user_id:
                raise CandidateTaskValidationError(
                    "candidate task session ownership is invalid"
                )
            metadata = await db.scalar(
                select(MemorySummaryMetadataRow).where(
                    MemorySummaryMetadataRow.session_id == payload.session_id,
                    MemorySummaryMetadataRow.summary_version
                    == payload.expected_summary_version,
                    MemorySummaryMetadataRow.status == SummaryStatus.SUCCEEDED.value,
                    MemorySummaryMetadataRow.source_start_message_id
                    == payload.source_start_message_id,
                    MemorySummaryMetadataRow.source_end_message_id
                    == payload.source_end_message_id,
                )
            )
            if metadata is None:
                raise CandidateTaskValidationError(
                    "candidate task summary boundary is unavailable"
                )
            current_state_version = int(
                await db.scalar(
                    select(MemoryWorkingStateRow.state_version).where(
                        MemoryWorkingStateRow.session_id == payload.session_id
                    )
                )
                or 0
            )
            if current_state_version < payload.expected_state_version:
                raise CandidateTaskValidationError(
                    "candidate task working state version is unavailable"
                )
            messages = list(
                (
                    await db.execute(
                        select(Message)
                        .where(
                            Message.session_id == payload.session_id,
                            Message.role == "user",
                            Message.id >= payload.source_start_message_id,
                            Message.id <= payload.source_end_message_id,
                        )
                        .order_by(Message.id)
                    )
                )
                .scalars()
                .all()
            )
            if not messages:
                raise CandidateTaskValidationError(
                    "candidate task has no user-side source messages"
                )
            message_ids = {item.id for item in messages}
            state_events = list(
                (
                    await db.execute(
                        select(MemoryStateEventRow)
                        .where(
                            MemoryStateEventRow.session_id == payload.session_id,
                            MemoryStateEventRow.message_id.in_(message_ids),
                            MemoryStateEventRow.state_version
                            <= payload.expected_state_version,
                            MemoryStateEventRow.source == MemorySource.USER_MESSAGE.value,
                        )
                        .order_by(MemoryStateEventRow.id)
                    )
                )
                .scalars()
                .all()
            )
            request = CandidateExtractionRequest(
                session_id=payload.session_id,
                summary_version=payload.expected_summary_version,
                state_version=payload.expected_state_version,
                messages=tuple(
                    CandidateSourceMessage(
                        message_id=item.id,
                        content=item.content,
                        created_on=item.created_at.date(),
                        query_hash=_query_hash(item.content),
                    )
                    for item in messages
                ),
                state_signals=tuple(
                    CandidateStateSignal(
                        event_id=item.id,
                        message_id=cast(int, item.message_id),
                        field_name=item.field_name,
                        operation=item.operation,
                        value_text=_safe_state_value(item.new_value),
                        confidence=item.confidence,
                        state_version=item.state_version,
                    )
                    for item in state_events
                    if item.message_id is not None
                ),
                prompt_version=payload.prompt_version,
                schema_version=CANDIDATE_EXTRACTOR_SCHEMA_VERSION,
            )
            return _CandidateTaskInput(
                task_id=task.id,
                lease_token=lease_token,
                user_id=task.user_id,
                trace_id=task.trace_id,
                payload=payload,
                request=request,
            )

    async def _apply(self, task_input: _CandidateTaskInput, drafts):
        """在候选、权威记录、审计与任务终态的单一事务内应用草稿。"""
        async with self._session_factory() as db:
            task = await self._leased_task(
                db,
                task_input.task_id,
                task_input.lease_token,
            )
            if task is None:
                return None
            payload = _candidate_payload(task.payload_json)
            _validate_task_identity(task, payload)
            observed_user_ids = set(
                (
                    await db.execute(
                        select(Message.id).where(
                            Message.session_id == payload.session_id,
                            Message.role == "user",
                            Message.id.in_(
                                item.message_id for item in task_input.request.messages
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            expected_user_ids = {
                item.message_id for item in task_input.request.messages
            }
            if observed_user_ids != expected_user_ids:
                raise CandidateTaskValidationError(
                    "candidate user evidence changed before commit"
                )
            result = await SqlAlchemyCandidateGovernanceRepository(db).govern(
                user_id=task_input.user_id,
                drafts=drafts,
                prompt_version=payload.prompt_version,
                summary_version=payload.expected_summary_version,
                state_version=payload.expected_state_version,
                trace_id=task_input.trace_id,
            )
            task.status = OutboxTaskStatus.SUCCEEDED.value
            task.completed_at = _utc_naive()
            task.lease_owner = None
            task.lease_expires_at = None
            task.last_error_code = None
            await db.commit()
            return result

    async def _record_failure(
        self,
        task_id: str,
        lease_token: str,
        exc: Exception,
    ) -> bool:
        """只让可恢复错误有限重试，永久合同错误直接进入 dead-letter。"""
        async with self._session_factory() as db:
            task = await self._leased_task(db, task_id, lease_token)
            if task is None:
                return False
            error_code = _error_code(exc)
            permanent = isinstance(
                exc,
                (CandidateTaskValidationError, MemoryContractError),
            )
            attempts_exhausted = int(task.attempt_count or 0) >= self._max_attempts
            task.status = (
                OutboxTaskStatus.DEAD_LETTER.value
                if permanent or attempts_exhausted
                else OutboxTaskStatus.RETRY.value
            )
            task.last_error_code = error_code.value
            task.available_at = _utc_naive() + timedelta(
                seconds=min(60, 2 ** max(1, int(task.attempt_count or 1)))
            )
            task.completed_at = (
                _utc_naive()
                if task.status == OutboxTaskStatus.DEAD_LETTER.value
                else None
            )
            task.lease_owner = None
            task.lease_expires_at = None
            await db.commit()
            return True

    async def _leased_task(
        self,
        db: AsyncSession,
        task_id: str,
        lease_token: str,
    ) -> MemoryOutboxTaskRow | None:
        """用状态、token 与未过期时间共同 fence 旧 Worker。"""
        return await db.scalar(
            select(MemoryOutboxTaskRow)
            .where(
                MemoryOutboxTaskRow.id == task_id,
                MemoryOutboxTaskRow.status == OutboxTaskStatus.PROCESSING.value,
                MemoryOutboxTaskRow.lease_owner == lease_token,
                MemoryOutboxTaskRow.lease_expires_at > _utc_naive(),
            )
            .with_for_update()
        )


def build_ltm_governance_worker() -> LongTermGovernanceWorker:
    """同步构造生产 Worker，使 Provider 配置错误在启动边界可见。"""
    from backend.infrastructure.memory.candidates import build_candidate_extractor

    return LongTermGovernanceWorker(
        session_factory=cast(async_sessionmaker[AsyncSession], AsyncSessionFactory),
        extraction=CandidateExtractionUseCase(
            extractor=build_candidate_extractor(),
        ),
        worker_id="ltm-governance-worker",
        max_attempts=int(settings.ltm_worker_max_retries),
        lease_seconds=int(settings.ltm_worker_lease_sec),
    )


async def run_ltm_governance_worker(
    worker: LongTermGovernanceWorker,
    stop_event: asyncio.Event | None = None,
) -> None:
    """轮询一个已完成依赖校验的 Worker，支持生命周期停止信号。"""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        processed = 0
        for _ in range(int(settings.ltm_worker_batch_size)):
            if not await worker.process_next():
                break
            processed += 1
        if processed == 0:
            try:
                if stop_event is None:
                    await asyncio.sleep(float(settings.ltm_worker_interval_sec))
                else:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=float(settings.ltm_worker_interval_sec),
                    )
            except TimeoutError:
                pass


async def ltm_governance_worker_loop(
    stop_event: asyncio.Event | None = None,
) -> None:
    """构造并运行生产候选治理 Worker。"""
    await run_ltm_governance_worker(build_ltm_governance_worker(), stop_event)


def _candidate_payload(value: object) -> CandidateExtractPayload:
    """严格恢复持久 JSON，拒绝隐式字符串和布尔数值转换。"""
    if not isinstance(value, dict):
        raise CandidateTaskValidationError("candidate task payload must be an object")
    try:
        return CandidateExtractPayload(
            session_id=_required_text(value, "session_id"),
            expected_summary_version=_required_int(value, "expected_summary_version"),
            expected_state_version=_required_int(value, "expected_state_version"),
            source_start_message_id=_required_int(value, "source_start_message_id"),
            source_end_message_id=_required_int(value, "source_end_message_id"),
            prompt_version=_required_text(value, "prompt_version"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateTaskValidationError("candidate task payload is invalid") from exc


def _validate_task_identity(
    task: MemoryOutboxTaskRow,
    payload: CandidateExtractPayload,
) -> None:
    """复核持久任务全部冗余标识与幂等键。"""
    expected_key = build_candidate_outbox_key(
        payload.session_id,
        payload.expected_summary_version,
    )
    if (
        task.task_kind != OutboxTaskKind.CANDIDATE_EXTRACT.value
        or task.aggregate_type != "chat_summary"
        or task.session_id != payload.session_id
        or task.aggregate_id != payload.session_id
        or task.idempotency_key != expected_key
        or task.schema_version != MEMORY_SCHEMA_VERSION
    ):
        raise CandidateTaskValidationError(
            "candidate task persisted identity is inconsistent"
        )


def _required_int(value: dict[str, object], field_name: str) -> int:
    """读取严格整数字段，拒绝布尔值及字符串强转。"""
    field_value = value[field_name]
    if isinstance(field_value, bool) or not isinstance(field_value, int):
        raise TypeError(f"{field_name} must be an integer")
    return field_value


def _required_text(value: dict[str, object], field_name: str) -> str:
    """读取严格字符串字段。"""
    field_value = value[field_name]
    if not isinstance(field_value, str):
        raise TypeError(f"{field_name} must be text")
    return field_value


def _query_hash(content: str) -> str:
    """生成不可逆 query hash，避免治理表复制用户原话。"""
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_state_value(value: object) -> str:
    """仅向抽取器传递有限状态值；日志和审计均不使用该文本。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:500]


def _error_code(exc: Exception) -> MemoryErrorCode:
    """将后台失败归一为稳定码，不记录异常正文。"""
    if isinstance(exc, (CandidateTaskValidationError, MemoryContractError)):
        return MemoryErrorCode.INVALID_CONTRACT
    if isinstance(exc, _CandidateProviderCallError):
        return MemoryErrorCode.PROVIDER_UNAVAILABLE
    return MemoryErrorCode.INTERNAL_ERROR


def _utc_naive() -> datetime:
    """返回与现有无时区数据库列一致的 UTC 时间。"""
    return datetime.now(UTC).replace(tzinfo=None)
