import asyncio
import copy
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session
from backend.services.chat.constants import InvalidSopSkillError, _ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE, _is_context_overflow_error
from backend.services.chat.session import _RECENT_MSG_LIMIT
from backend.services.chat_route_runtime import get_runtime_route_state, seed_route_runtime_from_summary_payload
from backend.services.entity_resolver import resolve_entity
from backend.services.stm_summary_runtime import (
    format_answer_policy_context,
    format_route_active_entities_context,
    resolve_session_rolling_payload,
)


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


def _ensure_skill_runtime_ready() -> None:
    chat_service = _chat_service_facade()
    if chat_service._skill_runtime_checked:
        return

    try:
        chat_service.get_skill_registry(refresh=True)
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] skill registry init failed: %s", exc, exc_info=True)

    chat_service.configure_tushare_client_factory(
        lambda: chat_service.TushareClient(token=settings.tushare_token or "")
    )
    chat_service._skill_runtime_checked = True


def normalize_requested_sop_skill_id(sop_skill_id: str | None) -> str | None:
    normalized = str(sop_skill_id or "").strip()
    return normalized or None


def validate_requested_sop_skill_id(sop_skill_id: str | None) -> str | None:
    normalized = normalize_requested_sop_skill_id(sop_skill_id)
    if normalized is None:
        return None

    _ensure_skill_runtime_ready()
    if _chat_service_facade().user_explicit_sop_decision(normalized) is None:
        raise InvalidSopSkillError(f"无效的 sop_skill_id: {normalized}")
    return normalized


def list_discoverable_sop_skills() -> list[dict[str, str]]:
    _ensure_skill_runtime_ready()
    chat_service = _chat_service_facade()
    items: list[dict[str, str]] = []
    for skill in chat_service.get_skill_registry().discoverable_sop_skills():
        items.append(
            {
                "name": skill.name,
                "official_name": str(skill.official_name or ""),
                "description": str(skill.description or ""),
                "execution_mode": chat_service.registry_execution_policy_for_skill(skill.name),
            }
        )
    return items


async def _load_memory_context_for_chat(
    db: AsyncSession,
    user_id: str,
    user_message: str,
) -> tuple[dict, str]:
    chat_service = _chat_service_facade()
    memory_profile = {}
    memory_system_prompt = ""
    if not settings.enable_memory or not user_id:
        with chat_service.trace_span(
            "memory_read",
            stage="memory",
            data={
                "memory_enabled": bool(settings.enable_memory),
                "enqueue_skipped_reason": "memory_disabled" if not settings.enable_memory else "missing_user_id",
                "user_message_summary": chat_service._trace_query_summary(user_message, limit=80),
            },
        ):
            pass
        return memory_profile, memory_system_prompt

    started = time.perf_counter()
    with chat_service.trace_span(
        "memory_read",
        stage="memory",
        data={
            "memory_enabled": True,
            "user_message_summary": chat_service._trace_query_summary(user_message, limit=80),
        },
    ):
        try:
            ctx = await asyncio.wait_for(
                chat_service._memory_svc.get_memory_context_for_chat(user_id, user_message, db),
                timeout=max(1, int(settings.memory_context_timeout_sec)),
            )
            memory_profile = ctx.get("profile", {})
            semantic_memories = ctx.get("semantic_memories", [])
            memory_system_prompt = chat_service._build_memory_system_prompt(memory_profile, semantic_memories)
            if memory_system_prompt:
                print(f"[LTM-chat] 注入用户画像到对话上下文 (user={user_id[:8]}...)")
                chat_service.logger.info(
                    f"[LTM-chat] 注入 memory_context: user={user_id}, len={len(memory_system_prompt)}"
                )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            if elapsed_ms >= 1500:
                chat_service.logger.warning(
                    "[LTM-chat] memory_context slow: user=%s elapsed_ms=%s",
                    user_id,
                    elapsed_ms,
                )
        except asyncio.TimeoutError:
            chat_service.logger.warning(
                "[LTM-chat] memory_context timeout: user=%s timeout_sec=%s",
                user_id,
                settings.memory_context_timeout_sec,
            )
        except Exception as exc:
            chat_service.logger.warning(f"[LTM-chat] 读取画像失败（不影响对话）: {exc}")
    return memory_profile, memory_system_prompt


