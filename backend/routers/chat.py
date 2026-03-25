"""对话路由 - Phase 2 新增 WebSocket 流式输出"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db, AsyncSessionFactory
from backend.middleware.auth import (
    AuthContext,
    authenticate_websocket,
    ensure_user_access,
    require_auth,
    require_query_user,
)
from backend.schemas.chat import (
    ChatMessage,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionListItem,
    ChatSessionMessages,
    ChatSessionSummaries,
    ChatSummaryItem,
    ChatSessionRenameRequest,
    ChatTemplateItem,
)
from backend.services import chat_service

logger = logging.getLogger("chat_router")

router = APIRouter()

# 预置模板问题
_TEMPLATES = [
    ChatTemplateItem(id="t1", label="基本面分析", content="帮我分析 [股票名] 的基本面"),
    ChatTemplateItem(id="t2", label="投资风险", content="这只股票近期有什么投资风险"),
    ChatTemplateItem(id="t3", label="估值判断", content="[股票名] 当前估值贵吗？"),
    ChatTemplateItem(id="t4", label="完整报告", content="帮我做一份完整的投研报告"),
    ChatTemplateItem(id="t5", label="对比分析", content="对比分析 [A] 和 [B] 哪只更值得买"),
    ChatTemplateItem(id="t6", label="持仓建议", content="结合我的风险偏好给出持仓建议"),
]


# ─────────────────────────────────────────────────────────────
# POST /api/chat/message
# ─────────────────────────────────────────────────────────────
@router.post("/message", response_model=ChatMessageResponse, summary="发送消息（同步返回）")
async def send_message(
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    effective_user_id = ensure_user_access(body.user_id, auth)
    reply, session_id, memory_profile = await chat_service.chat_single_turn(
        db=db,
        user_id=effective_user_id,
        user_message=body.message,
        session_id=body.session_id,
    )
    # Phase 3：响应体追加 memory_profile（前端在对话顶部/侧边展示"本次对话参考的用户画像"）
    return ChatMessageResponse(
        reply=reply,
        session_id=session_id,
        memory_profile=memory_profile if memory_profile else None,
    )


# ─────────────────────────────────────────────────────────────
# WebSocket /api/chat/stream  （Phase 2 实现：逐 token 推送）
# ─────────────────────────────────────────────────────────────
@router.websocket("/stream")
async def chat_stream(websocket: WebSocket):
    """
    Phase 2 流式对话 WebSocket。

    连接后客户端发送 JSON：
      {"user_id": "...", "message": "...", "session_id": "...（可选）"}

    服务端逐 token 推送纯文本，最后发送控制帧：
      {"type": "session_id", "session_id": "..."}  — 首帧（新建会话时）
      {"type": "done", "session_id": "..."}         — 完成
      {"type": "error", "message": "..."}           — 错误

    注意：每次连接只处理一条消息（一轮对话），前端在收到 done 后可继续发送。
    """
    await websocket.accept()
    logger.info("[WS /chat/stream] 新连接建立")
    print("[WS /chat/stream] 新连接建立")

    try:
        auth = await authenticate_websocket(websocket)
        # 接收请求体
        raw = await websocket.receive_text()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "message": "请求格式错误，需要 JSON"})
            await websocket.close()
            return

        user_id = payload.get("user_id", "").strip()
        user_message = payload.get("message", "").strip()
        session_id = payload.get("session_id") or None

        if not user_id or not user_message:
            await websocket.send_json({"type": "error", "message": "user_id 和 message 不能为空"})
            await websocket.close()
            return
        effective_user_id = ensure_user_access(user_id, auth)

        print(f"[WS /chat/stream] user={user_id[:8]} msg={user_message[:40]}...")
        logger.info(f"[WS /chat/stream] user={user_id}, session={session_id}, msg_len={len(user_message)}")

        # 使用独立 DB session（WebSocket 不走 HTTP 依赖注入）
        async with AsyncSessionFactory() as db:
            async for chunk in chat_service.stream_chat_single_turn(
                db=db,
                user_id=effective_user_id,
                user_message=user_message,
                session_id=session_id,
            ):
                await websocket.send_text(chunk)

    except WebSocketDisconnect:
        logger.info("[WS /chat/stream] 客户端断开连接")
        print("[WS /chat/stream] 客户端断开连接")
    except Exception as exc:
        logger.error(f"[WS /chat/stream] 异常: {exc}", exc_info=True)
        print(f"[WS /chat/stream] 异常: {exc}")
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# GET /api/chat/sessions
# ─────────────────────────────────────────────────────────────
@router.get("/sessions", response_model=list[ChatSessionListItem], summary="会话列表")
async def list_sessions(
    user_id: str = Depends(require_query_user),
    q: Optional[str] = Query(None, description="搜索关键词（会话标题）"),
    db: AsyncSession = Depends(get_db),
):
    sessions = await chat_service.get_sessions(db, user_id)
    if q:
        q_lower = q.lower()
        sessions = [s for s in sessions if s.title and q_lower in s.title.lower()]
    return [
        ChatSessionListItem(
            session_id=s.id,
            mode=s.mode,
            title=s.title,
            running_summary=s.running_summary,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


# ─────────────────────────────────────────────────────────────
# PATCH /api/chat/sessions/{id}  重命名
# ─────────────────────────────────────────────────────────────
@router.patch("/sessions/{session_id}", summary="重命名会话")
async def rename_session(
    session_id: str,
    body: ChatSessionRenameRequest,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await chat_service.rename_session(db, session_id, user_id, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "已重命名"}


# ─────────────────────────────────────────────────────────────
# GET /api/chat/sessions/{id}/messages
# ─────────────────────────────────────────────────────────────
@router.get("/sessions/{session_id}/messages", response_model=ChatSessionMessages, summary="会话完整消息历史")
async def get_session_messages(
    session_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    messages = await chat_service.get_session_messages(db, session_id, user_id)
    return ChatSessionMessages(
        session_id=session_id,
        messages=[
            ChatMessage(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                is_compressed=m.is_compressed,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


# ─────────────────────────────────────────────────────────────
# GET /api/chat/sessions/{id}/summaries
# ─────────────────────────────────────────────────────────────
@router.get(
    "/sessions/{session_id}/summaries",
    response_model=ChatSessionSummaries,
    summary="会话摘要历史（压缩快照）",
)
async def get_session_summaries(
    session_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    items = await chat_service.get_session_summaries(db, session_id, user_id)
    return ChatSessionSummaries(
        session_id=session_id,
        items=[ChatSummaryItem.model_validate(i) for i in items],
    )


# ─────────────────────────────────────────────────────────────
# DELETE /api/chat/sessions/{id}
# ─────────────────────────────────────────────────────────────
@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: str,
    user_id: str = Depends(require_query_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await chat_service.delete_session(db, session_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "已删除"}


# ─────────────────────────────────────────────────────────────
# GET /api/chat/templates
# ─────────────────────────────────────────────────────────────
@router.get("/templates", response_model=list[ChatTemplateItem], summary="获取模板问题列表")
async def get_templates(_: AuthContext = Depends(require_auth)):
    return _TEMPLATES
