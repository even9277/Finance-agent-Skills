"""报告相关 Pydantic 模型"""

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.application.report_progress.contracts import (
    REPORT_PROGRESS_PROTOCOL_VERSION,
    ReportStage,
    ReportStageStatus,
    ReportTaskStatus,
)


class ReportGenerateRequest(BaseModel):
    command: str = Field(..., description="用户的分析指令，例如：帮我分析茅台(600519)")
    user_id: str = Field(..., description="用户唯一标识")


class ReportTaskResponse(BaseModel):
    task_id: str
    report_id: str
    status: str = "pending"


class ReportStatusResponse(BaseModel):
    task_id: str
    status: str           # pending | running | completed | failed
    progress: int         # 0-100
    report_id: Optional[str] = None
    error_msg: Optional[str] = None
    error_code: Optional[str] = None


class ReportStageFrameState(BaseModel):
    """表示首帧中当前进程已经观察到的阶段状态。"""

    model_config = ConfigDict(extra="forbid")

    stage: ReportStage
    status: ReportStageStatus


class ReportProgressFrameBase(BaseModel):
    """定义 `report-progress-v1` 三类业务帧共享的关联字段。"""

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["report-progress-v1"] = REPORT_PROGRESS_PROTOCOL_VERSION
    task_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    emitted_at: datetime


class ReportStreamReadyFrame(ReportProgressFrameBase):
    """报告 SSE 建立后发送的数据库与进程内安全快照。"""

    type: Literal["stream_ready"] = "stream_ready"
    status: ReportTaskStatus
    progress: int = Field(ge=0, le=100)
    stages: list[ReportStageFrameState] = Field(default_factory=list)


class ReportStageUpdateFrame(ReportProgressFrameBase):
    """真实报告执行边界产生的单阶段变化。"""

    type: Literal["stage_update"] = "stage_update"
    stage: ReportStage
    stage_status: ReportStageStatus
    progress: int = Field(ge=0, le=100)


class ReportTaskTerminalFrame(ReportProgressFrameBase):
    """数据库终态提交后发送的唯一任务终态。"""

    type: Literal["task_terminal"] = "task_terminal"
    status: ReportTaskStatus
    progress: int = Field(ge=0, le=100)
    error_code: Optional[str] = None
    message: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_terminal_status(cls, value: ReportTaskStatus) -> ReportTaskStatus:
        """拒绝把 pending/running 伪装成任务终态。"""
        if value not in {ReportTaskStatus.COMPLETED, ReportTaskStatus.FAILED}:
            raise ValueError("task_terminal 只接受 completed 或 failed")
        return value


ReportProgressFrame = Annotated[
    ReportStreamReadyFrame | ReportStageUpdateFrame | ReportTaskTerminalFrame,
    Field(discriminator="type"),
]


class ReportDetail(BaseModel):
    report_id: str
    task_id: str
    stock_code: Optional[str] = None
    company_name: Optional[str] = None
    content: Optional[str] = None
    status: str
    progress: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportListItem(BaseModel):
    report_id: str
    stock_code: Optional[str] = None
    company_name: Optional[str] = None
    status: str
    progress: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportDeleteResponse(BaseModel):
    message: str = "已删除"
