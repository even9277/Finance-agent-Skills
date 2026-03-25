from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agents.agent_factory import build_analysis_agent
from src.agents.response_normalizer import extract_final_text
from src.agents.skill_evidence import validate_evidence
from src.agents.tushare_reference_planner import build_tushare_tool_plan
from src.skills.skill_registry import get_skill_registry
from src.tools.chat_tushare_tools import get_tushare_toolkit
from src.tools.skill_trace import (
    log_model_stage,
    log_reply_completed,
    log_skill_selected,
    log_tool_plan,
    skill_trace_context,
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
) -> tuple[str, list[tuple[str, dict[str, Any]]], Any]:
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
    synthesis_model = _synthesis_model_name()
    log_model_stage(stage="synthesis", model=synthesis_model, execution_path="deterministic")
    from langchain_core.messages import HumanMessage, SystemMessage

    response = await _build_model(model_name=synthesis_model, temperature=0.2).ainvoke(
        [
            SystemMessage(content=_skill_prompt(selected_skill, get_skill_registry().get_skill(_source_skill_name(selected_skill)).skill_file if get_skill_registry().get_skill(_source_skill_name(selected_skill)) else None)),
            HumanMessage(content=synthesis_prompt),
        ]
    )
    reply_text = extract_final_text(response)
    return str(reply_text).strip(), tool_results, evidence_response


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
    }
    analysis_mode = str((route_trace or {}).get("analysis_mode") or "general_chat")
    route_arguments = (route_trace or {}).get("arguments") or {}
    effective_query = str(route_arguments.get("effective_query") or user_message).strip() or user_message
    is_fund_query = _contains_any(effective_query, ("基金", "etf", "lof", "qdii", "联接"))
    execution_path = "deterministic" if _should_use_deterministic_path(
        analysis_mode=analysis_mode,
        is_fund_query=is_fund_query,
        enable_deterministic_skill_execution=enable_deterministic_skill_execution,
        enable_tushare_planner=enable_tushare_planner,
    ) else "agentic"
    router_model = str(route_arguments.get("router_model") or _router_model_name())
    resolver_model = _resolver_model_name()
    synthesis_model = _synthesis_model_name()

    with skill_trace_context(
        session_id=session_id,
        user_id=user_id,
        selected_skill=selected_skill,
        analysis_mode=analysis_mode,
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
            if execution_path == "deterministic":
                reply_text, tool_results, evidence_response = await _run_deterministic_skill_execution(
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
                response = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
                reply_text = extract_final_text(response)
                tool_results = []
            evidence = validate_evidence(
                analysis_mode=analysis_mode,
                resolved_symbol=stock_code,
                response=response,
            )
            used_tools = evidence.used_tools or _response_used_tools(response)
            if _needs_verifiable_data(effective_query) and not evidence.evidence_ok:
                reply_text = _missing_evidence_message(user_message)
                log_reply_completed(
                    mode="evidence-missing",
                    used_tools=used_tools,
                    successful_tools=evidence.successful_tools,
                    evidence_ok=evidence.evidence_ok,
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
            reply_text = _format_tool_failure_message(user_message, str(exc))
            used_tools = False
            tool_results = []
            log_reply_completed(mode="skill-error", used_tools=False, error=str(exc), evidence_ok=False)

        return SkillExecutionResult(
            reply_text=reply_text.strip(),
            selected_skill=selected_skill,
            trace={
                "resolved_company": company_name,
                "resolved_symbol": stock_code,
                "used_tools": used_tools,
                "skill_aliases": get_skill_registry().get_skill(_source_skill_name(selected_skill)).aliases
                if get_skill_registry().get_skill(_source_skill_name(selected_skill))
                else [],
                "analysis_mode": analysis_mode,
                "execution_path": execution_path,
                "planned_tools": [item.tool_name for item in tool_plan.tool_calls],
                "tool_batch_size": len(tool_plan.tool_calls),
                "evidence_ok": bool(locals().get("evidence").evidence_ok) if "evidence" in locals() else False,
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
            },
        )
