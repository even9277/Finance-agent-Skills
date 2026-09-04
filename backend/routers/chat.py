"""对话 HTTP/WebSocket 协议适配层。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing, suppress
from dataclasses import asdict, dataclass
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.chat.contracts import (
    ChatCommand,
    ChatContentDelta,
    ChatContextWindowData,
    ChatPlanPreview,
    ChatStepStatus,
    ChatStreamCompleted,
    ChatStreamEvent,
    ChatStreamFailed,
    ChatStreamStarted,
    ChatToolStatus,
    ChatTraceSummary,
    ChatVerificationSummary,
)
from backend.application.chat.factory import build_chat_session_use_case, build_chat_use_case
from backend.db.database import AsyncSessionFactory, get_db
from backend.middleware.auth import (
    AuthContext,
    authenticate_websocket,
    ensure_user_access,
    require_auth,
    require_query_user,
)
from backend.schemas.chat import (
    CHAT_STREAM_PROTOCOL_VERSION,
    ChatContentDeltaFrame,
    ChatContextWindow,
    ChatContextUpdateFrame,
    ChatMessage,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatMemoryCommandFrame,
    MemoryCommandResultResponse,
    ChatPlanPreviewFrame,
    ChatPlanStepPreviewFrame,
    ChatSkillConfirmationFrame,
    SkillConfirmationCandidateResponse,
    SkillConfirmationResponse,
    ChatStreamEndFrame,
    ChatStreamEnvelope,
    ChatStreamErrorFrame,
    ChatStreamStartFrame,
    ChatStepStatusFrame,
    ChatToolStatusFrame,
    ChatTraceSummaryFrame,
    ChatVerificationSummaryFrame,
    ChatSessionListItem,
    ChatSessionMessages,
    ChatSessionRenameRequest,
    ChatSessionSummaries,
    ChatSummaryItem,
    ChatTemplateItem,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_CHAT_INTERNAL_ERROR = "CHAT_INTERNAL_ERROR"
_CHAT_INTERNAL_MESSAGE = "对话处理失败"
_CHAT_STREAM_INCOMPLETE = "CHAT_STREAM_INCOMPLETE"

_TEMPLATES = [
    ChatTemplateItem(id="t1", label="基本面分析", content="帮我分析 [股票名] 的基本面"),
    ChatTemplateItem(id="t2", label="投资风险", content="这只股票近期有什么投资风险"),
    ChatTemplateItem(id="t3", label="估值判断", content="[股票名] 当前估值贵吗？"),
    ChatTemplateItem(id="t4", label="完整报告", content="帮我做一份完整的投研报告"),
    ChatTemplateItem(id="t5", label="对比分析", content="对比分析 [A] 和 [B] 哪只更值得买"),
    ChatTemplateItem(id="t6", label="持仓建议", content="结合我的风险偏好给出持仓建议"),
]


@dataclass(slots=True)
class _WebSocketStreamState:
    """记录单连接的低敏协议状态和发送侧指标。"""

    request_id: str
    session_id: str
    started_at: float
    sequence: int = 0
    chunk_count: int = 0
    output_chars: int = 0
    first_delta_sent_at: float | None = None
    terminal_sent: bool = False

    def next_sequence(self) -> int:
        """返回连接内严格递增且从 1 开始的公开帧序号。"""
        self.sequence += 1
        return self.sequence

    @property
    def elapsed_ms(self) -> float:
        """返回从连接进入聊天处理到当前时刻的毫秒耗时。"""
        return (time.perf_counter() - self.started_at) * 1000

    @property
    def server_ttft_ms(self) -> float | None:
        """返回首个非空正文成功写入 WebSocket 的毫秒耗时。"""
        if self.first_delta_sent_at is None:
            return None
        return (self.first_delta_sent_at - self.started_at) * 1000


async def _send_public_frame(
    websocket: WebSocket,
    frame: ChatStreamEnvelope,
) -> None:
    """发送一个已经通过 Pydantic 合同验证的 v2 公开帧。

    Args:
        websocket: 当前已接受的客户端连接。
        frame: 包含协议版本、关联标识和严格序号的公开 Schema。

    Raises:
        WebSocketDisconnect: 客户端在发送期间断开。
        RuntimeError: ASGI 传输拒绝写入；调用方必须关闭应用事件流。
    """
    await websocket.send_json(frame.model_dump(mode="json", exclude_none=True))


async def _send_stream_error(
    websocket: WebSocket,
    state: _WebSocketStreamState,
    *,
    code: Literal[
        "CHAT_STREAM_FAILED",
        "CHAT_INVALID_JSON",
        "CHAT_INVALID_REQUEST",
        "CHAT_INTERNAL_ERROR",
        "CHAT_STREAM_INCOMPLETE",
    ],
    message: str,
) -> None:
    """发送唯一安全失败终态，不包含内部异常或正文。"""
    await _send_public_frame(
        websocket,
        ChatStreamErrorFrame(
            protocol_version=CHAT_STREAM_PROTOCOL_VERSION,
            request_id=state.request_id,
            session_id=state.session_id,
            sequence=state.next_sequence(),
            code=code,
            message=message,
            chunk_count=state.chunk_count,
        ),
    )
    state.terminal_sent = True


async def _present_chat_stream(
    websocket: WebSocket,
    event_stream: AsyncGenerator[ChatStreamEvent, None],
    state: _WebSocketStreamState,
) -> None:
    """把 Application 事件映射为单调有序的 WebSocket v2 生命周期。

    Args:
        websocket: 当前已接受的客户端连接。
        event_stream: 唯一聊天用例产生的带背压异步事件流。
        state: 当前连接的安全关联字段、序号和发送指标。

    Raises:
        WebSocketDisconnect: 发送中断开时原样传播，并由 ``aclosing`` 取消上游。
        RuntimeError: Application 违反终态或 chunk 数量合同时终止连接。
    """
    async with aclosing(event_stream):
        async for event in event_stream:
            state.request_id = event.request_id
            state.session_id = event.session_id

            if isinstance(event, ChatStreamStarted):
                await _send_public_frame(
                    websocket,
                    ChatStreamStartFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                    ),
                )
                continue

            if isinstance(event, ChatTraceSummary):
                await _send_public_frame(
                    websocket,
                    ChatTraceSummaryFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        stage=event.stage,
                        status=event.status,
                        elapsed_ms=event.elapsed_ms,
                        summary=event.summary,
                        error_code=event.error_code,
                    ),
                )
                continue

            if isinstance(event, ChatPlanPreview):
                await _send_public_frame(
                    websocket,
                    ChatPlanPreviewFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        plan_id=event.plan_id,
                        revision=event.revision,
                        validated=event.validated,
                        steps=[
                            ChatPlanStepPreviewFrame(
                                step_id=step.step_id,
                                title=step.title,
                                purpose=step.purpose,
                                required=step.required,
                                status=step.status.value,
                                depends_on=list(step.depends_on),
                                subject_summary=step.subject_summary,
                            )
                            for step in event.steps
                        ],
                        replan_reason=event.replan_reason,
                        replaced_step_ids=list(event.replaced_step_ids),
                    ),
                )
                continue

            if isinstance(event, ChatStepStatus):
                await _send_public_frame(
                    websocket,
                    ChatStepStatusFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        plan_id=event.plan_id,
                        revision=event.revision,
                        step_id=event.step_id,
                        status=event.status.value,
                        elapsed_ms=event.elapsed_ms,
                        error_code=event.error_code,
                    ),
                )
                continue

            if isinstance(event, ChatToolStatus):
                await _send_public_frame(
                    websocket,
                    ChatToolStatusFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        plan_id=event.plan_id,
                        revision=event.revision,
                        tool_call_id=event.tool_call_id,
                        step_id=event.step_id,
                        display_name=event.display_name,
                        status=event.status.value,
                        attempt=event.attempt,
                        elapsed_ms=event.elapsed_ms,
                        parameter_summary=list(event.parameter_summary),
                        result_summary=event.result_summary,
                        error_code=event.error_code,
                    ),
                )
                continue

            if isinstance(event, ChatVerificationSummary):
                await _send_public_frame(
                    websocket,
                    ChatVerificationSummaryFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        plan_id=event.plan_id,
                        revision=event.revision,
                        sufficiency=event.sufficiency.value,
                        claim_level=event.claim_level,
                        accepted_count=event.accepted_count,
                        rejected_count=event.rejected_count,
                        covered_dimensions=list(event.covered_dimensions),
                        missing_dimensions=list(event.missing_dimensions),
                        limitation=event.limitation,
                    ),
                )
                continue

            if isinstance(event, ChatContentDelta):
                await _send_public_frame(
                    websocket,
                    ChatContentDeltaFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        content=event.content,
                        chunk_index=event.chunk_index,
                    ),
                )
                state.chunk_count += 1
                state.output_chars += len(event.content)
                if state.first_delta_sent_at is None:
                    state.first_delta_sent_at = time.perf_counter()
                continue

            if isinstance(event, ChatStreamCompleted):
                if event.chunk_count != state.chunk_count:
                    raise RuntimeError("application and WebSocket chunk counts do not match")
                skill_confirmation = _skill_confirmation_schema(event.outcome.skill_confirmation)
                if skill_confirmation is not None:
                    await _send_public_frame(
                        websocket,
                        ChatSkillConfirmationFrame(
                            request_id=event.request_id,
                            session_id=event.session_id,
                            sequence=state.next_sequence(),
                            confirmation=skill_confirmation,
                        ),
                    )
                memory_command = _memory_command_schema(event.outcome.memory_command)
                if memory_command is not None:
                    await _send_public_frame(
                        websocket,
                        ChatMemoryCommandFrame(
                            request_id=event.request_id,
                            session_id=event.session_id,
                            sequence=state.next_sequence(),
                            memory_command=memory_command,
                        ),
                    )
                context = _context_schema(event.outcome.context_window)
                if context is not None:
                    await _send_public_frame(
                        websocket,
                        ChatContextUpdateFrame(
                            request_id=event.request_id,
                            session_id=event.session_id,
                            sequence=state.next_sequence(),
                            context_window=context,
                        ),
                    )
                await _send_public_frame(
                    websocket,
                    ChatStreamEndFrame(
                        request_id=event.request_id,
                        session_id=event.session_id,
                        sequence=state.next_sequence(),
                        status=event.outcome.status,
                        chunk_count=event.chunk_count,
                        content_sha256=event.content_sha256,
                    ),
                )
                state.terminal_sent = True
                logger.info(
                    "chat.websocket.stream_terminated request_id=%s session_id=%s stage=%s "
                    "status=%s chunk_count=%d output_chars=%d server_ttft_ms=%s "
                    "application_ttft_ms=%s elapsed_ms=%.2f error_code=%s",
                    state.request_id,
                    state.session_id,
                    "chat.websocket.send",
                    event.outcome.status.value,
                    state.chunk_count,
                    state.output_chars,
                    state.server_ttft_ms,
                    event.ttft_ms,
                    state.elapsed_ms,
                    event.outcome.error_code.value if event.outcome.error_code else None,
                )
                return

            if isinstance(event, ChatStreamFailed):
                await _send_stream_error(
                    websocket,
                    state,
                    code=event.error_code.value,
                    message=_CHAT_INTERNAL_MESSAGE,
                )
                logger.warning(
                    "chat.websocket.stream_terminated request_id=%s session_id=%s stage=%s "
                    "status=%s chunk_count=%d output_chars=%d server_ttft_ms=%s "
                    "application_ttft_ms=%s elapsed_ms=%.2f error_code=%s",
                    state.request_id,
                    state.session_id,
                    "chat.websocket.send",
                    "FAILED",
                    state.chunk_count,
                    state.output_chars,
                    state.server_ttft_ms,
                    event.ttft_ms,
                    state.elapsed_ms,
                    event.error_code,
                )
                return

            raise RuntimeError("unsupported application chat stream event")

        if not state.terminal_sent:
            await _send_stream_error(
                websocket,
                state,
                code=_CHAT_STREAM_INCOMPLETE,
                message=_CHAT_INTERNAL_MESSAGE,
            )


async def _wait_for_client_disconnect(websocket: WebSocket) -> None:
    """持续读取 ASGI 连接事件，直到浏览器明确断开。

    Args:
        websocket: 已完成首个业务请求读取的当前连接。

    Raises:
        WebSocketDisconnect: 收到 ``websocket.disconnect`` 时携带客户端关闭码。
        RuntimeError: Starlette 连接状态异常时原样传播，由公开入口安全收口。
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(code=int(message.get("code") or 1000))


