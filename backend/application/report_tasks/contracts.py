"""定义报告任务幂等创建与持久快照的稳定应用合同。"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.application.report_progress.contracts import (
    ReportStage,
    ReportStageStatus,
    ReportTaskStatus,
)

IDEMPOTENCY_KEY_MIN_LENGTH = 8
IDEMPOTENCY_KEY_MAX_LENGTH = 128
REPORT_IDEMPOTENCY_ERROR_CODE = "INVALID_IDEMPOTENCY_KEY"
REPORT_IDEMPOTENCY_CONFLICT_CODE = "IDEMPOTENCY_KEY_CONFLICT"
_SCOPED_DIGEST_DOMAIN = "report-task-governance-v1"
_WHITESPACE_PATTERN = re.compile(r"\s+")


class ReportIdempotencyStatus(StrEnum):
    """报告创建接口允许公开的幂等结果。"""

    CREATED = "CREATED"
    REPLAYED = "REPLAYED"


class ExistingReportTaskDecision(StrEnum):
    """数据库已有治理行面对当前请求时的有限决策。"""

    REPLAY = "REPLAY"
    ROTATE = "ROTATE"
    CONFLICT = "CONFLICT"


class ReportIdempotencyValidationError(ValueError):
    """表示显式幂等键不满足公开边界，且不保留原始键值。"""

    error_code = REPORT_IDEMPOTENCY_ERROR_CODE

    def __init__(self) -> None:
        super().__init__("显式幂等键必须是 8 到 128 个无空白可见 ASCII 字符")


class ReportIdempotencyConflictError(RuntimeError):
    """表示同一用户把已有显式键用于不同报告请求。"""

    error_code = REPORT_IDEMPOTENCY_CONFLICT_CODE

    def __init__(self) -> None:
        super().__init__("幂等键已绑定其他报告请求")


class ReportStageSnapshot(BaseModel):
    """保存一个报告阶段的最新低敏状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: ReportStage
    status: ReportStageStatus


class ReportTaskSnapshot(BaseModel):
    """保存可跨实例恢复的最新报告任务快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    status: ReportTaskStatus
    progress: int = Field(ge=0, le=100)
    stages: tuple[ReportStageSnapshot, ...] = ()
    updated_at: datetime
    error_code: str | None = None
    message: str | None = None


class ReportTaskSnapshotRecord(BaseModel):
    """组合数据库快照与 Redis 镜像所需的不可逆所有权材料。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1)
    key_digest: str = Field(min_length=64, max_length=64)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    snapshot: ReportTaskSnapshot


class ReportTaskSnapshotUpdate(BaseModel):
    """描述一次需要与 Report 同事务提交的任务快照变化。

    ``report_content`` 只在完成终态写入，``report_error_msg`` 只在失败终态
    写入。两者均不会进入 Redis 或 SSE 快照。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    status: ReportTaskStatus
    progress: int = Field(ge=0, le=100)
    stages: tuple[ReportStageSnapshot, ...] = ()
    report_content: str | None = None
    report_error_msg: str | None = None

    def model_post_init(self, _context: object) -> None:
        """拒绝把报告正文或错误文本附着到非对应终态。"""
        if self.report_content is not None and self.status is not ReportTaskStatus.COMPLETED:
            raise ValueError("report_content 只允许 completed 快照写入")
        if self.report_error_msg is not None and self.status is not ReportTaskStatus.FAILED:
            raise ValueError("report_error_msg 只允许 failed 快照写入")


class ReportTaskClaim(BaseModel):
    """承载应用层交给数据库适配器的低敏创建声明。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1)
    key_digest: str = Field(min_length=64, max_length=64)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    expires_at: datetime


class ReportTaskCreateResult(BaseModel):
    """返回原子创建或复用的任务标识与派发所有权。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    status: ReportTaskStatus
    idempotency_status: ReportIdempotencyStatus
    expires_at: datetime
    generation: int = Field(ge=1)

    @property
    def should_dispatch(self) -> bool:
        """仅首次创建或过期换代的获胜请求拥有后台派发权。"""
        return self.idempotency_status is ReportIdempotencyStatus.CREATED


def normalize_report_command(command: str) -> str:
    """按 NFKC 与空白折叠生成跨实例一致的报告命令。"""
    return _WHITESPACE_PATTERN.sub(" ", unicodedata.normalize("NFKC", command).strip())


def validate_idempotency_key(value: str) -> str:
    """校验显式幂等键，拒绝空白、非 ASCII 和越界长度。

    Args:
        value: HTTP ``Idempotency-Key`` 原值。

    Returns:
        已通过校验且未改写的键值。

    Raises:
        ReportIdempotencyValidationError: 键值不满足 8..128 可见 ASCII 合同。
    """
    if not IDEMPOTENCY_KEY_MIN_LENGTH <= len(value) <= IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ReportIdempotencyValidationError
    if any(not 0x21 <= ord(character) <= 0x7E for character in value):
        raise ReportIdempotencyValidationError
    return value


def build_report_request_fingerprint(command: str) -> str:
    """生成不暴露报告命令正文的稳定 SHA-256 指纹。"""
    normalized = normalize_report_command(command)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_effective_idempotency_material(command: str, client_key: str | None) -> str:
    """按显式请求意图或旧客户端命令哈希构造有效键材料。"""
    if client_key is not None:
        return f"client:{validate_idempotency_key(client_key)}"
    return f"command:{build_report_request_fingerprint(command)}"


def build_scoped_idempotency_digest(
    *,
    user_id: str,
    effective_material: str,
    secret: str,
) -> str:
    """生成用户作用域内、与其他 HMAC 用途隔离的不可逆摘要。

    Args:
        user_id: 已通过认证所有权校验的内部用户标识。
        effective_material: 显式键或命令哈希形成的有效键材料。
        secret: 由 typed Settings 注入的服务器秘密。

    Returns:
        固定 64 位小写十六进制 HMAC-SHA256 摘要。
    """
    payload = f"{_SCOPED_DIGEST_DOMAIN}:{user_id}:{effective_material}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def decide_existing_report_task(
    *,
    existing_fingerprint: str,
    request_fingerprint: str,
    task_status: str,
    expires_at: datetime,
    now: datetime,
) -> ExistingReportTaskDecision:
    """根据指纹、任务状态与期限决定复用、换代或冲突。

    进行中和未知状态均保守复用，避免 TTL 到期放行第二个付费工作流；只有
    ``completed/failed`` 终态过期后才允许原子换代。
    """
    if not hmac.compare_digest(existing_fingerprint, request_fingerprint):
        return ExistingReportTaskDecision.CONFLICT
    if task_status not in {ReportTaskStatus.COMPLETED.value, ReportTaskStatus.FAILED.value}:
        return ExistingReportTaskDecision.REPLAY
    comparable_expiry = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
    comparable_now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    if comparable_now < comparable_expiry:
        return ExistingReportTaskDecision.REPLAY
    return ExistingReportTaskDecision.ROTATE