async def _build_skill_route_context(
    db: AsyncSession,
    session: Session,
    *,
    exclude_message_id: int | None = None,
    route_slice_text: str = "",
) -> str:
    """构建路由"对话快照"：route slice + 最近对话原文。

    用户消息保留全文，助手消息截断到 _ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE 字符。
    route slice 只承担主语补全、指代消解、follow-up 实体继承，不再注入全文摘要。
    """
    parts: list[str] = []

    if settings.enable_stm and route_slice_text:
        parts.append(route_slice_text)

    if settings.enable_stm:
        stmt = select(Message).where(
            Message.session_id == session.id,
            Message.is_compressed == False,  # noqa: E712
        )
    else:
        stmt = select(Message).where(Message.session_id == session.id)

    if exclude_message_id is not None:
        stmt = stmt.where(Message.id != exclude_message_id)

    stmt = stmt.order_by(Message.created_at.desc()).limit(_RECENT_MSG_LIMIT + 1)
    history_result = await db.execute(stmt)
    recent_messages = list(reversed(history_result.scalars().all()))

    if recent_messages:
        dialogue_lines = []
        truncate_len = _ROUTE_SNAPSHOT_ASSISTANT_TRUNCATE
        for msg in recent_messages:
            role = "用户" if msg.role == "user" else "助手"
            content = (msg.content or "").strip()
            if msg.role == "assistant" and len(content) > truncate_len:
                content = content[:truncate_len] + "…"
            dialogue_lines.append(f"{role}: {content}")
        parts.append("【最近对话记录】\n" + "\n".join(dialogue_lines))

    return "\n\n".join(parts)


def _resolver_hint_to_prompt_block(resolver_hint: dict[str, Any] | None) -> str:
    hint = dict(resolver_hint or {})
    if not hint:
        return ""
    display_name = str(hint.get("display_name") or "").strip() or "unknown"
    asset_type = str(hint.get("asset_type") or "").strip() or "unknown"
    symbol = str(hint.get("symbol") or "").strip() or "unknown"
    confidence = float(hint.get("confidence") or 0.0)
    stage = str(hint.get("resolver_stage") or "").strip() or "unknown"
    return (
        "【已解析实体提示】\n"
        f"display_name={display_name}\n"
        f"asset_type={asset_type}\n"
        f"symbol={symbol}\n"
        f"confidence={confidence:.4f}\n"
        f"resolver_stage={stage}"
    )


def _resolver_hint_payload(resolution: Any) -> dict[str, Any] | None:
    if resolution is None or not getattr(resolution, "ok", False):
        return None
    confidence = float(getattr(resolution, "confidence", 0.0) or 0.0)
    if confidence < 0.75:
        return None
    payload = {
        "display_name": str(getattr(resolution, "display_name", "") or "").strip(),
        "asset_type": str(getattr(resolution, "asset_type", "") or "").strip(),
        "symbol": str(getattr(resolution, "symbol", "") or "").strip(),
        "confidence": confidence,
        "resolver_stage": str(getattr(resolution, "resolver_stage", "") or "").strip(),
        "resolver_source": str(getattr(resolution, "resolver_source", "") or "").strip(),
    }
    if not payload["display_name"] and not payload["symbol"]:
        return None
    return payload


async def _resolve_entity_hint_for_route(session: Session, user_message: str) -> dict[str, Any] | None:
    chat_service = _chat_service_facade()
    runtime_state = get_runtime_route_state(session.id)
    summary_active_symbols: list[str] | None = None
    if runtime_state is None and settings.enable_stm:
        payload = resolve_session_rolling_payload(session)
        runtime_state = seed_route_runtime_from_summary_payload(payload, runtime_state)
        route_slice = payload.get("active_entities") if isinstance(payload, dict) else None
        if isinstance(route_slice, list):
            summary_active_symbols = [
                str(item.get("canonical_id") or "").strip()
                for item in route_slice
                if isinstance(item, dict) and str(item.get("canonical_id") or "").strip()
            ] or None
    session_symbols: list[str] | None = None
    if runtime_state is not None and str(runtime_state.active_entity_id or "").strip():
        session_symbols = [str(runtime_state.active_entity_id or "").strip()]
    try:
        resolution = await resolve_entity(
            user_message,
            session_symbols=session_symbols,
            summary_active_symbols=summary_active_symbols,
        )
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] resolve_entity hint failed (non-fatal): %s", exc)
        return None
    return _resolver_hint_payload(resolution)


