"""调研报告路由"""

import uuid
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Report, User
from backend.middleware.auth import AuthContext, ensure_user_access, require_auth
from backend.schemas.report import (
    ReportDeleteResponse,
    ReportDetail,
    ReportGenerateRequest,
    ReportListItem,
    ReportStatusResponse,
    ReportTaskResponse,
)
from backend.services.agent_service import run_report_task

router = APIRouter()


def _build_content_disposition(filename: str) -> str:
    """构造兼容中文文件名且可安全写入 HTTP 响应头的下载声明。

    Args:
        filename: 期望展示给用户的 UTF-8 文件名。

    Returns:
        同时包含 ASCII 回退名和 RFC 5987 UTF-8 文件名的响应头值。
    """
    normalized = filename.replace("\r", "").replace("\n", "")
    ascii_fallback = "".join(
        character if character.isascii() and (character.isalnum() or character in "._-") else "_"
        for character in normalized
    ).strip("_")
    if not ascii_fallback:
        ascii_fallback = "report.md"
    encoded_filename = quote(normalized, safe="")
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{encoded_filename}"
    )


async def _ensure_user(db: AsyncSession, user_id: str) -> User:
    """确保用户存在（不存在则自动创建）。"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=user_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


# ─────────────────────────────────────────────────────────────
# POST /api/report/generate
# ─────────────────────────────────────────────────────────────
@router.post("/generate", response_model=ReportTaskResponse, summary="触发报告生成")
async def generate_report(
    body: ReportGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    """
    异步触发完整多 Agent 工作流：
    1. 先插入 reports 行（status=pending）
    2. 启动后台任务
    3. 立即返回 task_id（前端轮询 /status/{task_id}）
    """
    effective_user_id = ensure_user_access(body.user_id, auth)
    await _ensure_user(db, effective_user_id)

    task_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    report = Report(
        id=report_id,
        task_id=task_id,
        user_id=effective_user_id,
        status="pending",
        progress=0,
    )
    db.add(report)
    await db.commit()

    background_tasks.add_task(
        run_report_task,
        task_id=task_id,
        report_id=report_id,
        command=body.command,
        user_id=effective_user_id,
    )

    return ReportTaskResponse(task_id=task_id, report_id=report_id, status="pending")


# ─────────────────────────────────────────────────────────────
# GET /api/report/status/{task_id}
# ─────────────────────────────────────────────────────────────
@router.get("/status/{task_id}", response_model=ReportStatusResponse, summary="查询任务进度")
async def get_report_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    result = await db.execute(select(Report).where(Report.task_id == task_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    ensure_user_access(report.user_id, auth)
    return ReportStatusResponse(
        task_id=report.task_id,
        status=report.status,
        progress=report.progress,
        report_id=report.id if report.status == "completed" else None,
        error_msg=report.error_msg,
    )


# ─────────────────────────────────────────────────────────────
# GET /api/report/history
# ─────────────────────────────────────────────────────────────
@router.get("/history", response_model=list[ReportListItem], summary="历史报告列表")
async def list_reports(
    user_id: str,
    q: Optional[str] = Query(None, description="搜索关键词（公司名/代码）"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    effective_user_id = ensure_user_access(user_id, auth)
    stmt = (
        select(Report)
        .where(Report.user_id == effective_user_id)
        .order_by(Report.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    reports = result.scalars().all()

    if q:
        q_lower = q.lower()
        reports = [
            r for r in reports
            if (r.company_name and q_lower in r.company_name.lower())
            or (r.stock_code and q_lower in r.stock_code.lower())
        ]

    return [
        ReportListItem(
            report_id=r.id,
            stock_code=r.stock_code,
            company_name=r.company_name,
            status=r.status,
            progress=r.progress,
            created_at=r.created_at,
        )
        for r in reports
    ]


# ─────────────────────────────────────────────────────────────
# GET /api/report/{report_id}
# ─────────────────────────────────────────────────────────────
@router.get("/{report_id}", response_model=ReportDetail, summary="获取报告全文")
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    ensure_user_access(report.user_id, auth)
    return ReportDetail(
        report_id=report.id,
        task_id=report.task_id,
        stock_code=report.stock_code,
        company_name=report.company_name,
        content=report.content,
        status=report.status,
        progress=report.progress,
        created_at=report.created_at,
    )


# ─────────────────────────────────────────────────────────────
# GET /api/report/{report_id}/download
# ─────────────────────────────────────────────────────────────
@router.get("/{report_id}/download", summary="下载报告 .md 文件")
async def download_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None or not report.content:
        raise HTTPException(status_code=404, detail="报告不存在或尚未生成")
    ensure_user_access(report.user_id, auth)
    company = report.company_name or report.stock_code or "report"
    date_str = report.created_at.strftime("%Y%m%d")
    filename = f"{company}_{date_str}.md"
    return Response(
        content=report.content.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": _build_content_disposition(filename)},
    )


# ─────────────────────────────────────────────────────────────
# DELETE /api/report/{report_id}
# ─────────────────────────────────────────────────────────────
@router.delete("/{report_id}", response_model=ReportDeleteResponse, summary="删除报告")
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    ensure_user_access(report.user_id, auth)
    await db.delete(report)
    await db.commit()
    return ReportDeleteResponse()
