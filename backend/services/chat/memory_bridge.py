import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Message, Session
from backend.services.chat.constants import _normalize_profile_action


_MIN_LTM_INTERVAL_SEC = int(os.getenv("MIN_LTM_INTERVAL", "300"))  # 最小间隔 300s
_LTM_TRIGGER_MSG_COUNT = 5  # 未处理 user 消息数阈值


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


def _build_memory_system_prompt(profile: dict, semantic_memories: list) -> str:
    """
    将 memory_context 构建为对话模式的 system prompt 注入段。
    与 summary_agent._build_memory_context_prompt 格式保持一致。
    """
    if not profile and not semantic_memories:
        return ""

    has_profile = any(
        v is not None and v != [] and v != {}
        for v in profile.values()
    )
    if not has_profile and not semantic_memories:
        return ""

    profile_lines = []

    risk_map = {
        "conservative": "保守", "moderate": "稳健", "balanced": "平衡",
        "aggressive": "进取", "speculative": "激进",
    }
    horizon_map = {
        "ultra_short": "超短线", "short": "短线", "swing": "波段", "long": "中长线",
    }

    rl = profile.get("risk_level")
    if rl:
        profile_lines.append(f"风险偏好：{risk_map.get(rl, rl)}")

    hz = profile.get("investment_horizon")
    if hz:
        profile_lines.append(f"持有周期：{horizon_map.get(hz, hz)}")

    ret_min = profile.get("expected_return_min")
    ret_max = profile.get("expected_return_max")
    if ret_min is not None:
        if ret_max is not None:
            profile_lines.append(f"期望收益：{ret_min}%~{ret_max}%")
        else:
            profile_lines.append(f"期望收益：≥{ret_min}%")

    sectors = profile.get("sectors", [])
    if sectors:
        profile_lines.append(f"关注板块：{', '.join(sectors[:5])}")

    constraints = profile.get("constraints", [])
    if constraints:
        profile_lines.append(f"约束：{', '.join(constraints[:3])}")

    if not profile_lines and not semantic_memories:
        return ""

    parts = ["【用户投资画像（参考，不覆盖实时数据）】"]
    parts.extend(profile_lines)

    if semantic_memories:
        semantic_texts = [m.get("text", "") for m in semantic_memories if m.get("text")]
        if semantic_texts:
            parts.append(f"历史偏好线索：{'; '.join(semantic_texts[:2])}")

    return "\n".join(parts)