def _should_offer_skill_hitl(route: Any) -> bool:
    if not settings.enable_skill_route_hitl:
        return False
    thr = float(settings.skill_route_hitl_confidence_threshold)
    if float(route.confidence or 0.0) >= thr:
        return False
    if str(route.selected_skill or "") == "fallback":
        return False
    return True


def _sop_execution_policy_for_name(skill_name: str) -> str:
    return _chat_service_facade().registry_execution_policy_for_skill(skill_name)


def _build_broad_skill_confirm_options() -> list[dict[str, Any]]:
    """fallback 或未命中时，列出可选 SOP 技能 + tushare + 纯对话。"""
    chat_service = _chat_service_facade()
    opts: list[dict[str, Any]] = []
    skills = chat_service.get_skill_registry().discoverable_sop_skills()
    for i, s in enumerate(skills[:14]):
        label = (s.official_name or s.name or "").strip() or s.name
        desc = (s.description or "")[:48]
        if desc:
            label = f"{label} — {desc}"
        opts.append(
            {
                "key": s.name,
                "label": label,
                "recommended": i == 0,
            }
        )
    opts.append(
        {
            "key": "tushare-data",
            "label": "实时行情 / Tushare 数据拉取",
            "recommended": False,
        }
    )
    opts.append(
        {
            "key": "fallback",
            "label": "不要技能链路，直接 AI 回答",
            "recommended": False,
        }
    )
    return opts


def _build_skill_confirm_options(route: Any) -> list[dict[str, Any]]:
    opts: list[dict[str, Any]] = []
    fam = str(route.selected_skill_family or "")
    if fam == "financial-sop" and route.skill_name:
        opts.append(
            {
                "key": str(route.skill_name),
                "label": f"按推荐执行技能：{route.skill_name}",
                "recommended": True,
            }
        )
    elif str(route.selected_skill) == "tushare-data":
        opts.append(
            {
                "key": "tushare-data",
                "label": "使用实时金融数据（Tushare）",
                "recommended": True,
            }
        )
    else:
        sk = str(route.selected_skill or "")
        if sk and sk != "fallback":
            opts.append({"key": sk, "label": f"继续：{sk}", "recommended": True})
    opts.append(
        {
            "key": "fallback",
            "label": "直接由 AI 回答（不强制工具链路）",
            "recommended": False,
        }
    )
    return opts


def _build_skill_confirm_options_from_trace(route_trace: dict[str, Any]) -> list[dict[str, Any]]:
    chat_service = _chat_service_facade()
    candidates = [str(item) for item in (route_trace.get("confirm_candidates") or []) if str(item).strip()]
    if not candidates and route_trace.get("skill_name"):
        candidates = [str(route_trace["skill_name"])]
    opts: list[dict[str, Any]] = []
    sop_names = {s.name for s in chat_service.get_skill_registry().discoverable_sop_skills()}
    for idx, key in enumerate(candidates):
        if key in sop_names:
            opts.append({"key": key, "label": f"按推荐执行技能：{key}", "recommended": idx == 0})
        elif key == "tushare-data":
            opts.append({"key": key, "label": "使用实时金融数据（Tushare）", "recommended": idx == 0})
    if not any(item.get("key") == "fallback" for item in opts):
        opts.append({"key": "fallback", "label": "直接由 AI 回答（不强制工具链路）", "recommended": False})
    return opts


