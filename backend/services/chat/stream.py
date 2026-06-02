import asyncio
import json
import time
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


async def stream_chat_single_turn(
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: Optional[str] = None,
    sop_skill_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    流式对话生成器：逐 token yield 内容，供 WebSocket 路由使用。

    协议（与前端 useChat.ts 对应）：
    - 正常 token：直接 yield 文本片段
    - 会话 ID 通知：yield JSON {"type": "session_id", "session_id": "..."}
    - 完成信号：yield JSON {"type": "done", "session_id": "..."}
    - 错误：yield JSON {"type": "error", "message": "..."}
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
        # 注入用户原始消息，供会话报告生成器填写"用户提问"列
        user_message=user_message,
    ):
        chat_service.log_trace_started(user_query_summary=chat_service._trace_query_summary(user_message))
        try:
            normalized_sop_skill_id = None
            if settings.enable_chat_skills:
                normalized_sop_skill_id = chat_service.validate_requested_sop_skill_id(sop_skill_id)

            # Phase 3：流式模式同样支持用户直接发送 JSON action
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

            if not session.title:
                session.title = user_message[:30]
                await db.flush()

            # 通知前端会话 ID（新建会话时前端需要更新 currentSessionId）
            yield json.dumps({"type": "session_id", "session_id": session.id}, ensure_ascii=False)

            memory_profile, memory_system_prompt = await chat_service._prepare_chat_preflight_inputs(
                db,
                session,
                user_id=user_id,
                user_message=user_message,
            )
            preflight_decision = None
            if settings.enable_stm and settings.stm_summary_preflight_enabled:
                preflight_context_window = await chat_service.refresh_session_context_metrics(db, session)
                preflight_decision = chat_service.should_run_preflight_summary_compaction(
                    session,
                    user_message,
                    system_prompt_text=chat_service._CHAT_SYSTEM_PROMPT,
                    memory_prompt_text=memory_system_prompt,
                )
                if preflight_decision.should_compact:
                    yield json.dumps(
                        {
                            "type": "task_status_running",
                            "session_id": session.id,
                            "task_kind": "pre_compaction",
                            "context_window": chat_service._context_window_to_payload(preflight_context_window),
                        },
                        ensure_ascii=False,
                    )

                preflight_result = await chat_service.maybe_run_preflight_summary_compaction(
                    db=db,
                    session=session,
                    pending_user_message=user_message,
                    system_prompt_text=chat_service._CHAT_SYSTEM_PROMPT,
                    memory_prompt_text=memory_system_prompt,
                    exclude_message_ids={int(user_msg.id)},
                    trigger="preflight_budget_stream_chat",
                )
                await db.refresh(session)
                if preflight_decision.should_compact:
                    refreshed_preflight_window = await chat_service.refresh_session_context_metrics(db, session)
                    yield json.dumps(
                        {
                            "type": "task_status_done" if preflight_result.compacted else "task_status_failed",
                            "session_id": session.id,
                            "task_kind": "pre_compaction",
                            "context_window": chat_service._context_window_to_payload(refreshed_preflight_window),
                            **(
                                {"message": preflight_result.reason}
                                if not preflight_result.compacted
                                else {}
                            ),
                        },
                        ensure_ascii=False,
                    )

            skill_reply_text, _, skill_trace, memory_system_prompt = await chat_service._run_skill_chat_if_enabled(
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
                yield json.dumps(
                    {
                        "type": "skill_confirm",
                        "session_id": session.id,
                        "options": sc.get("options", []),
                        "reasoning": sc.get("reasoning", ""),
                        "resolved_query": sc.get("resolved_query", ""),
                        "confidence": sc.get("confidence", 0),
                    },
                    ensure_ascii=False,
                )
                yield json.dumps(
                    {
                        "type": "done",
                        "session_id": session.id,
                        "awaiting_skill_confirm": True,
                        "running_summary": session.running_summary or "",
                        "running_summary_mode": session.running_summary_mode or "",
                        "context_window": chat_service._context_window_to_payload(context_window),
                    },
                    ensure_ascii=False,
                )
                return

            if skill_reply_text is not None:
                skill_reply_text = await chat_service._prepare_reply_for_user(skill_reply_text, user_id=user_id, db=db)
                chat_service.logger.info(
                    "[chat-skill] stream executed: session=%s skill=%s mode=%s",
                    session.id,
                    skill_trace.get("selected_skill"),
                    "skill-stream",
                )
                chat_service.log_reply_completed(
                    mode="skill-stream",
                    session_id=session.id,
                    user_id=user_id,
                    selected_skill_family=skill_trace.get("selected_skill_family"),
                    selected_skill=skill_trace.get("selected_skill"),
                    skill_name=skill_trace.get("skill_name"),
                    analysis_mode=skill_trace.get("analysis_mode"),
                    execution_policy=skill_trace.get("execution_policy"),
                )
                if settings.expose_plan_preview_to_user:
                    executor_events = []
                    executor_payload = skill_trace.get("executor") if isinstance(skill_trace.get("executor"), dict) else {}
                    if isinstance(executor_payload, dict):
                        executor_events = list(executor_payload.get("step_status_events") or [])
                    for event in executor_events:
                        if not isinstance(event, dict):
                            continue
                        frame_type = event.get("type")
                        if frame_type == "plan_preview":
                            yield json.dumps(
                                {
                                    "type": "plan_preview",
                                    "session_id": session.id,
                                    "plan_id": event.get("plan_id") or "",
                                    "items": event.get("items") or [],
                                },
                                ensure_ascii=False,
                            )
                        elif frame_type == "step_status":
                            yield json.dumps(
                                {
                                    "type": "step_status",
                                    "session_id": session.id,
                                    "plan_id": event.get("plan_id") or "",
                                    "step_id": event.get("step_id") or "",
                                    "tool_name": event.get("tool_name") or "",
                                    "status": event.get("status") or "",
                                },
                                ensure_ascii=False,
                            )
                        elif frame_type == "verification_summary":
                            verification = event.get("verification") if isinstance(event.get("verification"), dict) else {}
                            yield json.dumps(
                                {
                                    "type": "verification_summary",
                                    "session_id": session.id,
                                    "plan_id": event.get("plan_id") or "",
                                    "status": verification.get("status") or "",
                                    "evidence_score": verification.get("evidence_score") or 0,
                                    "allowed_claim_level": verification.get("allowed_claim_level") or "",
                                    "missing_dimensions": verification.get("missing_dimensions") or [],
                                },
                                ensure_ascii=False,
                            )
                for chunk in chat_service._chunk_text(skill_reply_text):
                    yield chunk

                chat_service._record_route_runtime_with_log(
                    session_id=session.id,
                    user_message=user_message,
                    route_trace=turn_trace,
                    reply_text=skill_reply_text,
                )
                _skill_route_summary = chat_service._build_route_summary(turn_trace)
                plan_artifact, skill_artifact, verification_artifact, allowed_claim_level = chat_service._trace_plan_artifacts(turn_trace)
                ai_msg = chat_service.Message(
                    session_id=session.id,
                    role="assistant",
                    content=skill_reply_text,
                    token_count=chat_service.count_message_tokens("assistant", skill_reply_text)[0],
                    route_summary_json=chat_service._persistable_route_summary(_skill_route_summary),
                    plan_artifact_json=plan_artifact,
                    skill_artifact_json=skill_artifact,
                    verification_json=verification_artifact,
                    allowed_claim_level=allowed_claim_level,
                )
                db.add(ai_msg)
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

                if settings.enable_memory and user_id:
                    with chat_service.trace_span(
                        "memory_write_enqueue",
                        stage="memory",
                        data={"memory_enabled": True, "session_id": session.id, "turn_index": session.turn_count},
                    ):
                        asyncio.create_task(chat_service.maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))
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

                yield json.dumps(
                    {
                        "type": "context_update",
                        "session_id": session.id,
                        "context_window": chat_service._context_window_to_payload(context_window),
                    },
                    ensure_ascii=False,
                )
                if _skill_route_summary:
                    yield json.dumps(
                        {
                            "type": "trace_summary",
                            "session_id": session.id,
                            "route_summary": _skill_route_summary,
                        },
                        ensure_ascii=False,
                    )

                yield json.dumps({
                    "type": "done",
                    "session_id": session.id,
                    "running_summary": session.running_summary or "",
                    "running_summary_mode": session.running_summary_mode or "",
                    "context_window": chat_service._context_window_to_payload(context_window),
                }, ensure_ascii=False)
                return

            # Phase 3：对话流式模式也注入 LTM 用户画像
            # 流式调用 LLM
            llm = chat_service._get_llm()
            reply_chunks = []

            print(f"[chat-stream] session={session.id[:8]} 开始流式输出...")
            chat_service.logger.info(f"[chat-stream] 开始流式输出: session={session.id}")

            stream_attempted_fallback = False
            while True:
                lc_messages = await chat_service._build_fallback_chat_messages(
                    db,
                    session,
                    memory_system_prompt=memory_system_prompt,
                )
                try:
                    async for chunk in llm.astream(lc_messages):
                        token = chunk.content if hasattr(chunk, "content") else str(chunk)
                        if token:
                            reply_chunks.append(token)
                            yield token
                    break
                except Exception as exc:
                    # 流式一旦已经向客户端发送过内容，就不能安全重试，只能原样抛出。
                    if reply_chunks or stream_attempted_fallback or not chat_service._is_context_overflow_error(exc):
                        raise
                    recovered = await chat_service._force_overflow_recovery_compaction(
                        db,
                        session,
                        user_message=user_message,
                        exc=exc,
                    )
                    if not recovered:
                        raise
                    stream_attempted_fallback = True
                    reply_chunks = []
                    continue

            reply_text = "".join(reply_chunks)
            final_selected_skill = "fallback"
            final_analysis_mode = "general_chat"
            chat_service.log_reply_completed(
                mode="fallback-stream",
                session_id=session.id,
                user_id=user_id,
                selected_skill_family="fallback",
                selected_skill="fallback",
                analysis_mode="general_chat",
                execution_policy="agentic",
            )

            # Phase 3: 流式模式也要解析 LLM 回复中的 <action> 并更新画像
            if settings.enable_memory and user_id:
                reply_text = await chat_service._prepare_reply_for_user(reply_text, user_id=user_id, db=db)

            chat_service._record_route_runtime_with_log(
                session_id=session.id,
                user_message=user_message,
                route_trace=turn_trace,
                reply_text=reply_text,
            )

            route_summary = chat_service._build_route_summary(turn_trace)

            # 保存 assistant 消息（FIX-8: persist user-facing route summary）
            ai_msg = chat_service.Message(
                session_id=session.id,
                role="assistant",
                content=reply_text,
                token_count=chat_service.count_message_tokens("assistant", reply_text)[0],
                route_summary_json=chat_service._persistable_route_summary(route_summary),
            )
            db.add(ai_msg)
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

            print(
                f"[chat-stream] 流式完成: session={session.id[:8]} "
                f"turn={session.turn_count} reply={len(reply_text)}字"
            )
            chat_service.logger.info(
                f"[chat-stream] 完成: session={session.id}, "
                f"turn={session.turn_count}, reply_len={len(reply_text)}"
            )

            context_window = await chat_service.refresh_session_context_metrics(db, session)
            context_window = chat_service.enrich_context_window(context_window, session.id)
            await db.commit()

            if settings.enable_memory and user_id:
                with chat_service.trace_span(
                    "memory_write_enqueue",
                    stage="memory",
                    data={"memory_enabled": True, "session_id": session.id, "turn_index": session.turn_count},
                ):
                    asyncio.create_task(chat_service.maybe_update_ltm_from_chat(session.id, user_id, session.turn_count))
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

            yield json.dumps(
                {
                    "type": "context_update",
                    "session_id": session.id,
                    "context_window": chat_service._context_window_to_payload(context_window),
                },
                ensure_ascii=False,
            )
            if route_summary:
                yield json.dumps(
                    {
                        "type": "trace_summary",
                        "session_id": session.id,
                        "route_summary": route_summary,
                        },
                        ensure_ascii=False,
                    )

            yield json.dumps({
                "type": "done",
                "session_id": session.id,
                "running_summary": session.running_summary or "",
                "running_summary_mode": session.running_summary_mode or "",
                "context_window": chat_service._context_window_to_payload(context_window),
            }, ensure_ascii=False)

        except Exception as exc:
            final_status = "error"
            chat_service.logger.error(f"[chat-stream] 流式输出失败: {exc}", exc_info=True)
            print(f"[chat-stream] 流式输出失败: {exc}")
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
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
