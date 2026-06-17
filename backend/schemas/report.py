"""报告相关 Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
    current_stage: Optional[str] = None
    current_stage_label: Optional[str] = None
    updated_at: Optional[str] = None


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
