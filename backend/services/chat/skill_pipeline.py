import asyncio
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Session
from backend.services.chat.constants import InvalidSopSkillError
from backend.services.working_state import get_working_state, upsert_active_entity


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


def _executor_qualifies_for_evidence_retry(executor_trace: dict | None) -> bool:
    if not executor_trace:
        return False
    if executor_trace.get("evidence_ok"):
        return False
    if str(executor_trace.get("reply_mode") or "") != "evidence-missing":
        return False
    if str(executor_trace.get("failure_code") or "") == "skill_disabled":
        return False
    return True


def _resolve_sop_skill_id(route_trace: dict[str, Any], decision: Any) -> str:
    """Concrete SOP skill id (e.g. stock-first-pass), not skill family (financial-sop)."""
    skill_name = str((route_trace or {}).get("skill_name") or "").strip()
    if skill_name:
        return skill_name
    return str(getattr(decision, "skill_id", None) or "").strip()


async def _apply_skill_query_rewrite(
    route: Any,
    route_context: str,
    *,
    error_feedback: str = "",
) -> None:
    chat_service = _chat_service_facade()
    try:
        rewritten = await chat_service.rewrite_query_for_skill(
            route,
            conversation_context=route_context,
            error_feedback=error_feedback or "",
        )
        if rewritten is None:
            return
        args = dict(route.arguments or {})
        args["effective_query"] = rewritten.query
        args["detected_entities"] = [{"value": e.value, "type": e.type} for e in rewritten.entities]
        if rewritten.tool_hints:
            args["tool_hints"] = rewritten.tool_hints
        route.arguments = args
        chat_service.logger.info(
            "[chat-skill] query rewrite%s: entities=%d",
            " (retry)" if error_feedback else "",
            len(rewritten.entities),
        )
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] query rewrite failed (non-fatal): %s", exc)


async def summarize_sop_reply(
    *,
    effective_query: str,
    tool_data: dict[str, Any],
    answer_policy_context: str,
    ltm_full: str,
    skill_id: str,
    session_id: str,
    user_id: str,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    chat_service = _chat_service_facade()
    sections = chat_service._load_skill_doc_sections(skill_id)
    if settings.enable_synthesis_v2:
        prompt = chat_service.build_sop_synthesis_prompt(
            effective_query=effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_full=ltm_full,
            skill_id=skill_id,
            output_template=sections.get("output_template") or "",
            fallbacks=sections.get("fallbacks") or "",
            decision_rules=sections.get("decision_rules") or "",
        )
    else:
        answer_policy_block = answer_policy_context or "【回答策略上下文】\n无"
        prompt = (
            "[角色]\n你是A股投研助手总结器，请依据证据回答。\n\n"
            "[SKILL 输出合同]\n"
            f"Output Template:\n{sections.get('output_template') or '无'}\n\n"
            f"Fallbacks:\n{sections.get('fallbacks') or '无'}\n\n"
            f"Decision Rules:\n{sections.get('decision_rules') or '无'}\n\n"
            f"[证据包 tool_data]\n{chat_service._serialize_prompt_payload(tool_data)}\n\n"
            f"[effective_query]\n{effective_query}\n\n"
            f"{answer_policy_block}\n\n"
            f"[全量 LTM]\n{ltm_full or '无'}\n\n"
            "[禁止项]\n"
            "- 不得编造证据包中不存在的数值\n"
            "- 若证据不足，按 Fallbacks 保守回答\n"
        )
    llm = chat_service._get_llm()
    chat_service.log_model_stage(
        stage="summarize",
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        execution_path="sop",
        session_id=session_id,
        user_id=user_id,
    )
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是金融问答总结器。"),
                HumanMessage(content=prompt),
            ]
        )
        reply = chat_service._extract_model_text(response) or "我已完成这次分析，但当前暂无可复述内容。"
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] summarize_sop_reply failed: %s", exc, exc_info=True)
        chat_service.log_degrade_transition(from_stage="summarize", reason=f"sop_summarize_failed: {exc}")
        reply = "我已完成工具执行，但总结阶段异常。你可以继续追问我具体维度。"

    chat_service.log_reply_completed(
        mode="sop",
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="financial-sop",
        selected_skill="financial-sop",
        skill_name=skill_id,
        used_tools=bool((tool_data or {}).get("results") or (tool_data or {}).get("executor_trace")),
    )
    return reply


