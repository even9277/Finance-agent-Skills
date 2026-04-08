from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents.agent_factory import build_analysis_agent
from src.agents.response_normalizer import extract_final_text
from src.agents.skill_evidence import validate_evidence
from src.agents.skill_spec_planner import build_skill_tool_plan
from src.agents.tushare_reference_planner import build_tushare_tool_plan
from src.skills.skill_registry import get_skill_registry
from src.tools.chat_tushare_tools import get_tushare_toolkit
from src.tools.skill_trace import (
    log_claim_lineage,
    log_degrade_transition,
    log_model_stage,
    log_policy_violation,
    log_reply_completed,
    log_skill_selected,
    log_tool_plan,
    new_claim_id,
    skill_trace_context,
    trace_span,
    write_trace_artifact,
)
from src.utils.logging_config import setup_logger

logger = setup_logger("skill_executor")

try:
    from dotenv import load_dotenv

    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / "backend" / ".env", override=False)
except Exception:
    pass


@dataclass(slots=True)
class SkillExecutionResult:
    reply_text: str
    selected_skill: str
    trace: dict[str, Any] = field(default_factory=dict)
    used_fallback: bool = False


_VERIFIABLE_DATA_KEYWORDS = [
    "今天",
    "今日",
    "现在",
    "最新",
    "最近",
    "行情",
    "财报",
    "财务",
    "估值",
    "营收",
    "利润",
    "净利润",
    "现金流",
    "毛利率",
    "涨幅",
    "跌幅",
    "成交额",
    "资金",
]


def _safe_getenv(name: str, default: str = "") -> str:
    import os

    return (os.getenv(name) or default).strip()


def _model_name(env_name: str, *, fallback_env: str = "OPENAI_COMPATIBLE_MODEL", default: str = "") -> str:
    return _safe_getenv(env_name) or _safe_getenv(fallback_env) or default


def _router_model_name() -> str:
    return _model_name("CHAT_ROUTER_MODEL", default="kimi-k2.5")


def _resolver_model_name() -> str:
    return _model_name("CHAT_RESOLVER_MODEL", default="kimi-k2.5")


def _synthesis_model_name() -> str:
    return _model_name("CHAT_SKILL_SYNTHESIS_MODEL", fallback_env="OPENAI_COMPATIBLE_MODEL")


def _build_model(*, model_name: str | None = None, temperature: float = 0.2, max_tokens: int | None = None):
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": model_name or _synthesis_model_name(),
        "openai_api_key": _safe_getenv("OPENAI_COMPATIBLE_API_KEY"),
        "openai_api_base": _safe_getenv("OPENAI_COMPATIBLE_BASE_URL"),
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def _skill_prompt(skill_name: str, official_skill_file: Path | None) -> str:
    meta = get_skill_registry().get_skill(_source_skill_name(skill_name))
    references_hint = ""
    if meta and meta.references_dir:
        references_hint = f"官方 references 目录：{meta.references_dir}"
    alias_hint = ""
    if meta and meta.aliases:
        alias_hint = f"官方别名/slug：{', '.join(meta.aliases)}"
    version_hint = ""
    if meta and meta.version:
        version_hint = f"官方 skill 版本：{meta.version}"

    return f"""你是一位A股投研助手，正在执行技能 `{skill_name}`。

技能来源：
- 主能力源：vendor 进来的官方 Tushare Skills 定义
- 当前执行引擎：本仓库内置 Python/Tushare 适配层
- 官方 skill 文件：{official_skill_file or 'unknown'}
- {references_hint or '无 references 目录'}
- {alias_hint or '无额外别名'}
- {version_hint or '版本未知'}

执行原则：
1. 先判断这个问题是否真的需要调用工具。
2. 如果不需要实时数据或专业数据分析，可以直接回答。
3. 如果需要数据，自主决定调用哪些工具，不要默认全调。
4. 如果回答中出现实时/财务/行情数值，必须先调用工具。
5. 如果当前能力边界不支持可靠回答，明确说不知道或暂不支持，不要编造。
6. 用中文回答。
7. 如果使用了工具，回答中要标注数据来源：Tushare，以及数据时间或财报期。
"""


def _source_skill_name(selected_skill: str) -> str:
    if selected_skill == "tushare-data":
        return "tushare-data"
    return selected_skill


def _analysis_style_guidance(analysis_mode: str) -> str:
    if analysis_mode == "single_stock_fundamental":
        return """【专业分析要求】
1. 这是单股专业分析问题，不仅要复述数据，还要结合用户画像评估“今天是否值得买入”。
2. 先用工具核实最近行情与财务指标，再给出结论；没有足够数据时必须明确说不能确定。
3. 回答至少覆盖：结论、支持理由、主要风险、与用户画像的匹配度、数据来源与时间。
4. 不要给绝对化承诺，不要编造实时价格、涨跌幅或财务指标。
"""
    if analysis_mode == "sector_market":
        return """【行业/板块分析要求】
1. 优先使用板块、行业、指数类工具；没有这类数据时明确说明边界。
2. 回答应区分板块整体表现与代表性成分股，不要把个股数据冒充板块数据。
"""
    return ""


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _reference_guidance(selected_skill: str, user_message: str) -> str:
    registry = get_skill_registry()
    meta = registry.get_skill(_source_skill_name(selected_skill))
    if meta is None:
        return ""

    refs = registry.find_references(_source_skill_name(selected_skill), user_message, limit=5)
    if not refs:
        return ""

    lines = []
    for item in refs:
        lines.append(f"- [{item['category']}] {item['title']} ({item['path']})")
    return "【官方 skill 相关参考】\n" + "\n".join(lines)


def _build_prompt(
    *,
    user_message: str,
    memory_context: str,
    running_summary: str,
    profile_summary: str,
    resolved_company: str | None,
    resolved_symbol: str | None,
    selected_skill: str,
    analysis_mode: str,
    tool_plan_summary: str,
) -> str:
    meta = get_skill_registry().get_skill(_source_skill_name(selected_skill))
    sections = [_skill_prompt(selected_skill, meta.skill_file if meta else None)]
    analysis_style_block = _analysis_style_guidance(analysis_mode)
    if analysis_style_block:
        sections.append(analysis_style_block)
    if meta:
        sections.append(f"【技能描述】\n{meta.description}")
        if meta.official_name and meta.official_name != meta.name:
            sections.append(f"【官方 skill 名称】\n{meta.official_name}")
        if meta.version:
            sections.append(f"【官方版本】\n{meta.version}")
        if meta.allowed_tools:
            sections.append(f"【允许工具】\n{', '.join(meta.allowed_tools)}")
        if meta.scripts_dir:
            sections.append(f"【官方脚本目录】\n{meta.scripts_dir}")
        reference_block = _reference_guidance(selected_skill, user_message)
        if reference_block:
            sections.append(reference_block)
    if tool_plan_summary:
        sections.append(f"【建议工具计划】\n{tool_plan_summary}")
    if memory_context:
        sections.append(f"【memory_context】\n{memory_context[:1600]}")
    if running_summary:
        sections.append(f"【running_summary】\n{running_summary[:600]}")
    if profile_summary:
        sections.append(f"【用户画像摘要】\n{profile_summary}")
    if resolved_company or resolved_symbol:
        sections.append(
            f"【已解析标的】\ncompany={resolved_company or 'unknown'}\nsymbol={resolved_symbol or 'unknown'}"
        )
    sections.append(f"【用户问题】\n{user_message}")
    return "\n\n".join(sections)


def _format_tool_failure_message(query: str, error: str | None = None) -> str:
    detail = f"（原因：{error}）" if error else ""
    return (
        f"暂时无法获取这条问题对应的可靠 Tushare 数据{detail}。"
        f"如果你希望继续，我建议你换成更明确的个股问题，或稍后重试。原问题：{query}"
    )


def _missing_evidence_message(query: str) -> str:
    return (
        f"这个问题需要可核对的数据支持，但我这次没有成功拿到足够的工具结果，所以不能可靠回答：{query}。"
        "如果你愿意，可以换成具体个股，或稍后重试。"
    )


def _needs_verifiable_data(query: str) -> bool:
    text = (query or "").strip()
    return any(keyword in text for keyword in _VERIFIABLE_DATA_KEYWORDS)