async def maybe_update_ltm_from_chat(
    session_id: str,
    user_id: str,
    turn_count: int,
) -> None:
    """
    对话后台 LTM 更新函数（非阻塞，由 asyncio.create_task 调用）。

    触发条件（满足任一）：
    1. 未处理的 user 消息 >= _LTM_TRIGGER_MSG_COUNT，且距上次写入超过 MIN_LTM_INTERVAL
    2. turn_count 是 STM 压缩轮次（turn_count % 10 == 0），摘要质量最高

    P3 重构逻辑：
    1. 入队前先调用 profile_extractor 做画像要素抽取（A 类结构化 + B 类回复风格事实）
    2. 只在 has_profile_signal=True 时才入队 Mem0
    3. 对抽取到的结构化字段，直接更新 user_invest_profiles（快速生效）
    4. 入队 Mem0 的为 build_fact_messages 生成的高维度事实字符串（非原始对话），metadata 含 extracted_fields / mem0_infer=False
    """
    chat_service = _chat_service_facade()
    if not settings.enable_memory:
        return
    if not bool(settings.enable_chat_ltm_extract):
        chat_service.logger.debug(
            "[LTM-chat] skip: ENABLE_CHAT_LTM_EXTRACT=false session=%s turn=%s",
            session_id,
            turn_count,
        )
        return

    try:
        from backend.services.profile_extractor import extract_profile_updates
        from backend.db.database import AsyncSessionFactory

        MemoryService = chat_service._get_memory_service_cls()
        async with AsyncSessionFactory() as db:
            # 查找未处理的 user/assistant 消息
            result = await db.execute(
                select(Message)
                .where(
                    Message.session_id == session_id,
                    Message.used_for_ltm == False,  # noqa: E712
                    Message.role.in_(["user", "assistant"]),
                )
                .order_by(Message.created_at)
                .limit(10)
            )
            pending_msgs = list(result.scalars().all())

            user_msgs_count = sum(1 for m in pending_msgs if m.role == "user")

            # 触发条件判断
            trigger_by_count = user_msgs_count >= _LTM_TRIGGER_MSG_COUNT
            trigger_by_compress = (turn_count > 0 and turn_count % 10 == 0)

            if not trigger_by_count and not trigger_by_compress:
                chat_service.logger.debug(
                    f"[LTM-chat] 未触发更新: user_msgs={user_msgs_count}, "
                    f"turn_count={turn_count}"
                )
                return

            # 检查 MIN_LTM_INTERVAL（仅对 trigger_by_count 路径生效）
            if trigger_by_count and not trigger_by_compress:
                from sqlalchemy import text
                last_ltm = await db.execute(
                    text(
                        "SELECT MAX(created_at) FROM ltm_write_tasks "
                        "WHERE user_id = :uid AND task_type = 'add_conversation'"
                    ),
                    {"uid": user_id},
                )
                last_ltm_time = last_ltm.scalar()
                if last_ltm_time:
                    try:
                        if isinstance(last_ltm_time, str):
                            from datetime import datetime as _dt
                            last_ltm_dt = _dt.fromisoformat(last_ltm_time)
                        else:
                            last_ltm_dt = last_ltm_time
                        elapsed = (datetime.utcnow() - last_ltm_dt).total_seconds()
                        if elapsed < _MIN_LTM_INTERVAL_SEC:
                            chat_service.logger.debug(
                                f"[LTM-chat] 距上次写入仅 {elapsed:.0f}s < {_MIN_LTM_INTERVAL_SEC}s，跳过"
                            )
                            return
                    except Exception:
                        pass  # 时间解析失败，继续触发

            # ── 获取 running_summary ─────────────────────────────
            session_result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session_obj = session_result.scalar_one_or_none()
            running_summary = (session_obj.running_summary or "") if session_obj else ""

            # ── P3 新增：画像要素抽取 ────────────────────────────
            messages_for_extract = [
                {"role": m.role, "content": m.content[:800]}
                for m in pending_msgs
            ]
            extraction = await extract_profile_updates(
                messages=messages_for_extract,
                running_summary=running_summary,
            )

            # ── 结构化字段直写 DB（快速生效） ────────────────────
            if extraction.get("has_profile_signal") and extraction.get("updates"):
                for update in extraction["updates"]:
                    field = update.get("field")
                    value = update.get("value")
                    if field and value is not None:
                        try:
                            await MemoryService.update_profile_field(
                                user_id=user_id,
                                field=field,
                                value=value,
                                source="chat_inferred",
                                db_session=db,
                            )
                            chat_service.logger.info(
                                f"[LTM-chat] 画像直写: {field}={value} "
                                f"(evidence: {update.get('evidence', '')[:60]})"
                            )
                        except Exception as uf_exc:
                            chat_service.logger.warning(f"[LTM-chat] 画像字段写入失败: {field}: {uf_exc}")

            # ── 语义增强入队（Mem0）：只在有画像信号时入队 ────────
            # 发给 Mem0 的是【高维度事实字符串】，包含：
            #   A 类：结构化投资画像事实（来自 extraction["updates"]）
            #   B 类：回复风格偏好事实（来自 extraction["style_facts"]）
            if extraction.get("has_profile_signal"):
                from backend.services.profile_extractor import build_fact_messages
                fact_messages = build_fact_messages(
                    extraction.get("updates", []),
                    extraction.get("style_facts", []),
                )

                if fact_messages:
                    msg_ids = [str(m.id) for m in pending_msgs]
                    extracted_fields = [u["field"] for u in extraction.get("updates", [])]
                    style_count = len(extraction.get("style_facts", []))
                    metadata = {
                        "source": "chat_inferred",
                        "session_id": session_id,
                        "evidence_ref": ",".join(msg_ids),
                        "active": True,
                        "updated_by": "llm",
                        "confidence": 0.7,
                        "mem0_infer": False,
                        "extracted_fields": extracted_fields,
                    }

                    await MemoryService.enqueue_add_conversation(
                        user_id=user_id,
                        messages=fact_messages,
                        metadata=metadata,
                        db_session=db,
                    )

                    trigger_reason = "count阈值" if trigger_by_count else "compress轮次"
                    print(
                        f"[LTM-chat] 事实入队: session={session_id[:8]}..., "
                        f"A类fields={extracted_fields}, B类style={style_count}条, "
                        f"总facts={len(fact_messages)}, 触发={trigger_reason}"
                    )
                    chat_service.logger.info(
                        f"[LTM-chat] 入队高维度事实: session={session_id}, user={user_id}, "
                        f"facts={len(fact_messages)}, A={extracted_fields}, "
                        f"B={extraction.get('style_facts', [])}, trigger={trigger_reason}"
                    )
            else:
                chat_service.logger.debug(
                    f"[LTM-chat] 对话无画像信号，跳过 Mem0 入队: session={session_id[:8]}..."
                )
                print(
                    f"[LTM-chat] 对话无画像信号，跳过 Mem0 入队: session={session_id[:8]}..."
                )

            # 批量标记 used_for_ltm=True（无论是否有信号，都标记避免重复处理）
            for msg in pending_msgs:
                msg.used_for_ltm = True
            await db.commit()

    except Exception as exc:
        chat_service.logger.error(f"[LTM-chat] maybe_update_ltm_from_chat 异常（不影响主流程）: {exc}", exc_info=True)
        print(f"[LTM-chat] LTM 更新异常（不影响主流程）: {exc}")