async def summarize_tushare_reply(
    *,
    effective_query: str,
    tool_data: dict[str, Any],
    answer_policy_context: str,
    ltm_full: str,
    session_id: str,
    user_id: str,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    chat_service = _chat_service_facade()
    if settings.enable_synthesis_v2:
        prompt = chat_service.build_tushare_synthesis_prompt(
            effective_query=effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_full=ltm_full,
        )
    else:
        answer_policy_block = answer_policy_context or "【回答策略上下文】\n无"
        prompt = (
            "[角色]\n你是A股投研助手总结器，请依据证据回答。\n\n"
            f"[证据包 tool_data]\n{chat_service._serialize_prompt_payload(tool_data)}\n\n"
            f"[effective_query]\n{effective_query}\n\n"
            f"{answer_policy_block}\n\n"
            f"[全量 LTM]\n{ltm_full or '无'}\n\n"
            "[禁止项]\n"
            "- 不得编造证据包中不存在的数值\n"
        )
    llm = chat_service._get_llm()
    chat_service.log_model_stage(
        stage="summarize",
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        execution_path="tushare",
        session_id=session_id,
        user_id=user_id,
    )
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是金融问答总结器。"),
                HumanMessage(content=prompt),
            ]
        )
        reply = chat_service._extract_model_text(response) or "已完成实时数据检索，但暂无可复述内容。"
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] summarize_tushare_reply failed: %s", exc, exc_info=True)
        chat_service.log_degrade_transition(from_stage="summarize", reason=f"tushare_summarize_failed: {exc}")
        reply = "我已执行实时数据工具，但总结阶段异常。你可以继续追问具体指标。"

    chat_service.log_reply_completed(
        mode="tushare",
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="tushare-data",
        selected_skill="tushare-data",
        used_tools=bool((tool_data or {}).get("results")),
    )
    return reply


async def summarize_fallback_reply(
    *,
    effective_query: str,
    answer_policy_context: str,
    ltm_full: str,
    session_id: str,
    user_id: str,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    chat_service = _chat_service_facade()
    if settings.enable_synthesis_v2:
        prompt = chat_service.build_fallback_synthesis_prompt(
            effective_query=effective_query,
            answer_policy_context=answer_policy_context,
            ltm_full=ltm_full,
        )
    else:
        answer_policy_block = answer_policy_context or "【回答策略上下文】\n无"
        prompt = (
            "[角色]\n你是通用问答总结器。\n\n"
            f"[effective_query]\n{effective_query}\n\n"
            f"{answer_policy_block}\n\n"
            f"[LTM 全量]\n{ltm_full or '无'}\n\n"
            "[要求]\n结合上下文给出直接回答，尽量简洁。"
        )
    llm = chat_service._get_llm()
    chat_service.log_model_stage(
        stage="summarize",
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        execution_path="fallback",
        session_id=session_id,
        user_id=user_id,
    )
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是对话助手。"),
                HumanMessage(content=prompt),
            ]
        )
        reply = chat_service._extract_model_text(response) or "我理解了你的问题，但暂时无法给出完整回答。"
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] summarize_fallback_reply failed: %s", exc, exc_info=True)
        chat_service.log_degrade_transition(from_stage="summarize", reason=f"fallback_summarize_failed: {exc}")
        reply = "我暂时没能完成回答生成，请换一种问法再试。"

    chat_service.log_reply_completed(
        mode="fallback",
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="fallback",
        selected_skill="fallback",
        used_tools=False,
    )
    return reply


async def _run_post_rewrite_extractors_if_enabled(
    *,
    db: AsyncSession,
    session: Session,
    route: str,
    skill_id: str | None,
    user_message: str,
    resolver_hint: dict[str, Any] | None,
    rewrite_result: Any,
    message_id: int | None,
) -> None:
    if not settings.enable_post_rewrite_extractors:
        return
    chat_service = _chat_service_facade()
    ctx = chat_service.RewriteContextPacket(
        route=route,  # type: ignore[arg-type]
        skill_id=skill_id,
        user_query=user_message,
        active_entity=resolver_hint,
        candidate_entities=list((resolver_hint or {}).get("candidate_entities") or []),
        resolution_status=str((resolver_hint or {}).get("resolution_status") or "no_entity"),
        working_state_prev=get_working_state(session),
    )
    try:
        constraints_result, pref_result = await asyncio.gather(
            chat_service.extract_constraints(ctx, rewrite_result),
            chat_service.extract_reply_preference(ctx, rewrite_result),
        )
        if constraints_result.operation != "no_update":
            from backend.services.working_state import upsert_constraints

            await upsert_constraints(
                db,
                session,
                constraints_result.constraints,
                message_id=message_id,
                confidence=constraints_result.confidence,
            )
        if pref_result.operation != "no_update":
            from backend.services.working_state import upsert_reply_preference

            await upsert_reply_preference(
                db,
                session,
                pref_result.reply_preference_hint,
                message_id=message_id,
                confidence=pref_result.confidence,
            )
    except Exception as exc:
        chat_service.logger.warning("[chat-skill] post rewrite extractors failed (non-fatal): %s", exc, exc_info=True)


