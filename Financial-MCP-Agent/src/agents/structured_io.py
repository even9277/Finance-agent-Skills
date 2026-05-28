from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredIOError(RuntimeError):
    """Raised when structured output cannot be parsed or validated."""


class SyntaxRepairError(StructuredIOError):
    """Raised when JSON syntax repair fails."""


class SemanticRepairError(StructuredIOError):
    """Raised when schema-valid JSON fails semantic validation."""


@dataclass(slots=True)
class StructuredCallResult:
    payload: Any
    raw_text: str
    stages_run: list[str] = field(default_factory=list)
    syntax_repaired: bool = False
    semantic_repaired: bool = False
    validation_errors: list[str] = field(default_factory=list)


def coerce_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def extract_json_object(raw_text: Any) -> dict[str, Any]:
    text = coerce_text(raw_text).strip()
    if not text:
        raise SyntaxRepairError("empty_output")

    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise SyntaxRepairError("json_object_not_found")
        try:
            parsed = json.loads(match.group(0))
        except Exception as exc:
            raise SyntaxRepairError(f"json_parse_failed: {exc}") from exc

    if not isinstance(parsed, dict):
        raise SyntaxRepairError("json_root_not_object")
    return parsed


def validate_model(model_cls: type[T], data: dict[str, Any]) -> T:
    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(data)
        return model_cls.parse_obj(data)  # type: ignore[attr-defined]
    except ValidationError as exc:
        raise SemanticRepairError(str(exc)) from exc


async def structured_call(
    *,
    invoke: Callable[[str], Any],
    prompt: str,
    schema: type[T],
    semantic_validator: Callable[[T], list[str]] | None = None,
    repair_prompt_fn: Callable[[str, str], str] | None = None,
    semantic_repair_prompt_fn: Callable[[str, list[str]], str] | None = None,
) -> StructuredCallResult:
    """
    Run generate -> syntax repair -> semantic validation for strict JSON outputs.

    `invoke` is intentionally generic so callers can pass LangChain, OpenAI-compatible,
    or deterministic test doubles without this module owning model construction.
    """

    stages = ["generate"]
    raw = coerce_text(await invoke(prompt))
    try:
        payload = extract_json_object(raw)
    except SyntaxRepairError as exc:
        stages.append("syntax_repair")
        repair_prompt = (
            repair_prompt_fn(raw, str(exc))
            if repair_prompt_fn
            else f"上次输出 JSON 解析失败：{exc}\n仅修复为合法 JSON，不要改变语义。\n\n{raw}"
        )
        raw = coerce_text(await invoke(repair_prompt))
        payload = extract_json_object(raw)
        syntax_repaired = True
    else:
        syntax_repaired = False

    model = validate_model(schema, payload)
    semantic_errors = semantic_validator(model) if semantic_validator else []
    if semantic_errors:
        stages.append("semantic_repair")
        repair_prompt = (
            semantic_repair_prompt_fn(raw, semantic_errors)
            if semantic_repair_prompt_fn
            else "上次 JSON 语义校验失败：\n"
            + "\n".join(f"- {item}" for item in semantic_errors)
            + "\n仅修复这些字段，仍然只输出 JSON。\n\n"
            + raw
        )
        raw = coerce_text(await invoke(repair_prompt))
        payload = extract_json_object(raw)
        model = validate_model(schema, payload)
        semantic_errors = semantic_validator(model) if semantic_validator else []
        if semantic_errors:
            raise SemanticRepairError("; ".join(semantic_errors))
        semantic_repaired = True
    else:
        semantic_repaired = False

    return StructuredCallResult(
        payload=model,
        raw_text=raw,
        stages_run=stages,
        syntax_repaired=syntax_repaired,
        semantic_repaired=semantic_repaired,
        validation_errors=[],
    )


__all__ = [
    "SemanticRepairError",
    "StructuredCallResult",
    "StructuredIOError",
    "SyntaxRepairError",
    "coerce_text",
    "extract_json_object",
    "structured_call",
    "validate_model",
]
