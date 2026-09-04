"""定义报告进度的稳定内部合同，不依赖 HTTP、ORM 或具体消息中间件。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

REPORT_PROGRESS_PROTOCOL_VERSION = "report-progress-v1"


class ReportStage(str, Enum):
    """报告生成过程中允许公开的低基数业务阶段。"""

    PREPARING = "PREPARING"
    FUNDAMENTAL_ANALYSIS = "FUNDAMENTAL_ANALYSIS"
    TECHNICAL_ANALYSIS = "TECHNICAL_ANALYSIS"
    VALUATION_ANALYSIS = "VALUATION_ANALYSIS"
    NEWS_ANALYSIS = "NEWS_ANALYSIS"
    PERSONALIZATION = "PERSONALIZATION"
    SYNTHESIZING = "SYNTHESIZING"


class ReportStageStatus(str, Enum):
    """单个报告阶段的有限生命周期状态。"""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ReportTaskStatus(str, Enum):
    """数据库报告任务允许公开的状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReportStageSnapshot:
    """描述某个阶段在当前进程可观察到的最新状态。"""

    stage: ReportStage
    stage_status: ReportStageStatus


@dataclass(frozen=True, slots=True)
class ReportProgressNotification:
    """表示由真实执行边界产生的一条阶段变化。

    Args:
        task_id: 报告任务标识，用于隔离订阅者。
        report_id: 最终报告标识，不包含报告正文。
        stage: 当前公开业务阶段。
        stage_status: 阶段生命周期状态。
        progress: 任务级单调百分比，范围为 0～100。

    Raises:
        ValueError: 标识为空或进度越界时抛出。
    """

    task_id: str
    report_id: str
    stage: ReportStage
    stage_status: ReportStageStatus
    progress: int

    def __post_init__(self) -> None:
        if not self.task_id or not self.report_id:
            raise ValueError("task_id 和 report_id 不能为空")
        if not 0 <= self.progress <= 100:
            raise ValueError("progress 必须位于 0～100")


@dataclass(frozen=True, slots=True)
class ReportTerminalNotification:
    """表示数据库终态已经提交，可安全关闭观察连接。

    Args:
        task_id: 报告任务标识。
        report_id: 报告标识。
        status: 只允许 ``completed`` 或 ``failed``。
        progress: 数据库最终单调进度。
        error_code: 失败时的稳定低敏错误码。
        message: 面向用户的安全错误提示，不得包含原始异常。

    Raises:
        ValueError: 状态不是终态或进度越界时抛出。
    """

    task_id: str
    report_id: str
    status: ReportTaskStatus
    progress: int
    error_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {ReportTaskStatus.COMPLETED, ReportTaskStatus.FAILED}:
            raise ValueError("terminal notification 只接受 completed 或 failed")
        if not 0 <= self.progress <= 100:
            raise ValueError("progress 必须位于 0～100")


ReportProgressMessage: TypeAlias = ReportProgressNotification | ReportTerminalNotification


class ReportProgressPublisher(Protocol):
    """定义后台报告任务可替换的非阻塞进度发布端口。"""

    def publish(self, message: ReportProgressMessage) -> None:
        """发布一条可丢弃通知，不改变报告任务的成败语义。

        Args:
            message: 阶段或任务终态事实。
        """