def _trace_plan_artifacts(trace: dict[str, Any]) -> tuple[dict | None, dict | None, dict | None, str | None]:
    executor = trace.get("executor") if isinstance(trace.get("executor"), dict) else {}
    plan_artifact = None
    if executor.get("plan_id") or executor.get("plan_preview"):
        plan_artifact = {
            "plan_id": executor.get("plan_id"),
            "discovery_trace_id": executor.get("discovery_trace_id"),
            "plan_preview": executor.get("plan_preview") or [],
        }
    skill_artifact = None
    if executor.get("skill_loader_artifacts"):
        skill_artifact = {
            "skill_loader_artifacts": executor.get("skill_loader_artifacts") or [],
            "skill_version": executor.get("skill_version") or "",
            "spec_hash": executor.get("spec_hash") or "",
            "registry_version": executor.get("registry_version") or "",
        }
    verification = executor.get("verification") if isinstance(executor.get("verification"), dict) else None
    allowed = None
    if verification:
        allowed = str(verification.get("allowed_claim_level") or "") or None
    allowed = allowed or str(executor.get("allowed_claim_level") or executor.get("evidence_allowed_claim_level") or "") or None
    return plan_artifact, skill_artifact, verification, allowed


async def _run_skill_chat_if_enabled(
    *,
    db: AsyncSession,
    session: Session,
    user_id: str,
    user_message: str,
    sop_skill_id: str | None = None,
    exclude_message_id: int | None = None,
    preloaded_memory_profile: dict | None = None,
    preloaded_memory_system_prompt: str | None = None,
) -> tuple[str | None, dict, dict, str]:
    chat_service = _chat_service_facade()
    if not settings.enable_chat_skills:
        return None, dict(preloaded_memory_profile or {}), {}, preloaded_memory_system_prompt or ""

    chat_service._ensure_skill_runtime_ready()
    if preloaded_memory_profile is None or preloaded_memory_system_prompt is None:
        memory_profile, memory_system_prompt = await chat_service._load_memory_context_for_chat(db, user_id, user_message)
    else:
        memory_profile = dict(preloaded_memory_profile)
        memory_system_prompt = preloaded_memory_system_prompt
    route_ltm_summary = chat_service._profile_to_route_summary(memory_profile)
    _, route_context_slice_text, answer_policy_context = chat_service._resolve_session_summary_contexts(session)
    route_context = await chat_service._build_skill_route_context(
        db,
        session,
        exclude_message_id=exclude_message_id,
        route_slice_text=route_context_slice_text,
    )
    resolver_hint = None
    if settings.enable_entity_resolver_v2:
        previous_active = get_working_state(session).get("active_entity")
        with chat_service.trace_span("entity_resolution_v2", stage="entity_resolution_v2", data={"enabled": True}):
            entity_v2 = await chat_service.resolve_authoritative_entity(
                user_message,
                allowed_asset_types={"stock", "fund", "sector", "index"},
                previous_active_entity=previous_active if isinstance(previous_active, dict) else None,
                source_message_id=exclude_message_id,
            )
        entity_payload = entity_v2.model_dump() if hasattr(entity_v2, "model_dump") else entity_v2.dict()
        if entity_v2.primary_entity is not None:
            primary = entity_v2.primary_entity
            resolver_hint = {
                "display_name": primary.display_name,
                "asset_type": primary.entity_type,
                "symbol": primary.canonical_id,
                "confidence": entity_v2.confidence,
                "resolver_stage": primary.resolver_path,
                "resolver_source": "entity_resolver_v2",
                "resolution_status": entity_v2.resolution_status,
                "candidate_entities": [item.model_dump() for item in entity_v2.candidate_entities],
            }
            await upsert_active_entity(
                db,
                session,
                {**resolver_hint, "entity_type": primary.entity_type, "canonical_id": primary.canonical_id},
                message_id=exclude_message_id,
                confidence=entity_v2.confidence,
            )
        if entity_v2.need_clarification:
            await upsert_active_entity(
                db,
                session,
                {"resolution_status": entity_v2.resolution_status, "candidate_entities": entity_payload.get("candidate_entities", [])},
                message_id=exclude_message_id,
                confidence=entity_v2.confidence,
            )
            return (
                entity_v2.clarification_question or "我需要先确认一下你说的是哪个标的？",
                memory_profile,
                {
                    "selected_skill_family": "clarification",
                    "selected_skill": "entity-clarification",
                    "skill_name": None,
                    "analysis_mode": "entity_resolution",
                    "execution_policy": "deterministic",
                    "entity_resolution": entity_payload,
                    "executor": {"reply_mode": "clarification", "used_tools": False},
                },
                memory_system_prompt,
            )
    else:
        resolver_hint = await chat_service._resolve_entity_hint_for_route(session, user_message)
    resolver_hint_block = chat_service._resolver_hint_to_prompt_block(resolver_hint)
    if resolver_hint_block:
        route_context = f"{resolver_hint_block}\n\n{route_context}" if route_context else resolver_hint_block
    normalized_sop_skill_id = chat_service.normalize_requested_sop_skill_id(sop_skill_id)
    skipped_llm_router = normalized_sop_skill_id is not None
    route_source = "user_explicit" if skipped_llm_router else "llm"
    with chat_service.trace_span(
        "route",
        stage="route",
        data={
            "user_query_summary": chat_service._trace_query_summary(user_message),
            "profile_summary_used": bool(route_ltm_summary),
            "user_sop_skill_id": normalized_sop_skill_id,
            "skipped_llm_router": skipped_llm_router,
        },
    ):
        if normalized_sop_skill_id is not None:
            decision = chat_service.user_explicit_sop_decision(normalized_sop_skill_id)
            if decision is None:
                raise InvalidSopSkillError(f"无效的 sop_skill_id: {normalized_sop_skill_id}")
        else:
            decision = await chat_service.route_chat_skill(
                user_message,
                conversation_context=route_context,
                profile_summary=route_ltm_summary,
                enable_route_v2=settings.enable_route_v2,
                active_entity=resolver_hint,
            )
    route_trace = chat_service._build_executor_route_trace(decision, user_message)
    if skipped_llm_router:
        route_trace["confidence"] = 1.0
    chat_service.log_model_stage(
        stage="router",
        model=None,
        execution_path="routing",
        session_id=session.id,
        user_id=user_id,
        route_source=route_source,
        skipped_llm_router=skipped_llm_router,
    )
    chat_service.log_router_decision(
        route=decision.route,
        skill_id=decision.skill_id,
        execution_policy=decision.execution_policy,
        session_id=session.id,
        user_id=user_id,
        route_source=route_source,
        route_confidence=1.0 if skipped_llm_router else None,
    )
    chat_service.logger.info(
        "[chat-skill] route=%s skill_id=%s execution_policy=%s selected_skill=%s route_source=%s",
        decision.route,
        decision.skill_id or "",
        decision.execution_policy,
        route_trace.get("selected_skill"),
        route_source,
    )

    if bool(route_trace.get("need_confirm")) and settings.enable_skill_route_hitl:
        options = chat_service._build_skill_confirm_options_from_trace(route_trace)
        payload = {
            "session_id": session.id,
            "user_id": user_id,
            "user_message": user_message,
            "route_context": route_context,
            "route_dict": route_trace,
            "options": options,
            "reasoning": str((route_trace.get("route_stage1") or {}).get("reasoning_brief") or "需要确认是否进入技能链路"),
            "resolved_query": user_message,
            "confidence": float(route_trace.get("confidence") or 0.0),
        }
        chat_service.set_pending_skill_confirm(session.id, payload)
        return (
            "",
            memory_profile,
            {
                **route_trace,
                "hitl_pending": True,
                "skill_confirm": {
                    "options": options,
                    "reasoning": payload["reasoning"],
                    "resolved_query": user_message,
                    "confidence": payload["confidence"],
                },
            },
            memory_system_prompt,
        )

    if decision.route == "sop":
        rewrite_result = await chat_service.rewrite_for_sop(
            decision,
            user_message,
            stm_snapshot=route_context,
            ltm_summary=route_ltm_summary,
            resolver_hint=resolver_hint,
        )
        await chat_service._run_post_rewrite_extractors_if_enabled(
            db=db,
            session=session,
            route="financial-sop",
            skill_id=decision.skill_id,
            user_message=user_message,
            resolver_hint=resolver_hint,
            rewrite_result=rewrite_result,
            message_id=exclude_message_id,
        )

        args = dict(route_trace.get("arguments") or {})
        args["effective_query"] = rewrite_result.effective_query
        args["skill_params"] = dict(rewrite_result.skill_params or {})
        if resolver_hint:
            args["resolved_entity_hint"] = dict(resolver_hint)
            args["inherited_entity"] = str(resolver_hint.get("display_name") or "")
            args["inherited_entity_id"] = str(resolver_hint.get("symbol") or "")
        args["candidate_entities"] = [item.display_name for item in rewrite_result.entities]
        args["entities"] = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in rewrite_result.entities
        ]
        route_trace["arguments"] = args

        _exec_data = {
            "selected_skill": route_trace.get("selected_skill"),
            "skill_name": route_trace.get("skill_name"),
            "analysis_mode": route_trace.get("analysis_mode"),
            "execution_policy": route_trace.get("execution_policy"),
        }
        if settings.enable_sop_v2:
            sop_skill_id = chat_service._resolve_sop_skill_id(route_trace, decision)
            skill_spec = chat_service.get_skill_registry().load_skill_spec(sop_skill_id)
            if not skill_spec:
                raise ValueError(f"SOP v2 缺少 skill_spec.yaml: {sop_skill_id or decision.skill_id}")
            with chat_service.trace_span("executor_v2", stage="executor", data={**_exec_data, "version": "v2"}):
                v2_result = await chat_service.run_sop_v2_pipeline(
                    skill_name=sop_skill_id,
                    skill_spec=skill_spec,
                    user_message=user_message,
                    rewrite_result=rewrite_result,
                    active_entity=resolver_hint,
                    trace_id=session.id,
                    config=settings,
                )
            result_trace = v2_result.tool_data().get("executor_trace") or {}
            tool_data = v2_result.tool_data()
            chat_service.log_tool_plan(
                planner_type="sop_v2",
                analysis_mode=str(route_trace.get("analysis_mode") or "general_chat"),
                planned_tools=list(result_trace.get("planned_tools") or []),
                plan_preview=list(result_trace.get("plan_preview") or []),
                execution_path=str(route_trace.get("execution_policy") or "deterministic"),
                skill_name=sop_skill_id,
                plan_id=result_trace.get("plan_id"),
            )
        else:
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
            result_trace = result.trace
            tool_data = {"executor_trace": result.trace, "route_arguments": args}
        reply = await chat_service.summarize_sop_reply(
            effective_query=rewrite_result.effective_query,
            tool_data={**tool_data, "route_arguments": args},
            answer_policy_context=answer_policy_context,
            ltm_full=memory_system_prompt,
            skill_id=str(decision.skill_id or ""),
            session_id=session.id,
            user_id=user_id,
        )
        trace = dict(route_trace)
        trace["executor"] = result_trace
        return reply, memory_profile, trace, memory_system_prompt

    if decision.route == "tushare":
        use_tushare_v2_pipeline = (
            settings.enable_tushare_v2
            and settings.enable_planner_v2
            and settings.enable_executor_v2
        )
        if use_tushare_v2_pipeline:
            rewrite_ctx = chat_service.RewriteContextPacket(
                route="tushare-data",
                user_query=user_message,
                active_entity=resolver_hint,
                working_state_prev=get_working_state(session),
            )
            rewrite_result = await chat_service.rewrite_for_tushare_v2(rewrite_ctx)
        else:
            rewrite_result = await chat_service.rewrite_for_tushare(
                decision,
                user_message,
                stm_snapshot=route_context,
                ltm_summary=route_ltm_summary,
                resolver_hint=resolver_hint,
            )
        await chat_service._run_post_rewrite_extractors_if_enabled(
            db=db,
            session=session,
            route="tushare-data",
            skill_id=None,
            user_message=user_message,
            resolver_hint=resolver_hint,
            rewrite_result=rewrite_result,
            message_id=exclude_message_id,
        )
        args = dict(route_trace.get("arguments") or {})
        args["effective_query"] = rewrite_result.effective_query
        if resolver_hint:
            args["resolved_entity_hint"] = dict(resolver_hint)
            args["inherited_entity"] = str(resolver_hint.get("display_name") or "")
            args["inherited_entity_id"] = str(resolver_hint.get("symbol") or "")
        args["entities"] = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in rewrite_result.entities
        ]
        if hasattr(rewrite_result, "tool_plan"):
            args["tool_plan"] = [
                item.model_dump() if hasattr(item, "model_dump") else item.dict()
                for item in rewrite_result.tool_plan
            ]
        route_trace["arguments"] = args
        planned_tool_names = [step.tool_name for step in getattr(rewrite_result, "tool_plan", [])]
        chat_service.log_tool_plan(
            planner_type="rewrite_tushare_v2" if use_tushare_v2_pipeline else "rewrite_tushare",
            analysis_mode="general_chat",
            planned_tools=planned_tool_names,
            execution_path="deterministic",
            tool_batch_size=len(planned_tool_names),
        )
        if use_tushare_v2_pipeline:
            with chat_service.trace_span(
                "executor_v2",
                stage="executor",
                data={"selected_skill": "tushare-data", "analysis_mode": "general_chat", "version": "v2"},
            ):
                v2_result = await chat_service.run_tushare_v2_pipeline(
                    rewrite_result=rewrite_result,
                    active_entity=resolver_hint,
                    trace_id=session.id,
                    config=settings,
                )
            tool_data = v2_result.tool_data()
        else:
            with chat_service.trace_span(
                "executor",
                stage="executor",
                data={"selected_skill": "tushare-data", "analysis_mode": "general_chat"},
            ):
                tool_data = await chat_service.execute_tushare_plan(
                    rewrite_result.tool_plan,
                    rewrite_result.entities,
                    session_id=session.id,
                    user_id=user_id,
                    decision=decision,
                    user_message=rewrite_result.effective_query,
                    stm_snapshot=route_context,
                    ltm_summary=route_ltm_summary,
                )
        reply = await chat_service.summarize_tushare_reply(
            effective_query=rewrite_result.effective_query,
            tool_data=tool_data,
            answer_policy_context=answer_policy_context,
            ltm_full=memory_system_prompt,
            session_id=session.id,
            user_id=user_id,
        )
        trace = dict(route_trace)
        trace["executor"] = dict(tool_data.get("executor_trace") or {})
        return reply, memory_profile, trace, memory_system_prompt

    rewrite_result = await chat_service.rewrite_for_fallback(
        user_message,
        stm_snapshot=route_context,
        ltm_summary=route_ltm_summary,
        resolver_hint=resolver_hint,
    )
    await chat_service._run_post_rewrite_extractors_if_enabled(
        db=db,
        session=session,
        route="fallback",
        skill_id=None,
        user_message=user_message,
        resolver_hint=resolver_hint,
        rewrite_result=rewrite_result,
        message_id=exclude_message_id,
    )
    args = dict(route_trace.get("arguments") or {})
    args["effective_query"] = rewrite_result.effective_query
    if resolver_hint:
        args["resolved_entity_hint"] = dict(resolver_hint)
        args["inherited_entity"] = str(resolver_hint.get("display_name") or "")
        args["inherited_entity_id"] = str(resolver_hint.get("symbol") or "")
    route_trace["arguments"] = args
    reply = await chat_service.summarize_fallback_reply(
        effective_query=rewrite_result.effective_query,
        answer_policy_context=answer_policy_context,
        ltm_full=memory_system_prompt,
        session_id=session.id,
        user_id=user_id,
    )
    route_trace["executor"] = {
        "selected_skill_family": "fallback",
        "selected_skill": "fallback",
        "skill_name": None,
        "analysis_mode": "general_chat",
        "execution_policy": "deterministic",
        "reply_mode": "fallback",
        "used_tools": False,
        "planned_tools": [],
        "prefetched_tool_names": [],
        "evidence_ok": False,
        "missing_evidence_reasons": [],
        "failure_code": "",
    }
    return reply, memory_profile, route_trace, memory_system_prompt
