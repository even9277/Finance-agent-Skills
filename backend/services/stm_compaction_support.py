"""为异步 STM 压缩 worker 提供模型和可选画像提取能力。"""

from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from backend.config import settings

logger = logging.getLogger(__name__)

SUMMARIZE_CONVERSATION_PROMPT = """
你是一个金融对话摘要助手。请将以下对话历史压缩成精炼摘要，严格保留：
- 股票代码、公司名称和用户问题；
- 风险偏好、持有期限、关注板块与关键约束；
- 已形成结论中的建议和关键数值。
省略寒暄、重复内容和中间推理。输出 300 字以内中文纯文字。
""".strip()


def build_compaction_model() -> ChatOpenAI:
    """使用统一 Settings 构造 STM 压缩模型。"""
    model = settings.openai_compatible_model
    if not all(
        (
            model,
            settings.openai_compatible_api_key,
            settings.openai_compatible_base_url,
        )
    ):
        raise RuntimeError("STM compaction model configuration is incomplete")
    return ChatOpenAI(
        model=model,
        api_key=SecretStr(settings.openai_compatible_api_key),
        base_url=settings.openai_compatible_base_url,
        temperature=0.2,
        timeout=30,
        max_retries=1,
    )


async def extract_profile_from_summary(
    *,
    session_id: str,
    user_id: str,
    summary: str,
) -> None:
    """从摘要提取画像并写入既有异步记忆队列。

    该出口属于可选增强；任何失败只记录类型，不改变已提交的压缩结果。
    """
    if not settings.enable_memory or not summary or not user_id:
        return
    try:
        from backend.db.database import AsyncSessionFactory
        from backend.services.profile_extractor import build_fact_messages, extract_profile_updates
        from src.memory.memory_service import MemoryService

        extraction = await extract_profile_updates(
            messages=[{"role": "system", "content": summary}],
            running_summary="",
        )
        if not extraction.get("has_profile_signal"):
            return
        updates = extraction.get("updates") or []
        style_facts = extraction.get("style_facts") or []
        fact_messages = build_fact_messages(updates, style_facts)
        async with AsyncSessionFactory() as db:
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
            if fact_messages:
                await MemoryService.enqueue_add_conversation(
                    user_id=user_id,
                    messages=fact_messages,
                    metadata={
                        "source": "chat_inferred",
                        "session_id": session_id,
                        "active": True,
                        "updated_by": "llm",
                        "confidence": 0.75,
                        "mem0_infer": False,
                        "extracted_fields": [item["field"] for item in updates],
                    },
                    db_session=db,
                )
            await db.commit()
    except Exception as exc:
        logger.warning(
            "stm.summary_profile_extract_failed session_id=%s error_type=%s",
            session_id,
            type(exc).__name__,
        )
