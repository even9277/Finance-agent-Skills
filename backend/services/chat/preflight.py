import json
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Session


def _chat_service_facade():
    from backend.services import chat_service

    return chat_service


def _get_llm():
    """懒加载 LLM 客户端（复用 agent 环境变量）。"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        openai_api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", ""),
        openai_api_base=os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
        temperature=0.7,
    )


async def _prepare_chat_preflight_inputs(
    db: AsyncSession,
    session: Session,
    *,
    user_id: str,
    user_message: str,
) -> tuple[dict, str]:
    memory_profile, memory_system_prompt = await _chat_service_facade()._load_memory_context_for_chat(
        db,
        user_id,
        user_message,
    )
    del session
    return memory_profile, memory_system_prompt


async def _run_chat_preflight_compaction(
    db: AsyncSession,
    session: Session,
    *,
    user_message: str,
    user_message_id: int,
    memory_system_prompt: str,
    trigger: str,
    stream_status_emitter: Any | None = None,
) -> None:
    if not settings.enable_stm or not settings.stm_summary_preflight_enabled:
        return

    chat_service = _chat_service_facade()
    await chat_service.maybe_run_preflight_summary_compaction(
        db=db,
        session=session,
        pending_user_message=user_message,
        system_prompt_text=chat_service._CHAT_SYSTEM_PROMPT,
        memory_prompt_text=memory_system_prompt,
        exclude_message_ids={int(user_message_id)},
        trigger=trigger,
        stream_status_emitter=stream_status_emitter,
    )
    await db.refresh(session)


def _serialize_prompt_payload(payload: Any, *, max_chars: int = 24000) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = str(payload)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>..."


def _extract_model_text(response: Any) -> str:
    if response is None:
        return ""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    chunks.append(str(text))
            elif isinstance(item, str):
                chunks.append(item)
        return "\n".join(chunks).strip()
    return str(content).strip()