async def _extract_from_summary(session_id: str, user_id: str, summary: str) -> None:
    """
    P3 新增：从 STM 压缩摘要中提取画像要素（非阻塞后台任务）。

    摘要质量远高于原始对话，是提取画像的最佳时机。
    仅在 ENABLE_MEMORY=true 且摘要非空时执行。
    同时将高维度事实字符串入队 Mem0，保持语义增强层与 DB 一致。
    """
    chat_service = _chat_service_facade()
    if not settings.enable_memory:
        return
    if not bool(settings.enable_summary_ltm_extract):
        chat_service.logger.debug(
            "[LTM-summary] skip: ENABLE_SUMMARY_LTM_EXTRACT=false session=%s",
            session_id,
        )
        return
    if not summary or not user_id:
        return
    try:
        from backend.services.profile_extractor import extract_profile_updates, build_fact_messages
        from backend.db.database import AsyncSessionFactory

        MemoryService = chat_service._get_memory_service_cls()
        extraction = await extract_profile_updates(
            messages=[{"role": "system", "content": summary}],
            running_summary="",
        )

        if not extraction.get("has_profile_signal"):
            chat_service.logger.debug(f"[LTM-summary] 摘要中无画像信号: session={session_id[:8]}...")
            return

        updates = extraction.get("updates") or []
        style_facts = extraction.get("style_facts") or []
        fact_messages = build_fact_messages(updates, style_facts)

        async with AsyncSessionFactory() as db:
            # A 类：写入结构化字段到 DB（可无，仅 B 类 style_facts 时跳过）
            for update in updates:
                field = update.get("field")
                value = update.get("value")
                if field and value is not None:
                    await MemoryService.update_profile_field(
                        user_id=user_id,
                        field=field,
                        value=value,
                        source="chat_inferred",
                        db_session=db,
                    )

            # A+B 类事实入队 Mem0（含仅有「用户偏好：…」的 B 类）
            if fact_messages:
                metadata = {
                    "source": "chat_inferred",
                    "session_id": session_id,
                    "active": True,
                    "updated_by": "llm",
                    "confidence": 0.75,
                    "mem0_infer": False,
                    "extracted_fields": [u["field"] for u in updates],
                }
                await MemoryService.enqueue_add_conversation(
                    user_id=user_id,
                    messages=fact_messages,
                    metadata=metadata,
                    db_session=db,
                )

            await db.commit()

        extracted_fields = [u["field"] for u in updates]
        chat_service.logger.info(
            f"[LTM-summary] 从摘要中抽取画像: session={session_id[:8]}..., "
            f"fields={extracted_fields}, style_facts={len(style_facts)}, facts={len(fact_messages)}"
        )
        print(
            f"[LTM-summary] 摘要画像抽取: session={session_id[:8]}..., "
            f"fields={extracted_fields}, B类={len(style_facts)}, facts={len(fact_messages)}"
        )

    except Exception as exc:
        chat_service.logger.warning(f"[LTM-summary] 摘要画像抽取失败（不影响主流程）: {exc}")