async def _present_chat_stream_until_disconnect(
    websocket: WebSocket,
    event_stream: AsyncGenerator[ChatStreamEvent, None],
    state: _WebSocketStreamState,
) -> None:
    """竞争发送生命周期与主动断连监听，并确定性取消败方。

    Args:
        websocket: 当前已接受且已读取一轮请求的连接。
        event_stream: 唯一 Application 事件流。
        state: 当前连接的公开协议状态。

    Raises:
        WebSocketDisconnect: 客户端先断开时，在关闭上游事件流后传播。
        BaseException: Presenter 或连接监听异常在清理另一个任务后传播。
    """
    presenter_task = asyncio.create_task(_present_chat_stream(websocket, event_stream, state))
    disconnect_task = asyncio.create_task(_wait_for_client_disconnect(websocket))
    done, _ = await asyncio.wait(
        {presenter_task, disconnect_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if presenter_task in done:
        if not disconnect_task.done():
            disconnect_task.cancel()
        with suppress(asyncio.CancelledError, WebSocketDisconnect):
            await disconnect_task
        await presenter_task
        return

    presenter_task.cancel()
    with suppress(asyncio.CancelledError):
        await presenter_task
    await disconnect_task


def _context_schema(value: ChatContextWindowData | None) -> ChatContextWindow | None:
    """把 Application 上下文快照映射为公开 Schema。"""
    if value is None:
        return None
    return ChatContextWindow(**{
        "used_tokens": value.used_tokens,
        "budget_tokens": value.budget_tokens,
        "usage_percent": value.usage_percent,
        "counting_mode": value.counting_mode,
        "compression_status": value.compression_status,
        "strategy": value.strategy,
        "updated_at": value.updated_at,
    })


def _memory_command_schema(value):
    """把应用层命令结果转换为 REST/WS 共用的安全响应模型。"""
    if value is None:
        return None
    return MemoryCommandResultResponse(
        status=value.status.value,
        command_kind=value.command_kind.value if value.command_kind is not None else None,
        command_ref=value.command_ref,
        affected_count=value.affected_count,
        affected_record_ids=list(value.affected_record_ids),
        consistency_status=value.consistency_status,
        pending_confirmation_id=value.pending_confirmation_id,
        error_code=value.error_code,
        user_message=value.user_message,
        preview_items=list(value.preview_items),
    )


def _skill_confirmation_schema(value) -> SkillConfirmationResponse | None:
    """把领域确认载荷投影为不含权限和正文的公开模型。"""
    if value is None:
        return None
    return SkillConfirmationResponse(
        candidates=[
            SkillConfirmationCandidateResponse(
                skill_name=item.skill_name,
                confidence=item.confidence,
                version=item.version,
                reason=item.reason,
            )
            for item in value.candidates
        ],
        reason=value.reason,
        registry_snapshot_hash=value.registry_snapshot_hash,
    )


@router.post("/message", response_model=ChatMessageResponse, summary="发送消息（同步返回）")
async def send_message(
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> ChatMessageResponse:
    """校验身份并把同步请求交给唯一聊天用例。"""
    effective_user_id = ensure_user_access(body.user_id, auth)
    try:
        outcome = await build_chat_use_case(db).execute(
            ChatCommand(
                user_id=effective_user_id,
                message=body.message,
                session_id=body.session_id,
                request_id=body.request_id,
                explicit_skill=body.explicit_skill,
            )
        )
    except Exception as exc:
        logger.error(
            "chat.rest.failed error_code=%s error_type=%s",
            _CHAT_INTERNAL_ERROR,
            type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=_CHAT_INTERNAL_MESSAGE) from exc
    return ChatMessageResponse(
        reply=outcome.reply,
        session_id=outcome.session_id,
        memory_profile=outcome.memory_profile,
        context_window=_context_schema(outcome.context_window),
        memory_command=_memory_command_schema(outcome.memory_command),
        skill_confirmation=_skill_confirmation_schema(outcome.skill_confirmation),
    )


@router.websocket("/stream")
async def chat_stream(websocket: WebSocket) -> None:
    """校验单轮输入并发送唯一 ``chat-stream-v2`` 生命周期。

    WebSocket 层只负责认证、输入校验、v2 Schema 映射和连接清理。发送失败或
    客户端断连会关闭 Application 异步生成器，使取消传播到模型和未提交事务。
    """
    stream_state = _WebSocketStreamState(
        request_id=f"req_{uuid.uuid4().hex}",
        session_id="unavailable",
        started_at=time.perf_counter(),
    )
    await websocket.accept()
    try:
        auth = await authenticate_websocket(websocket)
        try:
            payload = json.loads(await websocket.receive_text())
        except json.JSONDecodeError:
            await _send_stream_error(
                websocket,
                stream_state,
                code="CHAT_INVALID_JSON",
                message="请求格式错误，需要 JSON",
            )
            return

        try:
            request = ChatMessageRequest.model_validate(payload)
        except ValidationError:
            await _send_stream_error(
                websocket,
                stream_state,
                code="CHAT_INVALID_REQUEST",
                message="user_id 和 message 不能为空",
            )
            return
        effective_user_id = ensure_user_access(request.user_id, auth)
        stream_state.request_id = request.request_id or stream_state.request_id
        stream_state.session_id = request.session_id or stream_state.session_id

        async with AsyncSessionFactory() as db:
            use_case = build_chat_use_case(db)
            event_stream = use_case.stream(
                ChatCommand(
                    user_id=effective_user_id,
                    message=request.message,
                    session_id=request.session_id,
                    request_id=request.request_id,
                    explicit_skill=request.explicit_skill,
                )
            )
            await _present_chat_stream_until_disconnect(websocket, event_stream, stream_state)
    except WebSocketDisconnect:
        logger.info(
            "chat.websocket.disconnected request_id=%s session_id=%s stage=%s status=%s "
            "chunk_count=%d output_chars=%d elapsed_ms=%.2f disconnect_reason=%s",
            stream_state.request_id,
            stream_state.session_id,
            "chat.websocket.send",
            "CANCELLED",
            stream_state.chunk_count,
            stream_state.output_chars,
            stream_state.elapsed_ms,
            "CLIENT_DISCONNECT",
        )
    except Exception as exc:
        logger.error(
            "chat.websocket.failed request_id=%s session_id=%s stage=%s status=%s "
            "chunk_count=%d output_chars=%d elapsed_ms=%.2f error_code=%s error_type=%s",
            stream_state.request_id,
            stream_state.session_id,
            "chat.websocket.send",
            "FAILED",
            stream_state.chunk_count,
            stream_state.output_chars,
            stream_state.elapsed_ms,
            _CHAT_INTERNAL_ERROR,
            type(exc).__name__,
        )
        if not stream_state.terminal_sent:
            try:
                await _send_stream_error(
                    websocket,
                    stream_state,
                    code=_CHAT_INTERNAL_ERROR,
                    message=_CHAT_INTERNAL_MESSAGE,
                )
            except Exception:
                logger.debug("chat.websocket.error_frame_skipped")
    finally:
        try:
            await websocket.close()
        except Exception:
            logger.debug("chat.websocket.close_skipped")


@router.get("/sessions", response_model=list[ChatSessionListItem], summary="会话列表")
async def list_sessions(
    user_id: str = Depends(require_query_user),
    q: Optional[str] = Query(None, description="搜索关键词（会话标题）"),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionListItem]:
    """返回当前用户的会话列表。"""
    records = await build_chat_session_use_case(db).list_sessions(user_id)
    if q:
        keyword = q.lower()
        records = [item for item in records if item.title and keyword in item.title.lower()]
    return [
        ChatSessionListItem(
            session_id=item.session_id,
            mode=item.mode,
            title=item.title,
            running_summary=item.running_summary,
            context_window=_context_schema(item.context_window),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in records
    ]


@router.patch("/sessions/{session_id}", summary="重命名会话")
async def rename_session(
    session_id: str,
    body: ChatSessionRenameRequest,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """重命名当前用户拥有的会话。"""
    changed = await build_chat_session_use_case(db).rename_session(
        session_id, user_id, body.title
    )
    if not changed:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "已重命名"}


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatSessionMessages,
    summary="会话完整消息历史",
)
async def get_session_messages(
    session_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionMessages:
    """返回当前用户可访问的会话消息。"""
    page = await build_chat_session_use_case(db).get_messages(session_id, user_id)
    return ChatSessionMessages(
        session_id=session_id,
        messages=[ChatMessage(**asdict(item)) for item in page.messages],
        context_window=_context_schema(page.context_window),
    )


@router.get(
    "/sessions/{session_id}/summaries",
    response_model=ChatSessionSummaries,
    summary="会话摘要历史（压缩快照）",
)
async def get_session_summaries(
    session_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionSummaries:
    """返回当前用户可访问的摘要快照。"""
    records = await build_chat_session_use_case(db).get_summaries(session_id, user_id)
    return ChatSessionSummaries(
        session_id=session_id,
        items=[ChatSummaryItem(**asdict(item)) for item in records],
    )


@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """删除当前用户拥有的会话。"""
    deleted = await build_chat_session_use_case(db).delete_session(session_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "已删除"}


@router.get("/templates", response_model=list[ChatTemplateItem], summary="获取模板问题列表")
async def get_templates(_: AuthContext = Depends(require_auth)) -> list[ChatTemplateItem]:
    """返回静态模板问题。"""
    return _TEMPLATES
