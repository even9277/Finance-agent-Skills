from __future__ import annotations

from typing import Any

try:
    from langchain.messages import AIMessage
except Exception:
    from langchain_core.messages import AIMessage


def _text_from_content_blocks(message: Any) -> str:
    blocks = getattr(message, "content_blocks", None) or []
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in {"text", "text-plain"} and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()


def _text_from_message(message: Any) -> str:
    text = _text_from_content_blocks(message)
    if text:
        return text

    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()

    return ""


def extract_final_text(response: Any) -> str:
    """
    Extract the final human-readable agent output from legacy and v1 responses.
    """
    if isinstance(response, dict):
        output = response.get("output")
        if isinstance(output, str) and output.strip():
            return output.strip()

        messages = response.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, AIMessage):
                    text = _text_from_message(message)
                    if text:
                        return text

            for message in reversed(messages):
                text = _text_from_message(message)
                if text:
                    return text

    text = _text_from_message(response)
    return text or "No analysis generated."
