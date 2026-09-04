"""定义受控对话面向 Application 的协议无关实时进度合同。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .contracts import (
    ErrorCode,
    EvidenceDimension,
    StageName,
    StageStatus,
    ToolArgument,
    ToolObservation,
    ValidatedToolPlan,
    VerificationResult,
)


class ProgressStepStatus(StrEnum):
    """步骤在用户可观察执行过程中的有限生命周期。"""

    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    REPLANNED = "REPLANNED"
    CANCELLED = "CANCELLED"


class ProgressToolStatus(StrEnum):
    """单次工具尝试在用户可观察执行过程中的有限生命周期。"""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class TraceSummaryProgress:
    """表示一个可向用户概括、但不携带 Trace attributes 的阶段状态。"""

    stage: StageName
    status: StageStatus
    elapsed_ms: float
    error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class PlanPreviewProgress:
    """表示已经通过 Validator 的计划版本，禁止接受原始 ``ToolPlan``。"""

    validated_plan: ValidatedToolPlan
    revision: int
    replan_reason: str | None = None
    replaced_step_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("plan revision must start from one")


@dataclass(frozen=True, slots=True)
class StepStatusProgress:
    """表示一个稳定步骤 ID 的权威执行状态变化。"""

    plan_id: str
    revision: int
    step_id: str
    status: ProgressStepStatus
    elapsed_ms: float | None = None
    error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class ToolStatusProgress:
    """表示一次真实或明确跳过的工具尝试及其内部投影输入。"""

    plan_id: str
    revision: int
    tool_call_id: str
    step_id: str
    tool_name: str
    symbol: str
    evidence_dimension: EvidenceDimension
    arguments: tuple[ToolArgument, ...]
    status: ProgressToolStatus
    attempt: int
    elapsed_ms: float | None = None
    observation: ToolObservation | None = None
    error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class VerificationSummaryProgress:
    """表示 Evidence Verifier 对当前计划版本给出的权威结论。"""

    plan_id: str
    revision: int
    verification: VerificationResult


type ConversationProgressEvent = (
    TraceSummaryProgress
    | PlanPreviewProgress
    | StepStatusProgress
    | ToolStatusProgress
    | VerificationSummaryProgress
)


class ConversationProgressObserver(Protocol):
    """接收领域进度并把背压与取消传播回真实执行链。"""

    async def on_progress(self, event: ConversationProgressEvent) -> None:
        """接收一个有序事件；失败或取消必须原样传播。"""
        ...


async def emit_progress(
    observer: ConversationProgressObserver | None,
    event: ConversationProgressEvent,
) -> None:
    """仅在调用方提供 observer 时发布进度。

    Args:
        observer: 流式 Application 提供的请求级观察器；同步调用为空。
        event: 从领域权威状态转换点构造的强类型事件。

    Raises:
        BaseException: 观察器的背压、传输失败或取消原样向上游传播。
    """
    if observer is not None:
        await observer.on_progress(event)