def _response_used_tools(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    messages = response.get("messages")
    if not isinstance(messages, list):
        return False

    for message in messages:
        message_type = getattr(message, "type", None)
        if message_type == "tool" or message.__class__.__name__ == "ToolMessage":
            return True
    return False


def _unsupported_message(selected_skill: str, analysis_mode: str, query: str) -> str:
    if selected_skill == "tushare-data" and analysis_mode == "single_stock_fundamental":
        return f"当前单股专业分析模式尚未启用，所以对于“{query}”我现在不能可靠回答。"
    if selected_skill == "tushare-data" and analysis_mode == "sector_market":
        return f"当前板块/行业分析模式尚未启用，所以对于“{query}”我现在不能可靠回答。"
    if selected_skill == "tushare-data" and analysis_mode == "stock_selection":
        return f"当前选股模式尚未启用，所以对于“{query}”我现在不能可靠回答。"
    return f"当前能力暂未启用，所以对于“{query}”我现在不能可靠回答。"


def _skill_capability_note(selected_skill: str, query: str) -> str:
    registry = get_skill_registry()
    refs = registry.find_references(_source_skill_name(selected_skill), query, limit=3)
    if not refs:
        return ""
    joined = "；".join(f"{item['title']}" for item in refs)
    return f"官方 skill 当前最相关的参考包括：{joined}。"


def _mode_enabled(analysis_mode: str, *, enable_fundamental_analysis: bool, enable_sector_analysis: bool, enable_stock_selection: bool) -> bool:
    if analysis_mode == "single_stock_fundamental":
        return enable_fundamental_analysis
    if analysis_mode == "sector_market":
        return enable_sector_analysis
    if analysis_mode == "stock_selection":
        return enable_stock_selection
    return True


def _toolkit_for_plan(plan_tool_names: list[str]) -> list[Any]:
    available = {
        getattr(tool, "name", getattr(tool, "__name__", "")): tool
        for tool in get_tushare_toolkit()
    }
    tools: list[Any] = []
    for name in plan_tool_names:
        tool = available.get(name)
        if tool is not None:
            tools.append(tool)
    return tools


def _summarize_tool_plan(tool_plan) -> str:
    if not tool_plan.tool_calls:
        return "当前没有可执行的 Tushare 工具计划，如需回答必须明确说明能力边界。"
    lines = []
    for item in tool_plan.tool_calls:
        lines.append(f"- {item.tool_name}: {item.reason}")
    return "\n".join(lines)


@dataclass(slots=True)
class _ToolMessageLike:
    name: str
    content: str
    type: str = "tool"


def _toolkit_by_name() -> dict[str, Any]:
    return {
        getattr(tool, "name", getattr(tool, "__name__", "")): tool
        for tool in get_tushare_toolkit()
    }


def _toolkit_for_names(tool_names: list[str]) -> list[Any]:
    available = _toolkit_by_name()
    return [available[name] for name in tool_names if name in available]


def _percentile_ms(values: list[float | int], percentile: float = 0.95) -> float:
    cleaned = sorted(float(value) for value in values if value is not None)
    if not cleaned:
        return 0.0
    index = max(0, min(len(cleaned) - 1, math.ceil(len(cleaned) * percentile) - 1))
    return round(cleaned[index], 2)


def _policy_violation_names(planned_tool_names: list[str], allowed_tools: list[str]) -> list[str]:
    allowed = {str(item) for item in allowed_tools if str(item)}
    if not allowed:
        return []
    return [tool_name for tool_name in planned_tool_names if tool_name not in allowed]


def _execution_observability_metrics(
    *,
    route_confidence: float | None,
    planned_tool_names: list[str],
    tool_results: list[tuple[str, dict[str, Any]]],
    degrade_policy: dict[str, Any] | None,
    policy_violation_names: list[str] | None = None,
    evidence_ok: bool = False,
) -> dict[str, Any]:
    durations = [
        float(result.get("duration_ms") or 0)
        for _, result in tool_results
        if isinstance(result, dict) and result.get("duration_ms") is not None
    ]
    success_count = sum(1 for _, result in tool_results if isinstance(result, dict) and bool(result.get("ok")))
    failure_count = max(0, len(tool_results) - success_count)
    tool_failure_rate = round((failure_count / len(tool_results)), 4) if tool_results else 0.0
    return {
        "route_confidence": round(float(route_confidence or 0.0), 4),
        "tool_batch_size": len(planned_tool_names),
        "tool_success_count": success_count,
        "tool_failure_count": failure_count,
        "tool_failure_rate": tool_failure_rate,
        "p95_latency": _percentile_ms(durations),
        "degrade_stage": str((degrade_policy or {}).get("current_stage") or "none"),
        "policy_violation_count": len(policy_violation_names or []),
        "evidence_ok": bool(evidence_ok),
    }


def _should_use_deterministic_path(
    *,
    analysis_mode: str,
    is_fund_query: bool,
    enable_deterministic_skill_execution: bool,
    enable_tushare_planner: bool,
) -> bool:
    if not enable_deterministic_skill_execution or not enable_tushare_planner:
        return False
    if analysis_mode in {"single_stock_data", "single_stock_fundamental", "sector_market"}:
        return True
    return analysis_mode == "stock_selection" and is_fund_query


def _serialize_tool_output(payload: Any) -> str:
    def _trim(value: Any) -> Any:
        if isinstance(value, list):
            return [_trim(item) for item in value[:3]]
        if isinstance(value, dict):
            trimmed = {}
            for idx, (key, item) in enumerate(value.items()):
                if idx >= 20:
                    break
                trimmed[key] = _trim(item)
            return trimmed
        return value

    return json.dumps(_trim(payload), ensure_ascii=False, default=str)


def _strip_frontmatter(markdown_text: str) -> str:
    text = (markdown_text or "").strip()
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2].strip()


def _response_pref(profile_summary: str) -> str:
    for raw_line in (profile_summary or "").splitlines():
        if ":" not in raw_line:
            continue
        label, value = raw_line.split(":", 1)
        if label.strip() == "回答偏好":
            return value.strip()
    return "balanced"


def _skill_output_template(skill_spec: dict[str, Any], profile_summary: str) -> dict[str, Any]:
    template = dict(skill_spec.get("output_template") or {})
    section_order = list(template.get("default_section_order") or [])
    style_variant = "default"
    response_pref = _response_pref(profile_summary)
    overrides = template.get("response_pref_overrides") or {}
    override = overrides.get(response_pref) or {}
    if override.get("section_order"):
        section_order = list(override.get("section_order") or [])
    if override.get("style_variant"):
        style_variant = str(override.get("style_variant") or "default")
    return {
        "response_pref": response_pref,
        "section_order": section_order,
        "style_variant": style_variant,
    }


def _skill_tool_policy(skill_spec: dict[str, Any]) -> dict[str, list[str]]:
    allowed_tools = [str(item) for item in skill_spec.get("allowed_tools") or [] if str(item)]
    required_tools: list[str] = []
    optional_tools: list[str] = []
    for step in skill_spec.get("tool_plan_steps") or []:
        tool_name = str(step.get("tool") or "").strip()
        if not tool_name:
            continue
        if bool(step.get("required", True)):
            if tool_name not in required_tools:
                required_tools.append(tool_name)
        else:
            if tool_name not in optional_tools:
                optional_tools.append(tool_name)
    forbidden_tools = sorted(
        name for name in _toolkit_by_name().keys() if allowed_tools and name not in set(allowed_tools)
    )
    return {
        "allowed_tools": allowed_tools,
        "required_tools": required_tools,
        "optional_tools": optional_tools,
        "forbidden_tools": forbidden_tools,
    }


def _degrade_state(skill_spec: dict[str, Any], evidence_ok: bool) -> dict[str, str]:
    degrade_policy = dict(skill_spec.get("degrade_policy") or {})
    stages = {
        str(item.get("name") or ""): str(item.get("next_stage") or "none")
        for item in degrade_policy.get("stages") or []
        if str(item.get("name") or "").strip()
    }
    current_stage = "primary" if evidence_ok else str(degrade_policy.get("when_missing_evidence") or "graceful_decline")
    next_stage = stages.get(current_stage, "none")
    return {
        "current_stage": current_stage,
        "next_stage": next_stage,
    }