async def _handle_profile_action_in_reply(reply_text: str, user_id: str, db) -> None:
    """
    解析 LLM 回复中的 <action>...</action> 标签，提取结构化 profile update 指令。
    调用 MemoryService.update_profile_and_enqueue（source=explicit_correction）。
    """
    import re
    import json as _json

    chat_service = _chat_service_facade()
    pattern = r'<action>(.*?)</action>'
    matches = re.findall(pattern, reply_text, re.DOTALL)

    for match in matches:
        try:
            action_data = _json.loads(match.strip())
            if action_data.get("action") != "update_profile":
                continue
            field = action_data.get("field", "")
            value = action_data.get("value")

            if not field or value is None:
                continue

            # 字段合法性校验
            allowed = {"risk_level", "sectors", "investment_horizon", "response_pref"}
            if field not in allowed:
                continue

            normalized = _normalize_profile_action(field, value)
            if not normalized:
                chat_service.logger.info(
                    f"[LTM-chat] action 值不合法/无法映射，已忽略: user={user_id}, field={field}, value={value}"
                )
                continue
            field, value = normalized

            MemoryService = chat_service._get_memory_service_cls()
            MemorySource = chat_service._get_memory_source_cls()

            await MemoryService.update_profile_and_enqueue(
                user_id=user_id,
                field=field,
                value=value,
                source=MemorySource.EXPLICIT_CORR,
                db_session=db,
            )
            print(
                f"[LTM-chat] 检测到用户主动纠正，更新画像: "
                f"field={field}, value={value}, source=explicit_correction"
            )
            chat_service.logger.info(
                f"[LTM-chat] explicit_correction: user={user_id}, field={field}, value={value}"
            )

        except Exception as exc:
            chat_service.logger.debug(f"[LTM-chat] _handle_profile_action 解析失败: {exc}")


async def _handle_profile_action_in_user_message(db: AsyncSession, user_id: str, user_message: str) -> str:
    """
    支持用户直接发送 JSON action 来更新画像（用于“我已经按格式贴了 action，但前端没点亮”的场景）。

    输入示例：
      {"action":"update_profile","field":"sectors","value":["科技/半导体"]} 前端并没有点亮

    行为：
    - 若识别到 action，先更新画像（source=explicit_correction），再从 user_message 中剔除该 JSON 块，
      返回剩余文本继续走正常对话（避免 LLM 被 JSON 干扰）。
    - 若未识别到，原样返回。
    """
    import json as _json

    chat_service = _chat_service_facade()

    def _extract_json_candidates(text: str) -> list[str]:
        # 简易花括号配对提取，支持 message 中夹杂中文/空格
        out: list[str] = []
        stack = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if stack == 0:
                    start = i
                stack += 1
            elif ch == "}":
                if stack > 0:
                    stack -= 1
                    if stack == 0 and start != -1:
                        out.append(text[start : i + 1])
                        start = -1
        return out

    candidates = _extract_json_candidates(user_message)
    if not candidates:
        return user_message

    for blob in candidates:
        try:
            data = _json.loads(blob)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("action") != "update_profile":
            continue
        field = data.get("field")
        value = data.get("value")
        if not field:
            continue

        normalized = _normalize_profile_action(str(field), value)
        if not normalized:
            chat_service.logger.info(
                f"[LTM-chat] user_action 值不合法/无法映射，已忽略: user={user_id}, field={field}, value={value}"
            )
            continue
        field, value = normalized

        try:
            await MemoryService.update_profile_and_enqueue(
                user_id=user_id,
                field=str(field),
                value=value,
                source=MemorySource.EXPLICIT_CORRECTION,
                db_session=db,
            )
            chat_service.logger.info(f"[LTM-chat] user_action 更新画像: user={user_id}, field={field}")
            print(f"[LTM-chat] user_action 更新画像: user={user_id[:8]}..., field={field}")
        except Exception as exc:
            chat_service.logger.warning(f"[LTM-chat] user_action 更新画像失败（不影响对话）: {exc}")
            return user_message

        # 剔除该 JSON 块（只去掉一次），保留剩余自然语言
        cleaned = user_message.replace(blob, "").strip()
        return cleaned

    return user_message
