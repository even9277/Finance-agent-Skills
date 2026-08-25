"""对话 HTTP/WebSocket 协议适配层。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.chat.contracts import ChatCommand, ChatContextWindowData
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
    ChatContextWindow,
    ChatMessage,
    ChatMessageRequest,
    ChatMessageResponse,
    MemoryCommandResultResponse,
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

_TEMPLATES = [
    ChatTemplateItem(id="t1", label="基本面分析", content="帮我分析 [股票名] 的基本面"),
    ChatTemplateItem(id="t2", label="投资风险", content="这只股票近期有什么投资风险"),
    ChatTemplateItem(id="t3", label="估值判断", content="[股票名] 当前估值贵吗？"),
    ChatTemplateItem(id="t4", label="完整报告", content="帮我做一份完整的投研报告"),
    ChatTemplateItem(id="t5", label="对比分析", content="对比分析 [A] 和 [B] 哪只更值得买"),
    ChatTemplateItem(id="t6", label="持仓建议", content="结合我的风险偏好给出持仓建议"),
]


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
    )


@router.websocket("/stream")
async def chat_stream(websocket: WebSocket) -> None:
    """把同一聊天用例结果映射为兼容的 WebSocket 基础帧。

    客户端每次连接发送一轮 JSON。服务端依次发送 ``session_id``、回答文本、
    可选 ``context_update`` 和 ``done``；内部异常只返回稳定错误码与安全文案。
    """
    await websocket.accept()
    try:
        auth = await authenticate_websocket(websocket)
        try:
            payload = json.loads(await websocket.receive_text())
        except json.JSONDecodeError:
            await websocket.send_json(
                {"type": "error", "code": "CHAT_INVALID_JSON", "message": "请求格式错误，需要 JSON"}
            )
            return

        user_id = str(payload.get("user_id") or "").strip()
        message = str(payload.get("message") or "").strip()
        session_id = payload.get("session_id") or None
        if not user_id or not message:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "CHAT_INVALID_REQUEST",
                    "message": "user_id 和 message 不能为空",
                }
            )
            return
        effective_user_id = ensure_user_access(user_id, auth)

        async with AsyncSessionFactory() as db:
            outcome = await build_chat_use_case(db).execute(
                ChatCommand(
                    user_id=effective_user_id,
                    message=message,
                    session_id=session_id,
                )
            )

        await websocket.send_json({"type": "session_id", "session_id": outcome.session_id})
        memory_command = _memory_command_schema(outcome.memory_command)
        if memory_command is not None:
            await websocket.send_json(
                {
                    "type": "memory_command",
                    "session_id": outcome.session_id,
                    "memory_command": memory_command.model_dump(mode="json"),
                }
            )
        if outcome.reply:
            await websocket.send_text(outcome.reply)
        context = _context_schema(outcome.context_window)
        if context is not None:
            await websocket.send_json(
                {
                    "type": "context_update",
                    "session_id": outcome.session_id,
                    "context_window": context.model_dump(mode="json"),
                }
            )
        await websocket.send_json({"type": "done", "session_id": outcome.session_id})
    except WebSocketDisconnect:
        logger.info("chat.websocket.disconnected")
    except Exception as exc:
        logger.error(
            "chat.websocket.failed error_code=%s error_type=%s",
            _CHAT_INTERNAL_ERROR,
            type(exc).__name__,
            exc_info=True,
        )
        try:
            await websocket.send_json(
                {"type": "error", "code": _CHAT_INTERNAL_ERROR, "message": _CHAT_INTERNAL_MESSAGE}
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
