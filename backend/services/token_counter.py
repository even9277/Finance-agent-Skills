"""Token counting helpers for STM metrics and rolling summary budgeting."""

from __future__ import annotations

from typing import Iterable

from backend.config import settings

try:
    import tiktoken
except Exception:  # pragma: no cover - dependency is optional at runtime
    tiktoken = None

COUNTING_MODE_EXACT = "exact"
COUNTING_MODE_ESTIMATED = "estimated"
COUNTING_MODE_ESTIMATED_FALLBACK = "estimated_fallback"

_KNOWN_APPROXIMATE_MODEL_PREFIXES = ("qwen", "kimi", "deepseek", "glm", "moonshot")


def current_model_name() -> str:
    candidates = (
        settings.openai_compatible_model,
        settings.chat_router_model,
        settings.chat_resolver_model,
        settings.stm_compaction_model,
    )
    for item in candidates:
        model = (item or "").strip()
        if model:
            return model
    return ""


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars / 1.5 + other_chars / 4))


def _is_known_approximate_model(model_name: str) -> bool:
    model_lower = (model_name or "").strip().lower()
    return any(model_lower.startswith(prefix) for prefix in _KNOWN_APPROXIMATE_MODEL_PREFIXES)


def _estimate_with_mode(text: str, *, model_name: str) -> tuple[int, str]:
    if _is_known_approximate_model(model_name):
        return estimate_tokens(text), COUNTING_MODE_ESTIMATED

    mode = COUNTING_MODE_ESTIMATED_FALLBACK if model_name else COUNTING_MODE_ESTIMATED
    return estimate_tokens(text), mode


def count_text_tokens(text: str, model_name: str | None = None) -> tuple[int, str]:
    model = (model_name or current_model_name()).strip()
    if _is_known_approximate_model(model):
        return estimate_tokens(text), COUNTING_MODE_ESTIMATED

    if tiktoken is not None and model:
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text or "")), COUNTING_MODE_EXACT
        except Exception:
            pass

    if tiktoken is not None:
        try:
            encoding = tiktoken.get_encoding("o200k_base")
            return len(encoding.encode(text or "")), COUNTING_MODE_ESTIMATED_FALLBACK
        except Exception:
            pass

    return _estimate_with_mode(text, model_name=model)


def count_message_tokens(role: str, content: str, model_name: str | None = None) -> tuple[int, str]:
    # Small per-message overhead to better match chat payloads.
    tokens, mode = count_text_tokens(content, model_name=model_name)
    return tokens + 4 + (1 if role else 0), mode


def normalize_counting_mode(mode: str | None) -> str:
    normalized = (mode or "").strip().lower()
    if normalized == COUNTING_MODE_EXACT:
        return COUNTING_MODE_EXACT
    if normalized == COUNTING_MODE_ESTIMATED_FALLBACK:
        return COUNTING_MODE_ESTIMATED_FALLBACK
    return COUNTING_MODE_ESTIMATED


def merge_counting_modes(modes: Iterable[str]) -> str:
    normalized = [normalize_counting_mode(mode) for mode in modes if mode is not None]
    if not normalized:
        return COUNTING_MODE_ESTIMATED
    if COUNTING_MODE_ESTIMATED_FALLBACK in normalized:
        return COUNTING_MODE_ESTIMATED_FALLBACK
    if COUNTING_MODE_ESTIMATED in normalized:
        return COUNTING_MODE_ESTIMATED
    return COUNTING_MODE_EXACT
