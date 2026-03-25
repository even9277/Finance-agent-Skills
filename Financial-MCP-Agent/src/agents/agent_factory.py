from __future__ import annotations

from typing import Any

try:
    from langchain.agents import create_agent as _create_agent
except Exception:
    _create_agent = None

try:
    from langgraph.prebuilt import create_react_agent as _legacy_create_react_agent
except Exception:
    _legacy_create_react_agent = None


def build_analysis_agent(
    *,
    model: Any,
    tools: list[Any],
    system_prompt: str | None = None,
):
    """
    Build a tool-calling agent behind a stable internal interface.

    Prefer the LangChain v1 `create_agent` entrypoint when available.
    Fall back to legacy `create_react_agent` for pre-v1 environments.
    """
    if _create_agent is not None:
        kwargs: dict[str, Any] = {
            "model": model,
            "tools": tools,
        }
        if system_prompt:
            kwargs["system_prompt"] = system_prompt
        return _create_agent(**kwargs)

    if _legacy_create_react_agent is not None:
        return _legacy_create_react_agent(model, tools)

    raise RuntimeError("No supported agent builder is available.")
