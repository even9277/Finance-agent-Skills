"""Token counting helpers for STM context budgeting."""

from __future__ import annotations

from typing import Iterable

from backend.config import settings

try:
    import tiktoken
except Exception:  # pragma: no cover - dependency is optional at runtime
    tiktoken = None

_KNOWN_CONTEXT_WINDOWS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
}


def current_model_name() -> str:
    return (settings.openai_compatible_model or "").strip()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars / 1.5 + other_chars / 4))


def count_text_tokens(text: str, model_name: str | None = None) -> tuple[int, str]:
    if not text:
        return 0, "estimated" if tiktoken is None else "exact"

    model = (model_name or current_model_name()).strip()
    if tiktoken is not None and model:
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text)), "exact"
        except Exception:
            pass

    if tiktoken is not None:
        try:
            encoding = tiktoken.get_encoding("o200k_base")
            return len(encoding.encode(text)), "exact"
        except Exception:
            pass

    return estimate_tokens(text), "estimated"


def count_message_tokens(role: str, content: str, model_name: str | None = None) -> tuple[int, str]:
    # Small per-message overhead to better match chat payloads.
    tokens, mode = count_text_tokens(content, model_name=model_name)
    return tokens + 4 + (1 if role else 0), mode


def merge_counting_modes(modes: Iterable[str]) -> str:
    for mode in modes:
        if mode != "exact":
            return "estimated"
    return "exact"


def detect_context_budget_tokens(model_name: str | None = None) -> int:
    model = (model_name or current_model_name()).strip().lower()
    for prefix, size in _KNOWN_CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return size
    return int(settings.stm_context_budget_tokens)
