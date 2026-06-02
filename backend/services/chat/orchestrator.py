import asyncio
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


async def chat_single_turn(
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: Optional[str] = None,
    sop_skill_id: str | None = None,
) -> tuple[str, str, dict, object, dict | None, dict | None, dict | None]:
    """
    执行单轮对话，返回 (
        reply, session_id, memory_profile, context_window, route_summary, skill_confirm, reserved
    )。
    skill_confirm 非空时表示 HITL，reply 为空，需调 confirm-skill。
    """
    chat_service = _chat_service_facade()
    session = await chat_service.get_or_create_session(db, user_id, session_id)
    trace_id = chat_service.new_trace_id()
    trace_started = time.perf_counter()
    final_selected_skill_family = "fallback"
    final_selected_skill = "fallback"
    final_skill_name = None
    final_analysis_mode = "general_chat"
    final_execution_policy = "agentic"
    final_status = "ok"
    turn_trace: dict = {}

    with chat_service.skill_trace_context(
        trace_id=trace_id,
        group_id=session.id,
        session_id=session.id,
        user_id=user_id,
        workflow_name="chat-skill-turn",
        policy_version="trace-v1",
        trace_schema_version="2026-04-02.1",
        turn_index=(session.turn_count or 0) + 1,
    ):
        chat_service.log_trace_started(user_query_summary=chat_service._trace_query_summary(user_message))
        try:
            normalized_sop_skill_id = None
            if settings.enable_chat_skills:
                normalized_sop_skill_id = chat_service.validate_requested_sop_skill_id(sop_skill_id)

            # Phase 3：支持用户直接发送 JSON action（而非由 LLM 输出 <action>）
            # 例如：{"action":"update_profile","field":"sectors","value":[...]}后面跟自然语言
            if settings.enable_memory and user_id:
                user_message = await chat_service._handle_profile_action_in_user_message(db, user_id, user_message)

            # 保存用户消息
            user_msg = chat_service.Message(
                session_id=session.id,
                role="user",
                content=user_message,
                token_count=chat_service.count_message_tokens("user", user_message)[0],
            )
            db.add(user_msg)
            await db.flush()

            # 更新会话标题（取第一条用户消息前 30 字）
            if not session.title:
                session.title = user_message[:30]
                await db.flush()

            memory_profile, memory_system_prompt = await chat_service._prepare_chat_preflight_inputs(
                db,
                session,
                user_id=user_id,
                user_message=user_message,
            )
            await chat_service._run_chat_preflight_compaction(
                db,
                session,
                user_message=user_message,
                user_message_id=int(user_msg.id),
                memory_system_prompt=memory_system_prompt,
                trigger="preflight_budget_sync_chat",
            )

            skill_reply_text, memory_profile, skill_trace, memory_system_prompt = await chat_service._run_skill_chat_if_enabled(
                db=db,
                session=session,
                user_id=user_id,
                user_message=user_message,
                sop_skill_id=normalized_sop_skill_id,
                exclude_message_id=user_msg.id,
                preloaded_memory_profile=memory_profile,
                preloaded_memory_system_prompt=memory_system_prompt,
            )
            turn_trace = skill_trace or {}
            final_selected_skill_family = str(
                skill_trace.get("selected_skill_family") or final_selected_skill_family
            )
            final_selected_skill = str(skill_trace.get("selected_skill") or final_selected_skill)
            final_skill_name = skill_trace.get("skill_name") or final_skill_name
            final_analysis_mode = str(skill_trace.get("analysis_mode") or final_analysis_mode)
            final_execution_policy = str(
                skill_trace.get("execution_policy") or final_execution_policy
            )

            if skill_trace.get("hitl_pending"):
                context_window = await chat_service.refresh_session_context_metrics(db, session)
                context_window = chat_service.enrich_context_window(context_window, session.id)
                await db.commit()
                sc = skill_trace.get("skill_confirm") or {}
                skill_confirm_payload = {
                    "session_id": session.id,
                    "options": sc.get("options", []),
                    "reasoning": sc.get("reasoning", ""),
                    "resolved_query": sc.get("resolved_query", ""),
                    "confidence": sc.get("confidence", 0),
                }
                return (
                    "",
                    session.id,
                    memory_profile,
                    context_window,
                    None,
                    skill_confirm_payload,
                    None,
                )

            reply_prepared = False
            if skill_reply_text is not None:
                reply_text = await chat_service._prepare_reply_for_user(skill_reply_text, user_id=user_id, db=db)
                reply_prepared = True
                chat_service.logger.info(
                    "[chat-skill] sync executed: session=%s skill=%s mode=%s",
                    session.id,
                    skill_trace.get("selected_skill"),
                    "skill",
                )
                chat_service.log_reply_completed(
                    mode="skill",
                    session_id=session.id,
                    user_id=user_id,
                    selected_skill_family=skill_trace.get("selected_skill_family"),
                    selected_skill=skill_trace.get("selected_skill"),
                    skill_name=skill_trace.get("skill_name"),
                    analysis_mode=skill_trace.get("analysis_mode"),
                    execution_policy=skill_trace.get("execution_policy"),
                )
            else:
                llm = chat_service._get_llm()
                lc_messages = await chat_service._build_fallback_chat_messages(
                    db,
                    session,
                    memory_system_prompt=memory_system_prompt,
                )
                try:
                    response = await llm.ainvoke(lc_messages)
                except Exception as exc:
                    if not chat_service._is_context_overflow_error(exc):
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
                reply_text = response.content
                final_selected_skill = "fallback"
                final_analysis_mode = "general_chat"
                chat_service.log_reply_completed(
                    mode="fallback",
                    session_id=session.id,
                    user_id=user_id,
                    selected_skill_family="fallback",
                    selected_skill="fallback",
                    analysis_mode="general_chat",
                    execution_policy="agentic",
                )

            # ── Phase 3 LTM：解析 LLM 回复中的显式 profile update action ──
            if settings.enable_memory and not reply_prepared:
                reply_text = await chat_service._prepare_reply_for_user(reply_text, user_id=user_id, db=db)

            chat_service._record_route_runtime_with_log(
                session_id=session.id,
                user_message=user_message,
                route_trace=turn_trace,
                reply_text=reply_text,
            )

            route_summary = chat_service._build_route_summary(turn_trace)
            plan_artifact, skill_artifact, verification_artifact, allowed_claim_level = chat_service._trace_plan_artifacts(turn_trace)

            # 保存 assistant 消息（FIX-8: persist user-facing route summary）
            ai_msg = chat_service.Message(
                session_id=session.id,
                role="assistant",
                content=reply_text,
                token_count=chat_service.count_message_tokens("assistant", reply_text)[0],
                route_summary_json=chat_service._persistable_route_summary(route_summary),
                plan_artifact_json=plan_artifact,
                skill_artifact_json=skill_artifact,
                verification_json=verification_artifact,
                allowed_claim_level=allowed_claim_level,
            )
            db.add(ai_msg)

            # 更新会话统计
            session.turn_count = (session.turn_count or 0) + 1
            session.updated_at = chat_service.datetime.utcnow()
            await db.flush()
            await chat_service._apply_route_entities_to_stm_with_log(
                db=db,
                session=session,
                user_message=user_message,
                route_trace=turn_trace,
            )
            chat_service.logger.info(
                "[STM-chat] 旧异步 STM 链路已停用: session=%s user_msg=%s assistant_msg=%s",
                session.id,
                int(user_msg.id),
                int(ai_msg.id),
            )
            context_window = await chat_service.refresh_session_context_metrics(db, session)
            context_window = chat_service.enrich_context_window(context_window, session.id)
            await db.commit()

            chat_service.logger.info(
                f"[chat] session={session.id} turn={session.turn_count} "
                f"user_len={len(user_message)} reply_len={len(reply_text)}"
            )
            print(
                f"[chat] session={session.id[:8]} turn={session.turn_count} "
                f"user={len(user_message)}字 reply={len(reply_text)}字"
            )

            # Phase 3 LTM：非阻塞触发 LTM 更新（asyncio.create_task 后台执行）
            if settings.enable_memory and user_id:
                with chat_service.trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={"memory_enabled": True, "session_id": session.id, "turn_index": session.turn_count},
                ):
                    asyncio.create_task(
                        chat_service.maybe_update_ltm_from_chat(session.id, user_id, session.turn_count)
                    )
                    chat_service.log_memory_enqueue(
                        session_id=session.id,
                        user_id=user_id,
                        queued=True,
                        turn_index=session.turn_count,
                    )
            else:
                with chat_service.trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={
                        "memory_enabled": bool(settings.enable_memory),
                        "session_id": session.id,
                        "turn_index": session.turn_count,
                        "enqueue_skipped_reason": "memory_disabled" if not settings.enable_memory else "missing_user_id",
                    },
                ):
                    chat_service.log_memory_enqueue(
                        session_id=session.id,
                        user_id=user_id,
                        queued=False,
                        turn_index=session.turn_count,
                        enqueue_skipped_reason="memory_disabled" if not settings.enable_memory else "missing_user_id",
                    )

            return (
                reply_text,
                session.id,
                memory_profile,
                context_window,
                route_summary,
                None,
                {
                    "plan_artifact": plan_artifact,
                    "skill_artifact": skill_artifact,
                    "verification": verification_artifact,
                    "allowed_claim_level": allowed_claim_level,
                },
            )
        except Exception:
            final_status = "error"
            raise
        finally:
            chat_service.log_trace_finished(
                status=final_status,
                duration_ms=round((time.perf_counter() - trace_started) * 1000, 2),
                metrics=chat_service._trace_root_metrics(turn_trace),
                refs=chat_service._trace_root_refs(turn_trace),
                **chat_service._trace_root_payload(
                    final_status=final_status,
                    selected_skill_family=final_selected_skill_family,
                    selected_skill=final_selected_skill,
                    skill_name=final_skill_name,
                    analysis_mode=final_analysis_mode,
                    execution_policy=final_execution_policy,
                    skill_trace=turn_trace,
                ),
            )
