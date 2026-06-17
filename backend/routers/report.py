"""调研报告路由"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Report, User
from backend.integrations.redis.runtime import get_cache_service
from backend.middleware.auth import AuthContext, _build_auth_context, ensure_user_access, require_auth
from backend.schemas.report import (
    ReportDeleteResponse,
    ReportDetail,
    ReportGenerateRequest,
    ReportListItem,
    ReportStatusResponse,
    ReportTaskResponse,
)
from backend.services.auth_service import AuthError
from backend.services.agent_service import run_report_task
from backend.services.report.idempotency import (
    acquire_idempotency_slot,
    build_report_idempotency_key,
    finalize_idempotency_slot,
    read_idempotency_result,
    release_idempotency_slot,
)
from backend.services.report.sse_manager import subscribe, unsubscribe

router = APIRouter()
logger = logging.getLogger(__name__)


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

    cache_service = get_cache_service()
    idempotency_key = build_report_idempotency_key(
        cache_service,
        effective_user_id,
        body.command,
    )
    acquired_slot, idempotency_meta = await acquire_idempotency_slot(
        cache_service,
        idempotency_key,
    )
    idempotency_degraded = bool(idempotency_meta.get("fallback"))

    if idempotency_key and not acquired_slot and not idempotency_degraded:
        existing = await read_idempotency_result(cache_service, idempotency_key)
        if existing:
            return ReportTaskResponse(
                task_id=existing["task_id"],
                report_id=existing["report_id"],
                status=existing["status"],
            )
        logger.warning("报告幂等命中但读取已有任务超时，降级创建新任务")

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
    try:
        await db.commit()
    except Exception:
        if acquired_slot:
            await release_idempotency_slot(cache_service, idempotency_key)
        raise

    if acquired_slot:
        await finalize_idempotency_slot(
            cache_service,
            idempotency_key,
            task_id=task_id,
            report_id=report_id,
            status="pending",
        )

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
    cache_service = get_cache_service()
    if cache_service is not None:
        key = cache_service.key_builder.report_status(task_id)
        envelope, _meta = await cache_service.get(key)
        data = envelope.data if envelope else None
        if isinstance(data, dict) and data.get("user_id"):
            ensure_user_access(data.get("user_id"), auth)
            return ReportStatusResponse(
                task_id=data["task_id"],
                status=data["status"],
                progress=data["progress"],
                report_id=data.get("report_id") if data.get("status") == "completed" else None,
                error_msg=data.get("error_msg"),
                current_stage=data.get("current_stage"),
                current_stage_label=data.get("current_stage_label"),
                updated_at=data.get("updated_at"),
            )

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
        current_stage=None,
        current_stage_label=None,
    )


def _status_payload_from_report(report: Report) -> dict:
    return {
        "task_id": report.task_id,
        "report_id": report.id,
        "user_id": report.user_id,
        "status": report.status,
        "progress": report.progress,
        "error_msg": report.error_msg,
        "current_stage": None,
        "current_stage_label": None,
        "updated_at": datetime.utcnow().isoformat(),
    }


async def _current_status_payload(task_id: str, report: Report) -> dict:
    cache_service = get_cache_service()
    if cache_service is not None:
        envelope, _meta = await cache_service.get(cache_service.key_builder.report_status(task_id))
        data = envelope.data if envelope else None
        if isinstance(data, dict) and data.get("user_id"):
            return data
    return _status_payload_from_report(report)


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_event_generator(task_id: str, request: Request, initial_payload: dict):
    queue = await subscribe(task_id)
    if queue is None:
        yield _format_sse("error", {"message": "连接数已满，请稍后重试"})
        return

    try:
        yield _format_sse("status", initial_payload)
        if initial_payload.get("status") in {"completed", "failed"}:
            event = "completed" if initial_payload.get("status") == "completed" else "failed"
            yield _format_sse(event, initial_payload)
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event_data = await asyncio.wait_for(queue.get(), timeout=15)
                yield _format_sse(event_data["event"], event_data["data"])
                if event_data["data"].get("status") in {"completed", "failed"}:
                    break
            except asyncio.TimeoutError:
                yield _format_sse("heartbeat", {"ts": datetime.utcnow().isoformat()})
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("SSE 生成器异常 task=%s", task_id, exc_info=True)
    finally:
        await unsubscribe(task_id, queue)


@router.get("/events/{task_id}", summary="SSE 任务进度推送")
async def report_events(
    task_id: str,
    request: Request,
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if settings.auth_enabled:
        if not token:
            raise HTTPException(status_code=401, detail="未登录：缺少 token")
        try:
            auth = _build_auth_context(token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="未登录或 Token 无效") from exc
    else:
        auth = AuthContext(account_id="auth-disabled", username="auth-disabled", user_id="")

    result = await db.execute(select(Report).where(Report.task_id == task_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    ensure_user_access(report.user_id, auth)
    initial_payload = await _current_status_payload(task_id, report)

    return StreamingResponse(
        _sse_event_generator(task_id, request, initial_payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