def _apply_hitl_choice_to_route_dict(route_dict: dict[str, Any], choice: str) -> dict[str, Any]:
    chat_service = _chat_service_facade()
    out = copy.deepcopy(route_dict)
    choice = (choice or "").strip()
    args = dict(out.get("arguments") or {})
    sop_names = {s.name for s in chat_service.get_skill_registry().discoverable_sop_skills()}

    if choice == "fallback":
        out["selected_skill"] = "fallback"
        out["selected_skill_family"] = "fallback"
        out["skill_name"] = None
        out["route_kind"] = "fallback"
        out["grounding_policy"] = "none"
        out["claim_policy"] = "full"
        out["execution_policy"] = "agentic"
        out["analysis_mode"] = "general_chat"
        out["needs_realtime_data"] = False
        out["needs_professional_analysis"] = False
        out["confidence"] = 1.0
        out["skill_contract"] = ""
        out["arguments"] = args
        return out

    if choice in sop_names:
        out["selected_skill"] = "financial-sop"
        out["selected_skill_family"] = "financial-sop"
        out["skill_name"] = choice
        out["route_kind"] = "financial_sop"
        out["grounding_policy"] = "preferred"
        out["claim_policy"] = "cautious"
        out["execution_policy"] = _sop_execution_policy_for_name(choice)
        out["skill_contract"] = choice
        out["needs_realtime_data"] = True
        out["needs_professional_analysis"] = True
        out["confidence"] = 1.0
        out["analysis_mode"] = str(out.get("analysis_mode") or "")
        out["arguments"] = args
        return out

    if choice == "tushare-data":
        out["selected_skill"] = "tushare-data"
        out["selected_skill_family"] = "tushare-data"
        out["skill_name"] = None
        out["route_kind"] = "tushare_data"
        out["grounding_policy"] = "required"
        out["claim_policy"] = "cautious"
        out["execution_policy"] = "deterministic"
        out["skill_contract"] = ""
        out["needs_realtime_data"] = True
        out["needs_professional_analysis"] = False
        out["confidence"] = 1.0
        if not str(out.get("analysis_mode") or "").strip():
            out["analysis_mode"] = "general_chat"
        out["arguments"] = args
        return out

    return out


