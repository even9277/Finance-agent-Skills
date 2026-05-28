"""对话路由 - Phase 2 新增 WebSocket 流式输出"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.database import get_db, AsyncSessionFactory
from backend.db.models import Session
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
    SopSkillListItem,
    SkillConfirmOption,
    SkillConfirmPayload,
    SkillConfirmRequest,
)
from backend.services import chat_service
from backend.services.chat_route_runtime import enrich_context_window
from backend.services.stm_context_service import build_context_window_payload

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
    try:
        (
            reply,
            session_id,
            memory_profile,
            context_window,
            route_summary,
            skill_confirm_raw,
            reserved,
        ) = await chat_service.chat_single_turn(
            db=db,
            user_id=effective_user_id,
            user_message=body.message,
            session_id=body.session_id,
            sop_skill_id=body.sop_skill_id,
        )
    except chat_service.InvalidSopSkillError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    skill_confirm: SkillConfirmPayload | None = None
    if skill_confirm_raw:
        opt_models: list[SkillConfirmOption] = []
        for o in skill_confirm_raw.get("options") or []:
            if isinstance(o, dict):
                opt_models.append(
                    SkillConfirmOption(
                        key=str(o.get("key") or ""),
                        label=str(o.get("label") or o.get("key") or ""),
                        recommended=bool(o.get("recommended")),
                    )
                )
            else:
                opt_models.append(SkillConfirmOption(key=str(o), label=str(o)))
        skill_confirm = SkillConfirmPayload(
            session_id=skill_confirm_raw.get("session_id") or session_id,
            options=opt_models,
            reasoning=str(skill_confirm_raw.get("reasoning") or ""),
            resolved_query=str(skill_confirm_raw.get("resolved_query") or ""),
            confidence=float(skill_confirm_raw.get("confidence") or 0.0),
        )
    sess_row = await db.get(Session, session_id) if session_id else None
    # Phase 3：响应体追加 memory_profile（前端在对话顶部/侧边展示"本次对话参考的用户画像"）
    return ChatMessageResponse(
        reply=reply,
        session_id=session_id,
        memory_profile=memory_profile if memory_profile else None,
        context_window=context_window,
        route_summary=route_summary,
        running_summary=(sess_row.running_summary if sess_row else None),
        running_summary_state=(sess_row.running_summary_state if sess_row else None),
        running_summary_mode=(sess_row.running_summary_mode if sess_row else None),
        skill_confirm=skill_confirm,
        plan_artifact=(reserved or {}).get("plan_artifact") if isinstance(reserved, dict) else None,
        skill_artifact=(reserved or {}).get("skill_artifact") if isinstance(reserved, dict) else None,
        verification=(reserved or {}).get("verification") if isinstance(reserved, dict) else None,
        allowed_claim_level=(reserved or {}).get("allowed_claim_level") if isinstance(reserved, dict) else None,
    )


@router.post(
    "/sessions/{session_id}/confirm-skill",
    response_model=ChatMessageResponse,
    summary="确认低置信度路由后继续生成回复",
)
async def confirm_skill(
    session_id: str,
    body: SkillConfirmRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    effective_user_id = ensure_user_access(body.user_id, auth)
    try:
        reply, memory_profile, context_window, route_summary = await chat_service.confirm_skill_route(
            db=db,
            user_id=effective_user_id,
            session_id=session_id,
            user_choice=body.user_choice.strip(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    sess = await db.get(Session, session_id)
    return ChatMessageResponse(
        reply=reply,
        session_id=session_id,
        memory_profile=memory_profile if memory_profile else None,
        context_window=context_window,
        route_summary=route_summary,
        running_summary=(sess.running_summary if sess else None),
        running_summary_state=(sess.running_summary_state if sess else None),
        running_summary_mode=(sess.running_summary_mode if sess else None),
        skill_confirm=None,
    )


# ─────────────────────────────────────────────────────────────
# WebSocket /api/chat/stream  （Phase 2 实现：逐 token 推送）
# ─────────────────────────────────────────────────────────────
@router.websocket("/stream")
async def chat_stream(websocket: WebSocket):
    """
    Phase 2 流式对话 WebSocket。

    连接后客户端发送 JSON：
      {"user_id": "...", "message": "...", "session_id": "...（可选）", "sop_skill_id": "...（可选）"}

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
        sop_skill_id = chat_service.normalize_requested_sop_skill_id(payload.get("sop_skill_id"))

        if not user_id or not user_message:
            await websocket.send_json({"type": "error", "message": "user_id 和 message 不能为空"})
            await websocket.close()
            return
        effective_user_id = ensure_user_access(user_id, auth)
        if chat_service.settings.enable_chat_skills:
            try:
                sop_skill_id = chat_service.validate_requested_sop_skill_id(sop_skill_id)
            except chat_service.InvalidSopSkillError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                await websocket.close(code=1008)
                return
        else:
            sop_skill_id = None

        print(f"[WS /chat/stream] user={user_id[:8]} msg={user_message[:40]}...")
        logger.info(
            "[WS /chat/stream] user=%s, session=%s, msg_len=%s, sop_skill_id=%s",
            user_id,
            session_id,
            len(user_message),
            sop_skill_id or "",
        )

        # 使用独立 DB session（WebSocket 不走 HTTP 依赖注入）
        async with AsyncSessionFactory() as db:
            async for chunk in chat_service.stream_chat_single_turn(
                db=db,
                user_id=effective_user_id,
                user_message=user_message,
                session_id=session_id,
                sop_skill_id=sop_skill_id,
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


@router.get("/sop-skills", response_model=list[SopSkillListItem], summary="可显式选择的 SOP 技能列表")
async def list_sop_skills(auth: AuthContext = Depends(require_auth)):
    _ = auth
    return [
        SopSkillListItem(**item)
        for item in chat_service.list_discoverable_sop_skills()
    ]


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
            running_summary_state=s.running_summary_state,
            running_summary_mode=s.running_summary_mode,
            context_window=enrich_context_window(build_context_window_payload(s), s.id),
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
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = session_result.scalar_one_or_none()
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
                route_summary=m.route_summary_json if getattr(m, "route_summary_json", None) else None,
                plan_artifact=getattr(m, "plan_artifact_json", None),
                skill_artifact=getattr(m, "skill_artifact_json", None),
                verification=getattr(m, "verification_json", None),
                allowed_claim_level=getattr(m, "allowed_claim_level", None),
            )
            for m in messages
        ],
        running_summary=session.running_summary if session else None,
        running_summary_state=session.running_summary_state if session else None,
        running_summary_mode=session.running_summary_mode if session else None,
        context_window=enrich_context_window(build_context_window_payload(session), session.id) if session else None,
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
        items=[
            ChatSummaryItem(
                id=i.id,
                session_id=i.session_id,
                summary=i.summary,
                summary_payload=i.summary_payload,
                summary_mode=i.summary_mode,
                summary_trigger=i.summary_trigger,
                compressed_message_count=i.compressed_message_count,
                total_message_count=i.total_message_count,
                created_at=i.created_at,
            )
            for i in items
        ],
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