def _degrade_history(
    *,
    degrade_policy: dict[str, Any] | None,
    missing_reasons: list[str] | None,
    reply_mode: str,
) -> list[dict[str, Any]]:
    current_stage = str((degrade_policy or {}).get("current_stage") or "")
    if not current_stage or current_stage == "primary":
        return []
    return [
        {
            "stage": current_stage,
            "reason": "；".join(str(item) for item in (missing_reasons or []) if str(item)) or "evidence_not_sufficient",
            "entered_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "outcome": reply_mode,
        }
    ]


def _claim_type(analysis_mode: str, skill_name: str | None = None) -> str:
    normalized = str(skill_name or analysis_mode or "").lower()
    if "compare" in normalized:
        return "comparison"
    if "screen" in normalized or "selection" in normalized:
        return "screening"
    if "move" in normalized or "explain" in normalized:
        return "explanation"
    return "assessment"


def _claim_text_candidates(reply_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in (reply_text or "").splitlines():
        line = raw_line.strip().lstrip("-").lstrip("*").strip()
        if not line:
            continue
        if line.startswith("数据来源") or line.startswith("来源："):
            continue
        if len(line) < 8:
            continue
        if line not in lines:
            lines.append(line[:220])
        if len(lines) >= 3:
            break
    if lines:
        return lines

    text = (reply_text or "").strip()
    if not text:
        return []
    for sep in ("。", "\n", "；"):
        if sep in text:
            first = text.split(sep, 1)[0].strip()
            return [first[:220]] if first else []
    return [text[:220]]


def _build_claims(
    *,
    reply_text: str,
    analysis_mode: str,
    accepted_evidences: list[dict[str, Any]],
    evidence_ok: bool,
    skill_name: str | None = None,
) -> list[dict[str, Any]]:
    evidence_ids = [
        str(item.get("evidence_id") or "").strip()
        for item in accepted_evidences
        if str(item.get("evidence_id") or "").strip()
    ]
    tool_result_refs = [
        str(item.get("tool_result_id") or "").strip()
        for item in accepted_evidences
        if str(item.get("tool_result_id") or "").strip()
    ]
    base_confidence = 0.85 if evidence_ok else 0.45
    claims: list[dict[str, Any]] = []
    for idx, text in enumerate(_claim_text_candidates(reply_text), start=1):
        claims.append(
            {
                "claim_id": new_claim_id(),
                "claim_type": _claim_type(analysis_mode, skill_name),
                "claim_text": text,
                "evidence_refs": evidence_ids[:6],
                "tool_result_refs": tool_result_refs[:6],
                "confidence": round(max(0.2, base_confidence - (idx - 1) * 0.08), 2),
            }
        )
    return claims


def _build_claim_refs(claims: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for item in claims:
        claim_id = str(item.get("claim_id") or "").strip()
        if claim_id:
            refs.append(claim_id)
    return refs


def _tool_payload_artifact_refs(tool_results: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for tool_name, result in tool_results:
        if not isinstance(result, dict):
            continue
        tool_result_id = str(result.get("tool_result_id") or "").strip()
        if not tool_result_id:
            continue
        artifact = write_trace_artifact(
            "payload",
            result.get("payload"),
            file_stem=tool_result_id,
        )
        if artifact:
            refs.append(
                {
                    "tool_name": tool_name,
                    "tool_result_id": tool_result_id,
                    "payload_ref": artifact.get("path"),
                }
            )
    return refs


def _emit_policy_violation_events(
    *,
    skill_name: str | None,
    policy_violation_names: list[str],
    tool_policy: dict[str, list[str]],
    planned_tools: list[str],
) -> None:
    for tool_name in policy_violation_names:
        log_policy_violation(
            skill_name=skill_name,
            tool_name=tool_name,
            violation_type="forbidden_tool_attempt",
            resolution="blocked_before_execution",
        )

    required_tools = {str(item) for item in tool_policy.get("required_tools") or [] if str(item)}
    actual_tools = {str(item) for item in planned_tools if str(item)}
    missing_required = sorted(required_tools - actual_tools)
    for tool_name in missing_required:
        log_policy_violation(
            skill_name=skill_name,
            tool_name=tool_name,
            violation_type="required_tool_missing",
            resolution="missing_from_tool_plan",
        )


def _sop_missing_evidence_message(query: str, reasons: list[str]) -> str:
    reason_text = f"缺失原因：{'；'.join(reasons)}。" if reasons else ""
    return (
        f"这次 skill 分析还没有拿到足够的可核对证据，所以我不能可靠地下结论。{reason_text}"
        f"你可以补充更明确的基金名称，或稍后重试。原问题：{query}"
    )


def _sop_skill_prompt(
    *,
    skill_name: str,
    skill_markdown: str,
    skill_spec: dict[str, Any],
) -> str:
    return (
        f"你是一位A股投研助手，正在执行 financial-sop `{skill_name}`。\n\n"
        "执行原则：\n"
        "1. 只基于已获取到的工具证据下结论，不要编造。\n"
        "2. 严格遵守 allowed_tools 和 output_template。\n"
        "3. 若证据不足，要明确说明并走降级回复。\n"
        "4. 用中文回答，并标注数据来源为 Tushare。\n\n"
        f"【Skill SOP】\n{_strip_frontmatter(skill_markdown)[:2400]}\n\n"
        f"【Skill Spec 摘要】\n{json.dumps(skill_spec, ensure_ascii=False, default=str)[:2200]}"
    )


def _sop_reference_block(skill_name: str, user_message: str) -> str:
    refs = get_skill_registry().load_reference_texts(skill_name, user_message, limit=3)
    if not refs:
        return ""
    blocks = []
    for item in refs:
        blocks.append(
            f"- [{item['category']}] {item['title']} ({item['path']})\n{item['content'][:500]}"
        )
    return "【Skill References】\n" + "\n\n".join(blocks)


def _build_sop_synthesis_prompt(
    *,
    user_message: str,
    memory_context: str,
    running_summary: str,
    profile_summary: str,
    skill_name: str,
    skill_spec: dict[str, Any],
    skill_markdown: str,
    tool_results: list[tuple[str, dict[str, Any]]],
) -> str:
    template = _skill_output_template(skill_spec, profile_summary)
    sections = [
        "请基于下面已经获取到的工具结果生成最终回答。",
        "不要再假设未出现的数据；如果证据不足，请明确说明不能可靠判断。",
        f"【输出模板】\nsection_order={template['section_order']}\nstyle_variant={template['style_variant']}\nresponse_pref={template['response_pref']}",
        f"【Skill 名称】\n{skill_name}",
        f"【Skill SOP 摘要】\n{_strip_frontmatter(skill_markdown)[:1800]}",
    ]
    reference_block = _sop_reference_block(skill_name, user_message)
    if reference_block:
        sections.append(reference_block)
    if memory_context:
        sections.append(f"【memory_context】\n{memory_context[:1600]}")
    if running_summary:
        sections.append(f"【running_summary】\n{running_summary[:600]}")
    if profile_summary:
        sections.append(f"【用户画像摘要】\n{profile_summary}")
    tool_lines = []
    for tool_name, result in tool_results:
        tool_lines.append(f"- {tool_name}: {_serialize_tool_output(result)}")
    sections.append("【已获取工具结果】\n" + ("\n".join(tool_lines) if tool_lines else "无"))
    sections.append(f"【用户问题】\n{user_message}")
    sections.append(
        "请用中文回答，并根据 output_template 调整结构；如果回答偏好是 risk_first，先讲风险和不确定性；如果是 concise，压缩为少量关键点。"
    )
    return "\n\n".join(sections)


async def _run_sop_deterministic_execution(
    *,
    skill_name: str,
    skill_spec: dict[str, Any],
    skill_markdown: str,
    user_message: str,
    memory_context: str,
    running_summary: str,
    profile_summary: str,
    tool_plan: Any,
    concurrent: bool,
) -> tuple[str, list[tuple[str, dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    initial_calls, follow_up_calls, candidate_config = _split_sop_tool_calls(
        skill_spec=skill_spec,
        tool_plan=tool_plan,
    )
    tool_results = await _run_tool_batch(initial_calls, concurrent=concurrent)
    if follow_up_calls:
        trigger_tools = {
            str(item)
            for item in (candidate_config.get("trigger_tools") or [])
            if str(item)
        }
        candidate_symbols = _sop_candidate_symbols(
            tool_results=tool_results,
            trigger_tools=trigger_tools,
            top_n=int(candidate_config.get("top_n") or 3),
        ) if trigger_tools else []
        expanded_follow_up_calls = _expand_sop_follow_up_calls(
            follow_up_calls=follow_up_calls,
            candidate_symbols=candidate_symbols,
        )
        tool_results.extend(await _run_tool_batch(expanded_follow_up_calls, concurrent=concurrent))
    evidence_response = _build_tool_messages(tool_results)
    synthesis_prompt = _build_sop_synthesis_prompt(
        user_message=user_message,
        memory_context=memory_context,
        running_summary=running_summary,
        profile_summary=profile_summary,
        skill_name=skill_name,
        skill_spec=skill_spec,
        skill_markdown=skill_markdown,
        tool_results=tool_results,
    )
    prompt_artifact = write_trace_artifact(
        "prompt",
        synthesis_prompt,
        extension="txt",
        file_stem=f"{skill_name}_synthesis_prompt",
    )
    synthesis_model = _synthesis_model_name()
    log_model_stage(stage="synthesis", model=synthesis_model, execution_path="deterministic")
    from langchain_core.messages import HumanMessage, SystemMessage

    with trace_span(
        "synthesis",
        stage="reply",
        data={
            "model_name": synthesis_model,
            "memory_context_used": bool(memory_context),
            "running_summary_used": bool(running_summary),
            "profile_summary_used": bool(profile_summary),
            "tool_result_refs": [
                result.get("tool_result_id")
                for _, result in tool_results
                if isinstance(result, dict) and result.get("tool_result_id")
            ],
        },
    ):
        response = await _build_model(model_name=synthesis_model, temperature=0.2).ainvoke(
            [
                SystemMessage(
                    content=_sop_skill_prompt(
                        skill_name=skill_name,
                        skill_markdown=skill_markdown,
                        skill_spec=skill_spec,
                    )
                ),
                HumanMessage(content=synthesis_prompt),
            ]
        )
    reply_text = extract_final_text(response)
    reply_artifact = write_trace_artifact(
        "reply",
        str(reply_text).strip(),
        extension="txt",
        file_stem=f"{skill_name}_reply",
    )
    payload_refs = _tool_payload_artifact_refs(tool_results)
    return str(reply_text).strip(), tool_results, evidence_response, {
        "prompt_ref": prompt_artifact.get("path") if prompt_artifact else None,
        "reply_ref": reply_artifact.get("path") if reply_artifact else None,
        "payload_refs": payload_refs,
    }


async def _execute_financial_sop_skill(
    *,
    selected_skill: str,
    skill_name: str | None,
    execution_policy: str,
    user_message: str,
    effective_query: str,
    memory_context: str,
    running_summary: str,
    profile_summary: str,
    route_arguments: dict[str, Any],
    analysis_mode: str,
    enable_tool_prefetch_concurrency: bool,
    router_model: str,
    resolver_model: str,
    synthesis_model: str,
    route_confidence: float | None = None,
) -> SkillExecutionResult:
    if not skill_name:
        reply_text = "当前 financial-sop 路由没有命中具体 skill，所以这次不能可靠执行。"
        log_reply_completed(mode="skill-disabled", used_tools=False, evidence_ok=False)
        return SkillExecutionResult(
            reply_text=reply_text,
            selected_skill=selected_skill,
            trace={"enabled": False, "reason": "missing skill_name"},
        )

    registry = get_skill_registry()
    skill_spec = registry.load_skill_spec(skill_name) or {}
    skill_markdown = registry.load_skill_markdown(skill_name)
    if not skill_spec or not skill_markdown:
        reply_text = f"当前 `{skill_name}` 的 skill 资产还不完整，所以这次不能可靠执行。"
        log_reply_completed(mode="skill-disabled", used_tools=False, evidence_ok=False)
        return SkillExecutionResult(
            reply_text=reply_text,
            selected_skill=selected_skill,
            trace={"enabled": False, "reason": "missing skill assets", "skill_name": skill_name},
        )

    tool_policy = _skill_tool_policy(skill_spec)
    resolved_entities = [str(item) for item in route_arguments.get("candidate_entities") or [] if str(item)]
    with trace_span(
        "planner",
        stage="executor",
        data={
            "planner_type": "skill_planner",
            "skill_name": skill_name,
            "resolved_entities": resolved_entities,
        },
    ):
        tool_plan = build_skill_tool_plan(
            skill_name=skill_name,
            skill_spec=skill_spec,
            user_message=effective_query,
            resolved_entities=resolved_entities,
        )
    original_planned_tools = [item.tool_name for item in tool_plan.tool_calls]
    policy_violation_names = _policy_violation_names(original_planned_tools, tool_policy["allowed_tools"])
    allowed_tools = set(tool_policy["allowed_tools"])
    tool_plan.tool_calls = [
        item for item in tool_plan.tool_calls if item.tool_name in allowed_tools
    ]
    planned_tools = [item.tool_name for item in tool_plan.tool_calls]
    execution_path = "hybrid" if execution_policy == "hybrid" else "deterministic"
    initial_degrade_policy = _degrade_state(skill_spec, True)
    _emit_policy_violation_events(
        skill_name=skill_name,
        policy_violation_names=policy_violation_names,
        tool_policy=tool_policy,
        planned_tools=planned_tools,
    )
    log_tool_plan(
        planner_type=tool_plan.planner_type,
        analysis_mode=analysis_mode,
        planned_tools=planned_tools,
        references=[item["title"] for item in tool_plan.references],
        execution_path=execution_path,
        tool_batch_size=len(tool_plan.tool_calls),
        tool_policy={
            "required_tools": tool_policy["required_tools"],
            "optional_tools": tool_policy["optional_tools"],
            "forbidden_tools": tool_policy["forbidden_tools"],
        },
        degrade_policy=initial_degrade_policy,
        policy_violation_count=len(policy_violation_names),
        policy_violations=policy_violation_names,
    )

    if not tool_plan.tool_calls:
        reasons = ["no tool calls generated from skill_spec"]
        reply_text = _sop_missing_evidence_message(user_message, reasons)
        degrade_policy = _degrade_state(skill_spec, False)
        degrade_history = _degrade_history(
            degrade_policy=degrade_policy,
            missing_reasons=reasons,
            reply_mode="evidence-missing",
        )
        if degrade_history:
            for item in degrade_history:
                log_degrade_transition(
                    skill_name=skill_name,
                    analysis_mode=analysis_mode,
                    stage=item["stage"],
                    reason=item["reason"],
                    outcome=item["outcome"],
                )
        observability_metrics = _execution_observability_metrics(
            route_confidence=route_confidence,
            planned_tool_names=planned_tools,
            tool_results=[],
            degrade_policy=degrade_policy,
            policy_violation_names=policy_violation_names,
            evidence_ok=False,
        )
        log_reply_completed(
            mode="evidence-missing",
            used_tools=False,
            evidence_ok=False,
            missing_evidence_reasons=reasons,
            degrade_policy=degrade_policy,
        )
        return SkillExecutionResult(
            reply_text=reply_text,
            selected_skill=selected_skill,
            trace={
                "selected_skill_family": "financial-sop",
                "skill_name": skill_name,
                "analysis_mode": analysis_mode,
                "execution_policy": execution_policy,
                "execution_path": execution_path,
                "planner_type": tool_plan.planner_type,
                "planned_tools": planned_tools,
                "tool_policy": tool_policy,
                "degrade_policy": degrade_policy,
                "degrade_history": degrade_history,
                "final_degrade_outcome": degrade_history[-1]["outcome"] if degrade_history else "not_triggered",
                "evidence_ok": False,
                "evidence_refs": [],
                "reply_mode": "evidence-missing",
                "policy_violations": policy_violation_names,
                "available_tool_names": tool_policy["allowed_tools"],
                "official_skill_source": f"workspace:{skill_name}",
                **observability_metrics,
            },
        )

    try:
        reply_mode = "skill"
        if execution_path == "hybrid":
            reply_text, tool_results, evidence_response, artifact_refs = await _run_sop_deterministic_execution(
                skill_name=skill_name,
                skill_spec=skill_spec,
                skill_markdown=skill_markdown,
                user_message=effective_query,
                memory_context=memory_context,
                running_summary=running_summary,
                profile_summary=profile_summary,
                tool_plan=tool_plan,
                concurrent=enable_tool_prefetch_concurrency,
            )
        else:
            reply_text, tool_results, evidence_response, artifact_refs = await _run_sop_deterministic_execution(
                skill_name=skill_name,
                skill_spec=skill_spec,
                skill_markdown=skill_markdown,
                user_message=effective_query,
                memory_context=memory_context,
                running_summary=running_summary,
                profile_summary=profile_summary,
                tool_plan=tool_plan,
                concurrent=enable_tool_prefetch_concurrency,
            )
        with trace_span(
            "evidence",
            stage="executor",
            data={
                "planner_type": tool_plan.planner_type,
                "planned_tools": planned_tools,
            },
        ):
            evidence = validate_evidence(
                analysis_mode=analysis_mode,
                resolved_symbol=None,
                response=evidence_response,
                skill_spec=skill_spec,
            )
        claims = _build_claims(
            reply_text=reply_text,
            analysis_mode=analysis_mode,
            accepted_evidences=evidence.accepted_evidences,
            evidence_ok=evidence.evidence_ok,
            skill_name=skill_name,
        )
        claim_artifact = write_trace_artifact(
            "claims",
            claims,
            file_stem=f"{skill_name}_claims",
        )
        if claims:
            log_claim_lineage(
                skill_name=skill_name,
                analysis_mode=analysis_mode,
                claim_count=len(claims),
                claim_ids=_build_claim_refs(claims),
            )
        used_tools = evidence.used_tools
        degrade_policy = _degrade_state(skill_spec, evidence.evidence_ok)
        degrade_history = _degrade_history(
            degrade_policy=degrade_policy,
            missing_reasons=evidence.missing_evidence_reasons,
            reply_mode=reply_mode,
        )
        if degrade_history:
            for item in degrade_history:
                log_degrade_transition(
                    skill_name=skill_name,
                    analysis_mode=analysis_mode,
                    stage=item["stage"],
                    reason=item["reason"],
                    outcome=item["outcome"],
                )
        observability_metrics = _execution_observability_metrics(
            route_confidence=route_confidence,
            planned_tool_names=planned_tools,
            tool_results=tool_results,
            degrade_policy=degrade_policy,
            policy_violation_names=policy_violation_names,
            evidence_ok=evidence.evidence_ok,
        )
        if not evidence.evidence_ok:
            reply_mode = "evidence-missing"
            reply_text = _sop_missing_evidence_message(user_message, evidence.missing_evidence_reasons)
            log_reply_completed(
                mode="evidence-missing",
                used_tools=used_tools,
                successful_tools=evidence.successful_tools,
                evidence_ok=evidence.evidence_ok,
                missing_evidence_reasons=evidence.missing_evidence_reasons,
                accepted_evidences=evidence.accepted_evidences,
                rejected_evidences=evidence.rejected_evidences,
                degrade_policy=degrade_policy,
            )
        else:
            log_reply_completed(
                mode="skill",
                used_tools=used_tools,
                successful_tools=evidence.successful_tools,
                evidence_ok=evidence.evidence_ok,
                accepted_evidences=evidence.accepted_evidences,
                rejected_evidences=evidence.rejected_evidences,
                degrade_policy=degrade_policy,
            )
    except Exception as exc:
        logger.warning("[skill_executor] financial-sop invoke failed: %s", exc, exc_info=True)
        reply_mode = "skill-error"
        reply_text = _format_tool_failure_message(user_message, str(exc))
        tool_results = []
        artifact_refs = {"prompt_ref": None, "reply_ref": None, "payload_refs": []}
        with trace_span(
            "evidence",
            stage="executor",
            data={
                "planner_type": tool_plan.planner_type,
                "planned_tools": planned_tools,
            },
        ):
            evidence = validate_evidence(
                analysis_mode=analysis_mode,
                resolved_symbol=None,
                response={"messages": []},
                skill_spec=skill_spec,
            )
        used_tools = False
        degrade_policy = _degrade_state(skill_spec, False)
        degrade_history = _degrade_history(
            degrade_policy=degrade_policy,
            missing_reasons=evidence.missing_evidence_reasons,
            reply_mode=reply_mode,
        )
        claims = []
        claim_artifact = None
        if degrade_history:
            for item in degrade_history:
                log_degrade_transition(
                    skill_name=skill_name,
                    analysis_mode=analysis_mode,
                    stage=item["stage"],
                    reason=item["reason"],
                    outcome=item["outcome"],
                )
        observability_metrics = _execution_observability_metrics(
            route_confidence=route_confidence,
            planned_tool_names=planned_tools,
            tool_results=tool_results,
            degrade_policy=degrade_policy,
            policy_violation_names=policy_violation_names,
            evidence_ok=False,
        )
        log_reply_completed(mode="skill-error", used_tools=False, error=str(exc), evidence_ok=False)

    return SkillExecutionResult(
        reply_text=reply_text.strip(),
        selected_skill=selected_skill,
        trace={
            "selected_skill_family": "financial-sop",
            "selected_skill": selected_skill,
            "skill_name": skill_name,
            "analysis_mode": analysis_mode,
            "execution_policy": execution_policy,
            "execution_path": execution_path,
            "planner_type": tool_plan.planner_type,
            "planned_tools": planned_tools,
            "tool_batch_size": len(tool_plan.tool_calls),
            "tool_policy": tool_policy,
            "degrade_policy": degrade_policy,
            "degrade_stage": degrade_policy.get("current_stage"),
            "evidence_ok": evidence.evidence_ok,
            "missing_evidence_reasons": evidence.missing_evidence_reasons,
            "evidence_refs": evidence.accepted_evidences,
            "accepted_evidences": evidence.accepted_evidences,
            "rejected_evidences": evidence.rejected_evidences,
            "claims": claims,
            "claim_refs": _build_claim_refs(claims),
            "degrade_history": degrade_history,
            "final_degrade_outcome": degrade_history[-1]["outcome"] if degrade_history else "not_triggered",
            "reply_mode": reply_mode,
            "policy_violations": policy_violation_names,
            "router_model": router_model,
            "resolver_model": resolver_model,
            "synthesis_model": synthesis_model,
            "reference_titles": [item["title"] for item in tool_plan.references],
            "available_tool_names": tool_policy["allowed_tools"],
            "prefetched_tool_names": [tool_name for tool_name, _ in tool_results],
            "official_skill_source": f"workspace:{skill_name}",
            "prompt_ref": artifact_refs.get("prompt_ref"),
            "reply_ref": artifact_refs.get("reply_ref"),
            "payload_refs": artifact_refs.get("payload_refs") or [],
            "claim_ref": claim_artifact.get("path") if claim_artifact else None,
            **observability_metrics,
        },
    )


async def _invoke_tool(tool_name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool = _toolkit_by_name().get(tool_name)
    if tool is None:
        return tool_name, {
            "ok": False,
            "source": "tushare",
            "trade_date": None,
            "data_time": None,
            "symbol": arguments.get("symbol") or arguments.get("query") or "",
            "payload": {},
            "error": f"tool not found: {tool_name}",
        }
    result = await tool.ainvoke(arguments)
    if isinstance(result, dict):
        return tool_name, result
    return tool_name, {
        "ok": False,
        "source": "tushare",
        "trade_date": None,
        "data_time": None,
        "symbol": arguments.get("symbol") or arguments.get("query") or "",
        "payload": {},
        "error": f"unexpected tool result type: {type(result).__name__}",
    }


async def _run_tool_batch(
    tool_calls: list[dict[str, Any]],
    *,
    concurrent: bool,
) -> list[tuple[str, dict[str, Any]]]:
    if not tool_calls:
        return []
    if concurrent:
        results = await asyncio.gather(
            *[_invoke_tool(item["tool_name"], item["arguments"]) for item in tool_calls],
            return_exceptions=True,
        )
    else:
        results = []
        for item in tool_calls:
            results.append(await _invoke_tool(item["tool_name"], item["arguments"]))

    normalized: list[tuple[str, dict[str, Any]]] = []
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            original = tool_calls[idx]
            normalized.append(
                (
                    original["tool_name"],
                    {
                        "ok": False,
                        "source": "tushare",
                        "trade_date": None,
                        "data_time": None,
                        "symbol": original["arguments"].get("symbol") or original["arguments"].get("query") or "",
                        "payload": {},
                        "error": str(result),
                    },
                )
            )
            continue
        normalized.append(result)
    return normalized


def _build_tool_messages(tool_results: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return {
        "messages": [
            _ToolMessageLike(
                name=tool_name,
                content=json.dumps(result, ensure_ascii=False, default=str),
            )
            for tool_name, result in tool_results
        ]
    }


def _deterministic_candidate_symbols(
    basic_result: dict[str, Any],
    *,
    top_n: int = 3,
) -> list[str]:
    payload = basic_result.get("payload") if isinstance(basic_result, dict) else []
    if not isinstance(payload, list):
        return []
    symbols: list[str] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        ts_code = str(row.get("ts_code") or "").strip()
        if ts_code and ts_code not in symbols:
            symbols.append(ts_code)
        if len(symbols) >= top_n:
            break
    return symbols


def _sop_candidate_expansion_config(skill_spec: dict[str, Any]) -> dict[str, Any]:
    config = skill_spec.get("candidate_expansion") or {}
    return config if isinstance(config, dict) else {}


def _split_sop_tool_calls(
    *,
    skill_spec: dict[str, Any],
    tool_plan: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    config = _sop_candidate_expansion_config(skill_spec)
    trigger_tools = {
        str(item)
        for item in (config.get("trigger_tools") or [])
        if str(item)
    }
    all_calls = [
        {
            "tool_name": item.tool_name,
            "arguments": dict(item.arguments),
            "required": item.required,
        }
        for item in tool_plan.tool_calls
    ]
    if not trigger_tools:
        return all_calls, [], config

    initial_calls = [item for item in all_calls if item["tool_name"] in trigger_tools]
    follow_up_calls = [item for item in all_calls if item["tool_name"] not in trigger_tools]
    if not initial_calls:
        return all_calls, [], config
    return initial_calls, follow_up_calls, config


def _sop_candidate_symbols(
    *,
    tool_results: list[tuple[str, dict[str, Any]]],
    trigger_tools: set[str],
    top_n: int,
) -> list[str]:
    symbols: list[str] = []
    for tool_name, result in tool_results:
        if tool_name not in trigger_tools:
            continue
        for symbol in _deterministic_candidate_symbols(result, top_n=top_n):
            if symbol and symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= top_n:
                return symbols
    return symbols


def _expand_sop_follow_up_calls(
    *,
    follow_up_calls: list[dict[str, Any]],
    candidate_symbols: list[str],
) -> list[dict[str, Any]]:
    if not follow_up_calls:
        return []
    if not candidate_symbols:
        return follow_up_calls

    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in follow_up_calls:
        base_args = dict(item["arguments"])
        if base_args.get("symbol") or "query" not in base_args:
            key = f"{item['tool_name']}|{sorted(base_args.items())}"
            if key not in seen:
                seen.add(key)
                expanded.append(item)
            continue
        for symbol in candidate_symbols:
            args = dict(base_args)
            args.pop("query", None)
            args["symbol"] = symbol
            key = f"{item['tool_name']}|{sorted(args.items())}"
            if key in seen:
                continue
            seen.add(key)
            expanded.append(
                {
                    "tool_name": item["tool_name"],
                    "arguments": args,
                    "required": item["required"],
                }
            )
    return expanded


def _deterministic_follow_up_calls(
    *,
    analysis_mode: str,
    tool_plan: Any,
    basic_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if analysis_mode == "stock_selection" and isinstance(basic_result, dict):
        candidate_symbols = _deterministic_candidate_symbols(basic_result, top_n=3)
        for symbol in candidate_symbols:
            for item in tool_plan.tool_calls:
                if item.tool_name not in {"get_fund_nav", "get_fund_share", "get_fund_market_bars"}:
                    continue
                args = dict(item.arguments)
                args.pop("query", None)
                args["symbol"] = symbol
                calls.append({"tool_name": item.tool_name, "arguments": args, "required": item.required})
        return calls

    for item in tool_plan.tool_calls:
        calls.append({"tool_name": item.tool_name, "arguments": dict(item.arguments), "required": item.required})
    return calls


def _deterministic_initial_calls(tool_plan: Any) -> list[dict[str, Any]]:
    if tool_plan.analysis_mode == "stock_selection":
        for item in tool_plan.tool_calls:
            if item.tool_name == "get_fund_basic_info":
                return [{"tool_name": item.tool_name, "arguments": dict(item.arguments), "required": True}]
        return []
    return _deterministic_follow_up_calls(analysis_mode=tool_plan.analysis_mode, tool_plan=tool_plan)


def _build_synthesis_prompt(
    *,
    user_message: str,
    memory_context: str,
    running_summary: str,
    profile_summary: str,
    selected_skill: str,
    analysis_mode: str,
    resolved_company: str | None,
    resolved_symbol: str | None,
    tool_results: list[tuple[str, dict[str, Any]]],
) -> str:
    meta = get_skill_registry().get_skill(_source_skill_name(selected_skill))
    sections = [
        "请基于下面已经获取到的 Tushare 数据生成最终回答。",
        "不要再假设未出现的数据；如果证据不足，请明确说明不能可靠判断。",
    ]
    style = _analysis_style_guidance(analysis_mode)
    if style:
        sections.append(style)
    if meta:
        sections.append(f"【技能描述】\n{meta.description}")
    if memory_context:
        sections.append(f"【memory_context】\n{memory_context[:1600]}")
    if running_summary:
        sections.append(f"【running_summary】\n{running_summary[:600]}")
    if profile_summary:
        sections.append(f"【用户画像摘要】\n{profile_summary}")
    if resolved_company or resolved_symbol:
        sections.append(
            f"【已解析标的】\ncompany={resolved_company or 'unknown'}\nsymbol={resolved_symbol or 'unknown'}"
        )
    tool_lines = []
    for tool_name, result in tool_results:
        tool_lines.append(f"- {tool_name}: {_serialize_tool_output(result)}")
    sections.append("【已获取工具结果】\n" + ("\n".join(tool_lines) if tool_lines else "无"))
    sections.append(f"【用户问题】\n{user_message}")
    sections.append("请用中文回答，并在使用数据时标注数据来源：Tushare，以及数据时间或财报期。")
    return "\n\n".join(sections)


async def _run_deterministic_skill_execution(
    *,
    user_message: str,
    memory_context: str,
    running_summary: str,
    profile_summary: str,
    selected_skill: str,
    analysis_mode: str,
    tool_plan: Any,
    resolved_company: str | None,
    resolved_symbol: str | None,
    concurrent: bool,
) -> tuple[str, list[tuple[str, dict[str, Any]]], Any, dict[str, Any]]:
    initial_calls = _deterministic_initial_calls(tool_plan)
    tool_results = await _run_tool_batch(initial_calls, concurrent=concurrent)

    if analysis_mode == "stock_selection":
        basic_result = next((result for tool_name, result in tool_results if tool_name == "get_fund_basic_info"), None)
        follow_up_calls = _deterministic_follow_up_calls(
            analysis_mode=analysis_mode,
            tool_plan=tool_plan,
            basic_result=basic_result,
        )
        tool_results.extend(await _run_tool_batch(follow_up_calls, concurrent=concurrent))

    evidence_response = _build_tool_messages(tool_results)
    synthesis_prompt = _build_synthesis_prompt(
        user_message=user_message,
        memory_context=memory_context,
        running_summary=running_summary,
        profile_summary=profile_summary,
        selected_skill=selected_skill,
        analysis_mode=analysis_mode,
        resolved_company=resolved_company,
        resolved_symbol=resolved_symbol,
        tool_results=tool_results,
    )
    prompt_artifact = write_trace_artifact(
        "prompt",
        synthesis_prompt,
        extension="txt",
        file_stem=f"{selected_skill}_{analysis_mode}_prompt",
    )
    synthesis_model = _synthesis_model_name()
    log_model_stage(stage="synthesis", model=synthesis_model, execution_path="deterministic")
    from langchain_core.messages import HumanMessage, SystemMessage

    with trace_span(
        "synthesis",
        stage="reply",
        data={
            "model_name": synthesis_model,
            "memory_context_used": bool(memory_context),
            "running_summary_used": bool(running_summary),
            "profile_summary_used": bool(profile_summary),
            "tool_result_refs": [
                result.get("tool_result_id")
                for _, result in tool_results
                if isinstance(result, dict) and result.get("tool_result_id")
            ],
        },
    ):
        response = await _build_model(model_name=synthesis_model, temperature=0.2).ainvoke(
            [
                SystemMessage(content=_skill_prompt(selected_skill, get_skill_registry().get_skill(_source_skill_name(selected_skill)).skill_file if get_skill_registry().get_skill(_source_skill_name(selected_skill)) else None)),
                HumanMessage(content=synthesis_prompt),
            ]
        )
    reply_text = extract_final_text(response)
    reply_artifact = write_trace_artifact(
        "reply",
        str(reply_text).strip(),
        extension="txt",
        file_stem=f"{selected_skill}_{analysis_mode}_reply",
    )
    payload_refs = _tool_payload_artifact_refs(tool_results)
    return str(reply_text).strip(), tool_results, evidence_response, {
        "prompt_ref": prompt_artifact.get("path") if prompt_artifact else None,
        "reply_ref": reply_artifact.get("path") if reply_artifact else None,
        "payload_refs": payload_refs,
    }


async def execute_skill(
    *,
    selected_skill: str,
    user_message: str,
    memory_context: str = "",
    running_summary: str = "",
    profile_summary: str = "",
    session_id: str | None = None,
    user_id: str | None = None,
    route_trace: dict[str, Any] | None = None,
    enable_tushare_skills: bool = False,
    enable_tushare_planner: bool = False,
    enable_tushare_market_tools: bool = False,
    enable_tushare_index_tools: bool = False,
    enable_tushare_sector_tools: bool = False,
    enable_fundamental_analysis: bool = False,
    enable_sector_analysis: bool = False,
    enable_stock_selection: bool = False,
    enable_deterministic_skill_execution: bool = True,
    enable_tool_prefetch_concurrency: bool = True,
) -> SkillExecutionResult:
    enabled_map = {
        "fallback": True,
        "tushare-data": enable_tushare_skills,
        "financial-sop": True,
    }
    analysis_mode = str((route_trace or {}).get("analysis_mode") or "general_chat")
    selected_skill_family = str((route_trace or {}).get("selected_skill_family") or selected_skill)
    skill_name = (route_trace or {}).get("skill_name")
    execution_policy = str((route_trace or {}).get("execution_policy") or "")
    route_confidence = float((route_trace or {}).get("confidence") or 0.0)
    route_arguments = (route_trace or {}).get("arguments") or {}
    effective_query = str(route_arguments.get("effective_query") or user_message).strip() or user_message
    is_fund_query = _contains_any(effective_query, ("基金", "etf", "lof", "qdii", "联接"))
    execution_path = "deterministic" if _should_use_deterministic_path(
        analysis_mode=analysis_mode,
        is_fund_query=is_fund_query,
        enable_deterministic_skill_execution=enable_deterministic_skill_execution,
        enable_tushare_planner=enable_tushare_planner,
    ) else "agentic"
    if selected_skill_family == "financial-sop":
        execution_path = "hybrid" if execution_policy == "hybrid" else "deterministic"
    router_model = str(route_arguments.get("router_model") or _router_model_name())
    resolver_model = _resolver_model_name()
    synthesis_model = _synthesis_model_name()

    with skill_trace_context(
        session_id=session_id,
        user_id=user_id,
        selected_skill_family=selected_skill_family,
        selected_skill=selected_skill,
        skill_name=skill_name,
        analysis_mode=analysis_mode,
        execution_policy=execution_policy,
        needs_realtime_data=(route_trace or {}).get("needs_realtime_data"),
        execution_path=execution_path,
        router_model=router_model,
        resolver_model=resolver_model,
        synthesis_model=synthesis_model,
    ):
        log_skill_selected(
            enabled=enabled_map.get(selected_skill, False),
            why=(route_trace or {}).get("why"),
            confidence=(route_trace or {}).get("confidence"),
        )

        if selected_skill == "fallback":
            return SkillExecutionResult(
                reply_text="",
                selected_skill="fallback",
                trace={"reason": "fallback route"},
                used_fallback=True,
            )

        if selected_skill_family == "financial-sop":
            return await _execute_financial_sop_skill(
                selected_skill=selected_skill,
                skill_name=skill_name,
                execution_policy=execution_policy or "deterministic",
                user_message=user_message,
                effective_query=effective_query,
                memory_context=memory_context,
                running_summary=running_summary,
                profile_summary=profile_summary,
                route_arguments=route_arguments,
                analysis_mode=analysis_mode,
                enable_tool_prefetch_concurrency=enable_tool_prefetch_concurrency,
                router_model=router_model,
                resolver_model=resolver_model,
                synthesis_model=synthesis_model,
                route_confidence=route_confidence,
            )

        if not enabled_map.get(selected_skill, False) or not _mode_enabled(
            analysis_mode,
            enable_fundamental_analysis=enable_fundamental_analysis,
            enable_sector_analysis=enable_sector_analysis,
            enable_stock_selection=enable_stock_selection,
        ):
            capability_note = _skill_capability_note(selected_skill, user_message)
            reply_text = _unsupported_message(selected_skill, analysis_mode, user_message)
            if capability_note:
                reply_text = f"{reply_text}\n\n{capability_note}"
            log_reply_completed(mode="skill-disabled", used_tools=False)
            return SkillExecutionResult(
                reply_text=reply_text,
                selected_skill=selected_skill,
                trace={"enabled": False, "reason": "skill disabled"},
            )

        company_name = None
        stock_code = None
        if analysis_mode in {"single_stock_data", "single_stock_fundamental"} and not is_fund_query:
            try:
                from backend.services.stock_resolver import resolve_stock

                log_model_stage(stage="resolver", model=resolver_model, execution_path=execution_path)
                company_name, stock_code = await resolve_stock(effective_query)
            except Exception as exc:
                logger.warning("[skill_executor] pre-resolve hint failed: %s", exc)

        with trace_span(
            "planner",
            stage="executor",
            data={
                "planner_type": "fallback_planner",
                "analysis_mode": analysis_mode,
                "selected_skill": selected_skill,
            },
        ):
            tool_plan = build_tushare_tool_plan(
                user_message=effective_query,
                analysis_mode=analysis_mode,
                resolved_symbol=stock_code,
                enable_market_tools=enable_tushare_market_tools,
                enable_index_tools=enable_tushare_index_tools,
                enable_sector_tools=enable_tushare_sector_tools,
            )
        if not enable_tushare_planner:
            tool_plan.tool_calls = []
        log_tool_plan(
            planner_type=tool_plan.planner_type,
            analysis_mode=analysis_mode,
            planned_tools=[item.tool_name for item in tool_plan.tool_calls],
            references=[item["title"] for item in tool_plan.references],
            execution_path=execution_path,
            tool_batch_size=len(tool_plan.tool_calls),
        )
        planned_tools = _toolkit_for_plan([item.tool_name for item in tool_plan.tool_calls]) or get_tushare_toolkit()

        prompt = _build_prompt(
            user_message=effective_query,
            memory_context=memory_context,
            running_summary=running_summary,
            profile_summary=profile_summary,
            resolved_company=company_name,
            resolved_symbol=stock_code,
            selected_skill=selected_skill,
            analysis_mode=analysis_mode,
            tool_plan_summary=_summarize_tool_plan(tool_plan),
        )

        try:
            reply_mode = "skill"
            if execution_path == "deterministic":
                reply_text, tool_results, evidence_response, artifact_refs = await _run_deterministic_skill_execution(
                    user_message=effective_query,
                    memory_context=memory_context,
                    running_summary=running_summary,
                    profile_summary=profile_summary,
                    selected_skill=selected_skill,
                    analysis_mode=analysis_mode,
                    tool_plan=tool_plan,
                    resolved_company=company_name,
                    resolved_symbol=stock_code,
                    concurrent=enable_tool_prefetch_concurrency,
                )
                response = evidence_response
            else:
                source_skill = _source_skill_name(selected_skill)
                log_model_stage(stage="synthesis", model=synthesis_model, execution_path=execution_path)
                agent = build_analysis_agent(
                    model=_build_model(model_name=synthesis_model),
                    tools=planned_tools,
                    system_prompt=_skill_prompt(
                        selected_skill,
                        get_skill_registry().get_skill(source_skill).skill_file
                        if get_skill_registry().get_skill(source_skill)
                        else None,
                    ),
                )
                with trace_span(
                    "synthesis",
                    stage="reply",
                    data={
                        "model_name": synthesis_model,
                        "memory_context_used": bool(memory_context),
                        "running_summary_used": bool(running_summary),
                        "profile_summary_used": bool(profile_summary),
                    },
                ):
                    response = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
                reply_text = extract_final_text(response)
                tool_results = []
                prompt_artifact = write_trace_artifact(
                    "prompt",
                    prompt,
                    extension="txt",
                    file_stem=f"{selected_skill}_{analysis_mode}_agent_prompt",
                )
                reply_artifact = write_trace_artifact(
                    "reply",
                    str(reply_text).strip(),
                    extension="txt",
                    file_stem=f"{selected_skill}_{analysis_mode}_agent_reply",
                )
                artifact_refs = {
                    "prompt_ref": prompt_artifact.get("path") if prompt_artifact else None,
                    "reply_ref": reply_artifact.get("path") if reply_artifact else None,
                    "payload_refs": [],
                }
            with trace_span(
                "evidence",
                stage="executor",
                data={
                    "planner_type": tool_plan.planner_type,
                    "planned_tools": [item.tool_name for item in tool_plan.tool_calls],
                },
            ):
                evidence = validate_evidence(
                    analysis_mode=analysis_mode,
                    resolved_symbol=stock_code,
                    response=response,
                )
            claims = _build_claims(
                reply_text=reply_text,
                analysis_mode=analysis_mode,
                accepted_evidences=evidence.accepted_evidences,
                evidence_ok=evidence.evidence_ok,
                skill_name=selected_skill,
            )
            claim_artifact = write_trace_artifact(
                "claims",
                claims,
                file_stem=f"{selected_skill}_{analysis_mode}_claims",
            )
            if claims:
                log_claim_lineage(
                    skill_name=selected_skill,
                    analysis_mode=analysis_mode,
                    claim_count=len(claims),
                    claim_ids=_build_claim_refs(claims),
                )
            used_tools = evidence.used_tools or _response_used_tools(response)
            degrade_policy = {
                "current_stage": "primary" if evidence.evidence_ok else "graceful_decline",
                "next_stage": "none",
            }
            degrade_history = _degrade_history(
                degrade_policy=degrade_policy,
                missing_reasons=evidence.missing_evidence_reasons,
                reply_mode=reply_mode,
            )
            if degrade_history:
                for item in degrade_history:
                    log_degrade_transition(
                        skill_name=selected_skill,
                        analysis_mode=analysis_mode,
                        stage=item["stage"],
                        reason=item["reason"],
                        outcome=item["outcome"],
                    )
            observability_metrics = _execution_observability_metrics(
                route_confidence=route_confidence,
                planned_tool_names=[item.tool_name for item in tool_plan.tool_calls],
                tool_results=tool_results,
                degrade_policy=degrade_policy,
                policy_violation_names=[],
                evidence_ok=evidence.evidence_ok,
            )
            if _needs_verifiable_data(effective_query) and not evidence.evidence_ok:
                reply_mode = "evidence-missing"
                reply_text = _missing_evidence_message(user_message)
                log_reply_completed(
                    mode="evidence-missing",
                    used_tools=used_tools,
                    successful_tools=evidence.successful_tools,
                    evidence_ok=evidence.evidence_ok,
                    missing_evidence_reasons=evidence.missing_evidence_reasons,
                )
            else:
                log_reply_completed(
                    mode="skill",
                    used_tools=used_tools,
                    successful_tools=evidence.successful_tools,
                    evidence_ok=evidence.evidence_ok,
                )
        except Exception as exc:
            logger.warning("[skill_executor] agent invoke failed: %s", exc, exc_info=True)
            reply_mode = "skill-error"
            reply_text = _format_tool_failure_message(user_message, str(exc))
            used_tools = False
            tool_results = []
            artifact_refs = {"prompt_ref": None, "reply_ref": None, "payload_refs": []}
            evidence = validate_evidence(
                analysis_mode=analysis_mode,
                resolved_symbol=stock_code,
                response={"messages": []},
            )
            degrade_policy = {
                "current_stage": "graceful_decline",
                "next_stage": "none",
            }
            degrade_history = _degrade_history(
                degrade_policy=degrade_policy,
                missing_reasons=evidence.missing_evidence_reasons,
                reply_mode=reply_mode,
            )
            claims = []
            claim_artifact = None
            if degrade_history:
                for item in degrade_history:
                    log_degrade_transition(
                        skill_name=selected_skill,
                        analysis_mode=analysis_mode,
                        stage=item["stage"],
                        reason=item["reason"],
                        outcome=item["outcome"],
                    )
            observability_metrics = _execution_observability_metrics(
                route_confidence=route_confidence,
                planned_tool_names=[item.tool_name for item in tool_plan.tool_calls],
                tool_results=tool_results,
                degrade_policy=degrade_policy,
                policy_violation_names=[],
                evidence_ok=False,
            )
            log_reply_completed(mode="skill-error", used_tools=False, error=str(exc), evidence_ok=False)

        return SkillExecutionResult(
            reply_text=reply_text.strip(),
            selected_skill=selected_skill,
            trace={
                "selected_skill_family": selected_skill_family,
                "skill_name": skill_name,
                "resolved_company": company_name,
                "resolved_symbol": stock_code,
                "used_tools": used_tools,
                "skill_aliases": get_skill_registry().get_skill(_source_skill_name(selected_skill)).aliases
                if get_skill_registry().get_skill(_source_skill_name(selected_skill))
                else [],
                "analysis_mode": analysis_mode,
                "execution_policy": execution_policy,
                "execution_path": execution_path,
                "planner_type": tool_plan.planner_type,
                "planned_tools": [item.tool_name for item in tool_plan.tool_calls],
                "tool_batch_size": len(tool_plan.tool_calls),
                "evidence_ok": bool(locals().get("evidence").evidence_ok) if "evidence" in locals() else False,
                "missing_evidence_reasons": getattr(locals().get("evidence"), "missing_evidence_reasons", []),
                "accepted_evidences": getattr(locals().get("evidence"), "accepted_evidences", []),
                "rejected_evidences": getattr(locals().get("evidence"), "rejected_evidences", []),
                "evidence_refs": getattr(locals().get("evidence"), "accepted_evidences", []),
                "claims": locals().get("claims", []),
                "claim_refs": _build_claim_refs(locals().get("claims", [])),
                "degrade_policy": locals().get("degrade_policy", {}),
                "degrade_stage": (locals().get("degrade_policy") or {}).get("current_stage"),
                "degrade_history": locals().get("degrade_history", []),
                "final_degrade_outcome": (locals().get("degrade_history") or [{}])[-1].get("outcome") if locals().get("degrade_history") else "not_triggered",
                "reply_mode": locals().get("reply_mode", "skill"),
                "router_model": router_model,
                "resolver_model": resolver_model,
                "synthesis_model": synthesis_model,
                "reference_titles": [
                    item["title"]
                    for item in get_skill_registry().find_references(
                        _source_skill_name(selected_skill),
                        effective_query,
                        limit=5,
                    )
                ],
                "available_tool_names": [getattr(tool, "name", getattr(tool, "__name__", "unknown")) for tool in planned_tools],
                "prefetched_tool_names": [tool_name for tool_name, _ in tool_results],
                "official_skill_source": "vendor/tushare-skills/tushare",
                "prompt_ref": artifact_refs.get("prompt_ref"),
                "reply_ref": artifact_refs.get("reply_ref"),
                "payload_refs": artifact_refs.get("payload_refs") or [],
                "claim_ref": claim_artifact.get("path") if locals().get("claim_artifact") else None,
                **observability_metrics,
            },
        )