async def confirm_skill_route(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    user_choice: str,
) -> tuple[str, dict, object, dict | None]:
    """
    Resume a low-confidence route after user confirms skill choice (HITL).
    Consumes one pending record from chat_hitl_pending.
    """
    chat_service = _chat_service_facade()
    pending = chat_service.pop_pending_skill_confirm(session_id)
    if not pending or pending.get("user_id") != user_id:
        raise ValueError("没有待确认的路由，或已过期。请重新发送消息。")

    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise ValueError("会话不存在")

    user_message = str(pending.get("user_message") or "")
    route_dict = _apply_hitl_choice_to_route_dict(pending.get("route_dict") or {}, user_choice)
    route_trace = dict(route_dict)

    memory_profile, memory_system_prompt = await chat_service._load_memory_context_for_chat(db, user_id, user_message)
    _, _, answer_policy_context = chat_service._resolve_session_summary_contexts(session)
    turn_trace: dict = dict(route_trace)

    if str(route_trace.get("selected_skill") or "") == "fallback":
        llm = chat_service._get_llm()
        lc_messages = await chat_service._build_fallback_chat_messages(
            db,
            session,
            memory_system_prompt=memory_system_prompt,
        )
        try:
            response = await llm.ainvoke(lc_messages)
        except Exception as exc:
            if not _is_context_overflow_error(exc):
                raise
            recovered = await chat_service._force_overflow_recovery_compaction(
                db,
                session,
                user_message=user_message,
                exc=exc,
            )
            if not recovered:
                raise
            lc_messages = await chat_service._build_fallback_chat_messages(
                db,
                session,
                memory_system_prompt=memory_system_prompt,
            )
            response = await llm.ainvoke(lc_messages)
        reply_text = response.content if hasattr(response, "content") else str(response)
        chat_service.log_reply_completed(
            mode="fallback-hitl-confirm",
            session_id=session.id,
            user_id=user_id,
            selected_skill_family="fallback",
            selected_skill="fallback",
            analysis_mode="general_chat",
            execution_policy="agentic",
        )
    else:
        _exec_data = {
            "selected_skill_family": route_trace.get("selected_skill_family"),
            "selected_skill": route_trace.get("selected_skill"),
            "skill_name": route_trace.get("skill_name"),
            "analysis_mode": route_trace.get("analysis_mode"),
            "execution_policy": route_trace.get("execution_policy"),
        }
        with chat_service.trace_span("executor", stage="executor", data=_exec_data):
            result = await chat_service.execute_skill(
                selected_skill=str(route_trace.get("selected_skill") or "fallback"),
                user_message=user_message,
                memory_context=memory_system_prompt,
                answer_policy_context=answer_policy_context,
                profile_summary=chat_service._profile_to_summary(memory_profile),
                session_id=session.id,
                user_id=user_id,
                route_trace=route_trace,
                enable_tushare_skills=settings.enable_tushare_skills,
                enable_tushare_planner=settings.enable_tushare_planner,
                enable_tushare_market_tools=settings.enable_tushare_market_tools,
                enable_tushare_index_tools=settings.enable_tushare_index_tools,
                enable_tushare_sector_tools=settings.enable_tushare_sector_tools,
                enable_fundamental_analysis=settings.enable_fundamental_analysis,
                enable_sector_analysis=settings.enable_sector_analysis,
                enable_stock_selection=settings.enable_stock_selection,
                enable_deterministic_skill_execution=settings.enable_deterministic_skill_execution,
                enable_tool_prefetch_concurrency=settings.enable_tool_prefetch_concurrency,
            )
        if chat_service._executor_qualifies_for_evidence_retry(result.trace):
            with chat_service.trace_span("executor_retry", stage="executor", data={**_exec_data, "retry": True}):
                result = await chat_service.execute_skill(
                    selected_skill=str(route_trace.get("selected_skill") or "fallback"),
                    user_message=user_message,
                    memory_context=memory_system_prompt,
                    answer_policy_context=answer_policy_context,
                    profile_summary=chat_service._profile_to_summary(memory_profile),
                    session_id=session.id,
                    user_id=user_id,
                    route_trace=route_trace,
                    enable_tushare_skills=settings.enable_tushare_skills,
                    enable_tushare_planner=settings.enable_tushare_planner,
                    enable_tushare_market_tools=settings.enable_tushare_market_tools,
                    enable_tushare_index_tools=settings.enable_tushare_index_tools,
                    enable_tushare_sector_tools=settings.enable_tushare_sector_tools,
                    enable_fundamental_analysis=settings.enable_fundamental_analysis,
                    enable_sector_analysis=settings.enable_sector_analysis,
                    enable_stock_selection=settings.enable_stock_selection,
                    enable_deterministic_skill_execution=settings.enable_deterministic_skill_execution,
                    enable_tool_prefetch_concurrency=settings.enable_tool_prefetch_concurrency,
                )
        reply_text = result.reply_text
        turn_trace = dict(route_trace)
        turn_trace["executor"] = result.trace
        chat_service.log_reply_completed(
            mode="skill-hitl-confirm",
            session_id=session.id,
            user_id=user_id,
            selected_skill_family=turn_trace.get("selected_skill_family"),
            selected_skill=turn_trace.get("selected_skill"),
            skill_name=turn_trace.get("skill_name"),
            analysis_mode=turn_trace.get("analysis_mode"),
            execution_policy=turn_trace.get("execution_policy"),
        )

    if settings.enable_memory and user_id:
        reply_text = await chat_service._prepare_reply_for_user(reply_text, user_id=user_id, db=db)

    chat_service._record_route_runtime_with_log(
        session_id=session.id,
        user_message=user_message,
        route_trace=turn_trace,
        reply_text=reply_text,
    )
    route_summary = chat_service._build_route_summary(turn_trace)

    ai_msg = Message(
        session_id=session.id,
        role="assistant",
        content=str(reply_text or ""),
        token_count=chat_service.count_message_tokens("assistant", str(reply_text or ""))[0],
        route_summary_json=chat_service._persistable_route_summary(route_summary),
    )
    db.add(ai_msg)
    session.turn_count = (session.turn_count or 0) + 1
    session.updated_at = chat_service.datetime.utcnow()
    await db.flush()
    user_msg_id_result = await db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.role == "user")
        .order_by(Message.id.desc())
        .limit(1)
    )
    latest_user_msg_id = user_msg_id_result.scalar_one_or_none()
    await chat_service._apply_route_entities_to_stm_with_log(
        db=db,
        session=session,
        user_message=user_message,
        route_trace=turn_trace,
    )
    if latest_user_msg_id is not None:
        chat_service.logger.info(
            "[STM-chat] 旧异步 STM 链路已停用: session=%s user_msg=%s assistant_msg=%s",
            session.id,
            latest_user_msg_id,
            ai_msg.id,
        )
    context_window = await chat_service.refresh_session_context_metrics(db, session)
    context_window = chat_service.enrich_context_window(context_window, session.id)
    await db.commit()

    if settings.enable_memory and user_id:
        asyncio.create_task(chat_service.maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))
        chat_service.log_memory_enqueue(
            session_id=session.id,
            user_id=user_id,
            queued=True,
            turn_index=session.turn_count,
        )

    return reply_text, memory_profile, context_window, route_summary
