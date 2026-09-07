"""调研报告 REST 与 SSE 协议适配路由。"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.report_progress.contracts import (
    REPORT_PROGRESS_PROTOCOL_VERSION,
    ReportProgressNotification,
    ReportProgressMessage,
    ReportStageSnapshot,
    ReportTaskStatus,
    ReportTerminalNotification,
)
from backend.application.report_progress.hub import report_progress_hub
from backend.application.report_progress.snapshot import (
    ReportProgressSnapshot,
    project_report_snapshot,
)
from backend.application.report_tasks.contracts import (
    ReportIdempotencyConflictError,
    ReportIdempotencyValidationError,
    ReportTaskSnapshotRecord,
)
from backend.application.report_tasks.service import ReportTaskCreationService
from backend.config import settings
from backend.db.database import AsyncSessionFactory, get_db
from backend.db.models import Report, User
from backend.middleware.auth import AuthContext, ensure_user_access, require_auth
from backend.infrastructure.report_tasks.redis_store import ReportTaskVersionNotification
from backend.infrastructure.report_tasks.repository import (
    SqlAlchemyReportTaskClaimRepository,
    SqlAlchemyReportTaskSnapshotRepository,
)
from backend.infrastructure.report_tasks.runtime import get_report_task_runtime
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
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    """原子创建或复用报告任务，并仅由数据库获胜请求注册后台执行。

    Args:
        body: 已校验的报告命令与请求用户。
        background_tasks: FastAPI 当前响应完成后执行的进程内任务容器。
        idempotency_key: 可选显式请求键；缺省时使用规范化命令哈希。
        db: 当前请求的异步数据库会话。
        auth: 已验证的请求身份。

    Returns:
        保持旧字段兼容并附带幂等结果、期限的任务响应。

    Raises:
        HTTPException: 用户越权、显式键非法或同键绑定不同请求时抛出。
    """
    effective_user_id = ensure_user_access(body.user_id, auth)
    await _ensure_user(db, effective_user_id)

    if settings.enable_report_task_governance:
        service = ReportTaskCreationService(
            SqlAlchemyReportTaskClaimRepository(db),
            digest_secret=settings.jwt_secret_key,
            ttl_seconds=settings.report_idempotency_ttl_sec,
        )
        try:
            result = await service.create_or_reuse(
                user_id=effective_user_id,
                command=body.command,
                client_key=idempotency_key,
            )
        except ReportIdempotencyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error_code": exc.error_code, "message": str(exc)},
            ) from None
        except ReportIdempotencyConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error_code": exc.error_code, "message": str(exc)},
            ) from None

        if result.should_dispatch:
            background_tasks.add_task(
                run_report_task,
                task_id=result.task_id,
                report_id=result.report_id,
                command=body.command,
                user_id=effective_user_id,
            )
        logger.info(
            "report_task_claim stage=CREATE status=%s task_id=%s report_id=%s generation=%d",
            result.idempotency_status.value,
            result.task_id,
            result.report_id,
            result.generation,
        )
        return ReportTaskResponse(
            task_id=result.task_id,
            report_id=result.report_id,
            status=result.status.value,
            idempotency_status=result.idempotency_status,
            expires_at=result.expires_at,
        )

    # 紧急回滚开关保留既有单请求创建语义；默认路径始终使用数据库治理。
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
    record = await SqlAlchemyReportTaskSnapshotRepository(db).load_latest(task_id)
    if record is not None:
        return _project_persisted_snapshot(record)
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
    """使用独立短会话读取治理快照，并 best-effort 重建 Redis 镜像。"""
    async with AsyncSessionFactory() as db:
        record = await SqlAlchemyReportTaskSnapshotRepository(db).load_latest(task_id)
        if record is not None:
            runtime = get_report_task_runtime()
            if runtime is not None:
                runtime.mark_reconcile()
                await runtime.store_record(record)
            return _project_persisted_snapshot(record)
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


def _project_persisted_snapshot(record: ReportTaskSnapshotRecord) -> ReportProgressSnapshot:
    """把治理层 Pydantic 快照转换为 SSE 使用的内部只读投影。"""
    snapshot = record.snapshot
    return ReportProgressSnapshot(
        task_id=snapshot.task_id,
        report_id=snapshot.report_id,
        user_id=record.user_id,
        status=snapshot.status,
        progress=snapshot.progress,
        error_code=snapshot.error_code,
        message=snapshot.message,
        snapshot_version=snapshot.snapshot_version,
        stages=tuple(
            ReportStageSnapshot(stage=item.stage, stage_status=item.status)
            for item in snapshot.stages
        ),
    )


def _ready_frame(
    snapshot: ReportProgressSnapshot,
    *,
    sequence: int,
) -> ReportStreamReadyFrame:
    """把持久化阶段快照投影为首帧，历史任务才回退进程内状态。"""
    stages = snapshot.stages or report_progress_hub.stage_snapshots(snapshot.task_id)
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
            for item in stages
        ],
    )


class _ReportUpdateSubscription:
    """合并进程内通知与 Redis 版本唤醒，并确保等待任务可取消。"""

    def __init__(self, local: object, remote: object | None) -> None:
        self._local = local
        self._remote = remote

    async def receive(self) -> ReportProgressMessage | ReportTaskVersionNotification:
        """返回任一观察通道最先到达的消息，并取消另一等待。"""
        local_receive = getattr(self._local, "receive")
        local_task = asyncio.create_task(local_receive())
        tasks = {local_task}
        remote_task: asyncio.Task[object] | None = None
        if self._remote is not None:
            remote_receive = getattr(self._remote, "receive")
            remote_task = asyncio.create_task(remote_receive())
            tasks.add(remote_task)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # 同时到达时优先消费已提交的本地完整事件；仍读取另一 task 的结果，
            # 避免遗留未观察异常。Redis 摘要只负责后续数据库对账。
            selected = local_task if local_task in done else remote_task
            for task in done:
                if task is not selected:
                    task.result()
            if selected is None:  # pragma: no cover - 构造时始终存在 local task
                raise RuntimeError("报告观察订阅没有可用任务")
            return selected.result()  # type: ignore[return-value]
        finally:
            # ``wait_for`` 可在 FIRST_COMPLETED 前取消本协程；始终清理全部未完成
            # 子任务并观察结果，避免 SSE 周期对账遗留 pending receive。
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def _subscribe_report_updates(
    task_id: str,
) -> AsyncIterator[_ReportUpdateSubscription]:
    """先注册本地和可选 Redis 观察通道，再允许调用方读取最新快照。"""
    async with report_progress_hub.subscribe(task_id) as local:
        runtime = get_report_task_runtime()
        if runtime is None:
            yield _ReportUpdateSubscription(local, None)
            return
        async with runtime.subscribe(task_id) as remote:
            yield _ReportUpdateSubscription(local, remote)


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


def _apply_stage_notification(
    snapshot: ReportProgressSnapshot,
    notification: ReportProgressNotification,
    *,
    snapshot_version: int,
) -> ReportProgressSnapshot:
    """把已提交的本地阶段通知合并到当前连接快照，用于跨通道去重。"""
    stages = {item.stage: item for item in snapshot.stages}
    stages[notification.stage] = ReportStageSnapshot(
        stage=notification.stage,
        stage_status=notification.stage_status,
    )
    return replace(
        snapshot,
        status=ReportTaskStatus.RUNNING,
        progress=max(snapshot.progress, notification.progress),
        snapshot_version=max(snapshot.snapshot_version, snapshot_version),
        stages=tuple(stages[stage] for stage in stages),
    )


def _latest_changed_stage(
    previous: ReportProgressSnapshot,
    latest: ReportProgressSnapshot,
) -> ReportProgressNotification | None:
    """从两个持久快照中提取最后一次单阶段变化。"""
    previous_status = {item.stage: item.stage_status for item in previous.stages}
    changed = [
        item
        for item in latest.stages
        if previous_status.get(item.stage) is not item.stage_status
    ]
    if not changed:
        return None
    item = changed[-1]
    return ReportProgressNotification(
        task_id=latest.task_id,
        report_id=latest.report_id,
        stage=item.stage,
        stage_status=item.stage_status,
        progress=latest.progress,
        snapshot_version=latest.snapshot_version,
    )


async def _report_event_stream(
    initial: ReportProgressSnapshot,
) -> AsyncIterator[ServerSentEvent]:
    """订阅后读取最新快照，再合并本地/Redis 唤醒与周期数据库对账。"""
    sequence = initial.snapshot_version
    current = initial
    last_progress = current.progress
    last_status = current.status
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
        # 鉴权阶段已读取持久快照；先注册观察通道再发首帧，随后立即复查数据库，
        # 既保留 D05 的首帧语义，又关闭鉴权快照到订阅之间的竞态。
        async with _subscribe_report_updates(initial.task_id) as subscription:
            yield _sse_event(_ready_frame(current, sequence=sequence))
            if current.is_terminal:
                sequence += 1
                yield _sse_event(_terminal_frame(current, sequence=sequence))
                return

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
                if (
                    latest.snapshot_version > current.snapshot_version
                    or latest.status is not current.status
                    or latest.progress > current.progress
                ):
                    previous = current
                    current = latest
                    last_progress = max(last_progress, current.progress)
                    last_status = current.status
                    sequence = max(sequence + 1, current.snapshot_version)
                    if current.is_terminal:
                        yield _sse_event(_terminal_frame(current, sequence=sequence))
                        return
                    changed_stage = _latest_changed_stage(previous, current)
                    if changed_stage is not None:
                        yield _sse_event(
                            _stage_frame(
                                changed_stage,
                                sequence=sequence,
                                progress_floor=last_progress,
                            )
                        )

            while True:
                latest = None
                try:
                    message = await asyncio.wait_for(
                        subscription.receive(),
                        timeout=settings.report_task_reconcile_sec,
                    )
                except TimeoutError:
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
                else:
                    if isinstance(message, ReportTaskVersionNotification):
                        if message.task_id != initial.task_id:
                            continue
                        if message.snapshot_version <= current.snapshot_version:
                            continue
                        try:
                            latest = await _reload_sse_snapshot(initial.task_id)
                        except Exception as exc:
                            logger.warning(
                                "report_progress_notification_reconcile_failed stage=%s "
                                "task_id=%s status=%s transport=%s error_code=%s error_type=%s",
                                "report_progress",
                                initial.task_id,
                                "DEGRADED",
                                "redis_pubsub",
                                "REPORT_SNAPSHOT_UNAVAILABLE",
                                type(exc).__name__,
                            )
                            continue
                        if latest is None:
                            return
                    else:
                        if (
                            message.task_id != initial.task_id
                            or message.report_id != initial.report_id
                        ):
                            continue
                        message_version = message.snapshot_version
                        if (
                            message_version is not None
                            and message_version <= current.snapshot_version
                        ):
                            continue
                        sequence = message_version or sequence + 1
                        last_progress = max(last_progress, message.progress)
                        if isinstance(message, ReportProgressNotification):
                            current = _apply_stage_notification(
                                current,
                                message,
                                snapshot_version=message_version or current.snapshot_version,
                            )
                            frame = _stage_frame(
                                message,
                                sequence=sequence,
                                progress_floor=last_progress,
                            )
                            yield _sse_event(frame)
                            continue

                        last_status = message.status
                        yield _sse_event(
                            _terminal_frame(message, sequence=sequence)
                        )
                        return

                if latest is None:
                    continue
                if (
                    latest.snapshot_version <= current.snapshot_version
                    and latest.status is current.status
                    and latest.progress <= current.progress
                ):
                    continue
                previous = current
                current = latest
                last_progress = max(last_progress, current.progress)
                last_status = current.status
                sequence = max(sequence + 1, current.snapshot_version)
                if current.is_terminal:
                    yield _sse_event(_terminal_frame(current, sequence=sequence))
                    return
                changed_stage = _latest_changed_stage(previous, current)
                if changed_stage is not None:
                    frame = _stage_frame(
                        changed_stage,
                        sequence=sequence,
                        progress_floor=last_progress,
                    )
                    yield _sse_event(frame)
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
