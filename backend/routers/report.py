"""调研报告 REST 与 SSE 协议适配路由。"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.report_progress.contracts import (
    REPORT_PROGRESS_PROTOCOL_VERSION,
    ReportProgressNotification,
    ReportTaskStatus,
    ReportTerminalNotification,
)
from backend.application.report_progress.hub import report_progress_hub
from backend.application.report_progress.snapshot import (
    ReportProgressSnapshot,
    project_report_snapshot,
)
from backend.config import settings
from backend.db.database import AsyncSessionFactory, get_db
from backend.db.models import Report, User
from backend.middleware.auth import AuthContext, ensure_user_access, require_auth
from backend.schemas.report import (
    ReportDeleteResponse,
    ReportDetail,
    ReportGenerateRequest,
    ReportListItem,
    ReportStageFrameState,
    ReportStageUpdateFrame,
    ReportStatusResponse,
    ReportStreamReadyFrame,
    ReportTaskResponse,
    ReportTaskTerminalFrame,
)
from backend.services.agent_service import run_report_task

router = APIRouter()
logger = logging.getLogger(__name__)

_REPORT_RECONCILE_SECONDS = 15.0


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
    snapshot = project_report_snapshot(
        task_id=report.task_id,
        report_id=report.id,
        user_id=report.user_id,
        status=report.status,
        progress=report.progress,
    )
    return ReportStatusResponse(
        task_id=snapshot.task_id,
        status=snapshot.status.value,
        progress=snapshot.progress,
        report_id=snapshot.report_id if snapshot.status is ReportTaskStatus.COMPLETED else None,
        error_msg=snapshot.message,
        error_code=snapshot.error_code,
    )


async def _load_sse_snapshot(
    db: AsyncSession,
    *,
    task_id: str,
    auth: AuthContext,
) -> ReportProgressSnapshot:
    """加载 SSE 首帧并在响应提交前隐藏任务存在性。

    Args:
        db: 生命周期仅覆盖 path operation 的短数据库会话。
        task_id: 客户端请求观察的任务标识。
        auth: 已验证的 Bearer 身份。

    Returns:
        不含正文和原始异常的数据库权威快照。

    Raises:
        HTTPException: 任务不存在或不属于当前用户时统一返回 404。
    """
    result = await db.execute(select(Report).where(Report.task_id == task_id))
    report = result.scalar_one_or_none()
    if report is None or (settings.auth_enabled and report.user_id != auth.user_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return project_report_snapshot(
        task_id=report.task_id,
        report_id=report.id,
        user_id=report.user_id,
        status=report.status,
        progress=report.progress,
    )


async def _require_sse_snapshot(
    task_id: str,
    db: AsyncSession = Depends(get_db, scope="function"),
    auth: AuthContext = Depends(require_auth),
) -> ReportProgressSnapshot:
    """作为普通依赖在 SSE producer 启动前完成访问校验。

    Args:
        task_id: URL 中的报告任务标识。
        db: 仅覆盖依赖解析阶段的短数据库会话。
        auth: 已验证的 Bearer 身份。

    Returns:
        已完成所有权检查的安全数据库快照。

    Raises:
        HTTPException: 未认证返回 401；不存在或非所有者统一返回 404。
    """
    return await _load_sse_snapshot(db, task_id=task_id, auth=auth)


async def _reload_sse_snapshot(task_id: str) -> ReportProgressSnapshot | None:
    """使用独立短会话重新读取长连接期间的数据库权威状态。"""
    async with AsyncSessionFactory() as db:
        result = await db.execute(select(Report).where(Report.task_id == task_id))
        report = result.scalar_one_or_none()
        if report is None:
            return None
        return project_report_snapshot(
            task_id=report.task_id,
            report_id=report.id,
            user_id=report.user_id,
            status=report.status,
            progress=report.progress,
        )


def _ready_frame(
    snapshot: ReportProgressSnapshot,
    *,
    sequence: int,
) -> ReportStreamReadyFrame:
    """把数据库快照和当前进程阶段状态投影为首帧。"""
    return ReportStreamReadyFrame(
        protocol_version=REPORT_PROGRESS_PROTOCOL_VERSION,
        task_id=snapshot.task_id,
        report_id=snapshot.report_id,
        sequence=sequence,
        emitted_at=datetime.now(UTC),
        status=snapshot.status,
        progress=snapshot.progress,
        stages=[
            ReportStageFrameState(stage=item.stage, status=item.stage_status)
            for item in report_progress_hub.stage_snapshots(snapshot.task_id)
        ],
    )


def _stage_frame(
    notification: ReportProgressNotification,
    *,
    sequence: int,
    progress_floor: int,
) -> ReportStageUpdateFrame:
    """把内部阶段事实映射为无私有字段的公共帧。"""
    return ReportStageUpdateFrame(
        protocol_version=REPORT_PROGRESS_PROTOCOL_VERSION,
        task_id=notification.task_id,
        report_id=notification.report_id,
        sequence=sequence,
        emitted_at=datetime.now(UTC),
        stage=notification.stage,
        stage_status=notification.stage_status,
        progress=max(progress_floor, notification.progress),
    )


def _terminal_frame(
    terminal: ReportProgressSnapshot | ReportTerminalNotification,
    *,
    sequence: int,
) -> ReportTaskTerminalFrame:
    """把数据库快照或已提交终态通知映射为唯一公共终态。"""
    return ReportTaskTerminalFrame(
        protocol_version=REPORT_PROGRESS_PROTOCOL_VERSION,
        task_id=terminal.task_id,
        report_id=terminal.report_id,
        sequence=sequence,
        emitted_at=datetime.now(UTC),
        status=terminal.status,
        progress=terminal.progress,
        error_code=terminal.error_code,
        message=terminal.message,
    )


def _sse_event(
    frame: ReportStreamReadyFrame | ReportStageUpdateFrame | ReportTaskTerminalFrame,
) -> ServerSentEvent:
    """交由 FastAPI 原生实现编码标准 SSE event/id/data。"""
    return ServerSentEvent(data=frame, event=frame.type, id=str(frame.sequence))


async def _report_event_stream(
    initial: ReportProgressSnapshot,
) -> AsyncIterator[ServerSentEvent]:
    """发送数据库首帧、进程内低延迟事件和周期权威终态检查。"""
    sequence = 1
    last_progress = initial.progress
    last_status = initial.status
    started_at = time.perf_counter()
    logger.info(
        "report_progress_stream_open stage=%s task_id=%s report_id=%s status=%s transport=%s",
        "report_progress",
        initial.task_id,
        initial.report_id,
        "STARTED",
        "sse",
    )
    try:
        # 先注册再发数据库快照，避免任务在首帧期间完成而无人接收终态通知。
        async with report_progress_hub.subscribe(initial.task_id) as subscription:
            yield _sse_event(_ready_frame(initial, sequence=sequence))
            if initial.is_terminal:
                sequence += 1
                yield _sse_event(_terminal_frame(initial, sequence=sequence))
                return

            # 首次查询与 Hub 注册之间可能已经提交终态；订阅后立即核对一次，
            # 避免等到周期 reconcile 才把这一竞态收敛给客户端。
            try:
                latest = await _reload_sse_snapshot(initial.task_id)
            except Exception as exc:
                logger.warning(
                    "report_progress_initial_reconcile_failed stage=%s task_id=%s "
                    "status=%s transport=%s error_code=%s error_type=%s",
                    "report_progress",
                    initial.task_id,
                    "DEGRADED",
                    "database",
                    "REPORT_SNAPSHOT_UNAVAILABLE",
                    type(exc).__name__,
                )
            else:
                if latest is None:
                    return
                last_progress = max(last_progress, latest.progress)
                last_status = latest.status
                if latest.is_terminal:
                    sequence += 1
                    terminal = ReportProgressSnapshot(
                        task_id=latest.task_id,
                        report_id=latest.report_id,
                        user_id=latest.user_id,
                        status=latest.status,
                        progress=last_progress,
                        error_code=latest.error_code,
                        message=latest.message,
                    )
                    yield _sse_event(_terminal_frame(terminal, sequence=sequence))
                    return

            while True:
                try:
                    message = await asyncio.wait_for(
                        subscription.receive(),
                        timeout=_REPORT_RECONCILE_SECONDS,
                    )
                except TimeoutError:
                    # Hub 可丢且不跨进程；idle 时只用短会话核对数据库终态。
                    try:
                        latest = await _reload_sse_snapshot(initial.task_id)
                    except Exception as exc:
                        logger.warning(
                            "report_progress_reconcile_failed stage=%s task_id=%s "
                            "status=%s transport=%s error_code=%s error_type=%s",
                            "report_progress",
                            initial.task_id,
                            "FAILED",
                            "database",
                            "REPORT_SNAPSHOT_UNAVAILABLE",
                            type(exc).__name__,
                        )
                        return
                    if latest is None:
                        return
                    last_progress = max(last_progress, latest.progress)
                    last_status = latest.status
                    if latest.is_terminal:
                        sequence += 1
                        terminal = ReportProgressSnapshot(
                            task_id=latest.task_id,
                            report_id=latest.report_id,
                            user_id=latest.user_id,
                            status=latest.status,
                            progress=last_progress,
                            error_code=latest.error_code,
                            message=latest.message,
                        )
                        yield _sse_event(_terminal_frame(terminal, sequence=sequence))
                        return
                    continue

                if message.task_id != initial.task_id or message.report_id != initial.report_id:
                    continue
                sequence += 1
                if isinstance(message, ReportProgressNotification):
                    frame = _stage_frame(
                        message,
                        sequence=sequence,
                        progress_floor=last_progress,
                    )
                    last_progress = frame.progress
                    yield _sse_event(frame)
                    continue

                last_progress = max(last_progress, message.progress)
                last_status = message.status
                terminal = ReportTerminalNotification(
                    task_id=message.task_id,
                    report_id=message.report_id,
                    status=last_status,
                    progress=last_progress,
                    error_code=message.error_code,
                    message=message.message,
                )
                yield _sse_event(_terminal_frame(terminal, sequence=sequence))
                return
    finally:
        logger.info(
            "report_progress_stream_close stage=%s task_id=%s report_id=%s status=%s "
            "transport=%s elapsed_ms=%.2f",
            "report_progress",
            initial.task_id,
            initial.report_id,
            last_status.value,
            "sse",
            (time.perf_counter() - started_at) * 1000,
        )


@router.get(
    "/events/{task_id}",
    response_class=EventSourceResponse,
    summary="订阅报告生成进度",
)
async def stream_report_progress(
    snapshot: ReportProgressSnapshot = Depends(_require_sse_snapshot),
) -> AsyncIterator[ServerSentEvent]:
    """在鉴权与所有权校验后返回 `report-progress-v1` SSE。

    Args:
        snapshot: 由普通依赖在 producer 启动前完成鉴权和所有权校验的快照。

    Yields:
        FastAPI 原生 SSE 事件；框架负责 15 秒 comment ping、断连取消、
        ``no-cache`` 和 ``X-Accel-Buffering: no``。

    Raises:
        HTTPException: 未认证返回 401；不存在或非所有者统一返回 404。
    """
    async for event in _report_event_stream(snapshot):
        yield event


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
