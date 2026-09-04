"""把数据库报告记录投影为不含正文和原始异常的安全任务快照。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.application.report_progress.contracts import ReportTaskStatus

REPORT_GENERATION_FAILED_CODE = "REPORT_GENERATION_FAILED"
REPORT_GENERATION_FAILED_MESSAGE = "报告生成失败，请稍后重试"


@dataclass(frozen=True, slots=True)
class ReportProgressSnapshot:
    """表示可通过 REST 或 SSE 公开的数据库权威任务状态。"""

    task_id: str
    report_id: str
    user_id: str | None
    status: ReportTaskStatus
    progress: int
    error_code: str | None
    message: str | None

    @property
    def is_terminal(self) -> bool:
        """返回任务是否已经进入不可逆终态。"""
        return self.status in {ReportTaskStatus.COMPLETED, ReportTaskStatus.FAILED}


def project_report_snapshot(
    *,
    task_id: str,
    report_id: str,
    user_id: str | None,
    status: str,
    progress: int,
) -> ReportProgressSnapshot:
    """将数据库原始字段转换为安全、范围受限的任务快照。

    Args:
        task_id: 报告任务标识。
        report_id: 报告标识。
        user_id: 报告所属用户；历史未绑定记录允许为 ``None``。
        status: 数据库任务状态。
        progress: 数据库任务进度，输出会限制在 0～100。

    Returns:
        不包含报告正文或原始异常的权威快照。

    Raises:
        ValueError: 数据库状态不在公开状态枚举内时抛出。
    """
    task_status = ReportTaskStatus(status)
    safe_progress = max(0, min(100, progress))
    failed = task_status is ReportTaskStatus.FAILED
    return ReportProgressSnapshot(
        task_id=task_id,
        report_id=report_id,
        user_id=user_id,
        status=task_status,
        progress=safe_progress,
        error_code=REPORT_GENERATION_FAILED_CODE if failed else None,
        message=REPORT_GENERATION_FAILED_MESSAGE if failed else None,
    )
