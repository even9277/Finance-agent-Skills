from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agents.rewrite_context import RewriteContextPacket
from src.agents.skill_router_node import SkillRouteDecision
from src.skills.skill_registry import get_skill_registry
from src.tools.chat_tushare_tools import get_tushare_toolkit, resolve_sector_request
from src.tools.skill_trace import log_degrade_transition, trace_span
from src.utils.logging_config import setup_logger

logger = setup_logger("query_rewriter")

try:
    from dotenv import load_dotenv

    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / "backend" / ".env", override=False)
except Exception:
    pass


class EntityResolution(BaseModel):
    display_name: str
    asset_type: Literal["stock", "fund", "sector", "index"]
    symbol: str | None = None


class SopRewriteResult(BaseModel):
    effective_query: str
    entities: list[EntityResolution] = Field(default_factory=list)
    skill_params: dict[str, Any] = Field(default_factory=dict)


AllowedTushareToolName = Literal[
    "get_stock_basic_info",
    "get_daily_bars",
    "get_market_bars",
    "get_index_bars",
    "get_sector_snapshot",
    "get_sector_constituents",
    "get_fund_basic_info",
    "get_fund_nav",
    "get_fund_market_bars",
    "get_fund_share",
    "get_fina_indicator",
    "get_income",
    "get_balance_sheet",
    "get_cashflow",
]


class ToolPlanStep(BaseModel):
    tool_name: AllowedTushareToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] | None = None


class TushareRewriteResult(BaseModel):
    effective_query: str
    entities: list[EntityResolution] = Field(default_factory=list)
    tool_plan: list[ToolPlanStep] = Field(default_factory=list)


class FallbackRewriteResult(BaseModel):
    effective_query: str


class TushareRewriteResultV2(BaseModel):
    effective_query: str
    entities: list[EntityResolution] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    candidate_tool_hints: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str = ""
    route_mismatch: str = ""
    entity_conflict: str = ""
    confidence: float = 0.0


class SopRewriteResultV2(SopRewriteResult):
    need_clarification: bool = False
    clarification_question: str = ""
    route_mismatch: str = ""
    entity_conflict: str = ""
    confidence: float = 0.0


class FallbackRewriteResultV2(FallbackRewriteResult):
    need_clarification: bool = False
    clarification_question: str = ""
    route_mismatch: str = ""
    entity_conflict: str = ""
    confidence: float = 0.0


_SOP_REWRITER_SYSTEM_PROMPT = """[角色与任务边界]
你是 A 股投研问答的 Query 重写器。你只能做改写与结构化抽取，不能做路由，不能编造事实。

[Route Context Slice]
这是 route slice + 最近对话，不是全文 STM。
rolling-summary 可用字段只有 active_entities，用于主语补全、指代消解、follow-up 实体继承。
禁止把 constraints / reply_preference_hint / open_loops / session_record_summary 当作输入信号。
{stm_snapshot}

[LTM 摘要]
{ltm_summary}

[Resolver Hint]
resolver_hint 只是增强，不是强制真源。
{resolver_hint}

[Latest User Message]
这是本轮必须优先保留的用户意图。
如果与最近对话/旧问题冲突，以最新用户消息为准；历史只用于补主语和指代，不得把任务回退成上一问。
{latest_user_message}

[SKILL Inputs / Decision Rules / allowed_tools]
skill_id: {skill_id}
allowed_tools: {allowed_tools}
skill_specific_constraints:
{skill_specific_constraints}
Inputs:
{inputs}

Decision Rules:
{decision_rules}

[输出 JSON Schema]
{schema}

[正例]
1) 单标的：把“它/这只”改写为可执行问法，并抽取实体
2) 缺少关键槽位：保持 effective_query 清晰，并在 skill_params 中写入 need_clarification=true 与 clarification_question
3) 指代消解：结合 STM 快照把省略主语补全

[反例]
1) 不要输出 JSON 之外的文字
2) 不要输出未经用户提及的行情结论

[禁止项]
- 不验证交易所标号是否真实存在
- 不补充行情事实
- 只输出合法 JSON
"""

_TUSHARE_REWRITER_SYSTEM_PROMPT = """[角色与任务边界]
你是 Tushare tool_plan 重写器。你不能重路由，不能输出 analysis_mode，不能输出 SOP skill 名。

[Route Context Slice]
这是 route slice + 最近对话，不是全文 STM。
rolling-summary 可用字段只有 active_entities。
禁止把 constraints / reply_preference_hint / open_loops / session_record_summary 当作输入信号。
{stm_snapshot}

[LTM 摘要]
{ltm_summary}

[Resolver Hint]
resolver_hint 只是增强，不是强制真源。
{resolver_hint}

[Latest User Message]
这是本轮必须优先保留的用户意图。
如果与最近对话/旧问题冲突，以最新用户消息为准；历史只用于补主语和指代，不得把任务回退成上一问。
{latest_user_message}

[工具目录]
{toolkit_catalog}

[输出 JSON Schema]
{schema}

[正例]
1) 基本面：stock_basic -> fina_indicator -> income
2) 行情：daily_bars 或 market_bars
3) 板块：sector_snapshot -> sector_constituents
4) 指数：index_bars
5) 基金：fund_basic_info -> fund_nav -> fund_share

[反例]
1) 禁止 analysis_mode 字段
2) 禁止 SOP skill 名作为 tool_name

[禁止项]
- tool_name 只能来自工具目录
- 不得编造行情数值
- 只输出合法 JSON
"""

_TUSHARE_REWRITER_REFINER_PROMPT = """[角色与任务边界]
你是 Tushare tool_plan 精修器，只能在候选工具集合内改进计划。

[Route Context Slice]
这是 route slice + 最近对话，不是全文 STM。
rolling-summary 可用字段只有 active_entities。
{stm_snapshot}

[LTM 摘要]
{ltm_summary}

[Resolver Hint]
resolver_hint 只是增强，不是强制真源。
{resolver_hint}

[Latest User Message]
这是本轮必须优先保留的用户意图。
如果上一轮候选计划与最新用户消息冲突，必须以最新用户消息为准重写 effective_query，并同步调整 tool_plan。
{latest_user_message}

[候选工具条目]
{focused_catalog}

[上一轮候选计划]
{previous_plan}

[输出 JSON Schema]
{schema}

[要求]
- tool_name 只能取候选工具条目中的名字
- 优先补齐 depends_on 的可执行顺序
- 只输出合法 JSON
"""

_FALLBACK_REWRITER_SYSTEM_PROMPT = """[角色与任务边界]
你是通用对话改写器，只做意图澄清和指代补全。

[Route Context Slice]
这是 route slice + 最近对话，不是全文 STM。
rolling-summary 可用字段只有 active_entities。
禁止把 constraints / reply_preference_hint / open_loops / session_record_summary 当作输入信号。
{stm_snapshot}

[LTM 摘要]
{ltm_summary}

[Resolver Hint]
resolver_hint 只是增强，不是强制真源。
{resolver_hint}

[Latest User Message]
这是本轮必须优先保留的用户意图。
如果与最近对话/旧问题冲突，以最新用户消息为准；历史只用于补主语和指代，不得把任务回退成上一问。
{latest_user_message}

[输出 JSON Schema]
{schema}

[正例]
1) “它现在怎么样” -> 补全为具体对象
2) “继续刚才那个问题” -> 补全为明确问题

[反例]
1) 不要添加观点
2) 不要输出 JSON 外文字
"""

_EFFECTIVE_QUERY_SIGNAL_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
_RESPONSE_PREFS = {"risk_first", "concise", "balanced"}
_COMPARE_SIGNAL_RE = re.compile(r"(比较|对比|PK|pk|VS|vs|和)")
_SECTOR_HINT_RE = re.compile(r"(板块|行业|概念|赛道|主题)")
_FUND_ENTITY_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\-]{2,30}(?:ETF|etf|基金|联接|LOF|lof|QDII|qdii)")
_GENERIC_FOLLOWUP_ONLY_RE = re.compile(r"^(继续|还是|然后|再|那|这个|那个|它|他们|她们|该|这只|那只|这家公司|那家公司|怎么看|怎么样|如何|咋样|呢|\?|？|,|，|。|\s)+$")
_ANSWER_POLICY_HINT_RE = re.compile(
    r"(沿用刚才的回答风格|沿用刚才风格|按刚才的风格|按刚才风格|还是先结论后依据|先给结论再给三条依据|先给结论|再给三条依据|"
    r"不要讲太宏观|术语少一点|更适合新手阅读|不要丢掉核心结论|A股口径|港股|美股)"
)
_FOCUS_CLEANUP_RE = re.compile(
    r"(帮我|请|麻烦|给我|如果|继续|延续|沿用|还是|再回答一遍|回答一遍|再回答|回答|只保留|保留|把|换成|第二家公司|"
    r"这两个|两个|这个|那个|它|他们|她们|更看好谁|怎么看|怎么样|如何|只要|不要|太宏观|最近|一年|对比|比较|一下)"
)
_FOCUS_TERM_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}")
_FOCUS_TERM_STOPWORDS = {
    "如果",
    "只要",
    "只保留",
    "继续",
    "延续",
    "刚才",
    "上一题",
    "上一个问题",
    "回答一遍",
    "再回答一遍",
    "还是",
    "回答",
    "风格",
    "这个",
    "那个",
    "这样",
    "它",
    "他们",
    "她们",
    "这只",
    "那只",
    "这家公司",
    "那家公司",
    "怎么看",
    "怎么样",
    "如何",
    "现在",
    "最近",
    "一年",
    "不要",
    "讲太宏观",
}


def _safe_getenv(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _rewriter_model_name() -> str:
    # 改写阶段需要稳定 JSON 输出；优先非 reasoning 模型，避免 max_tokens 被推理 token 吃满。
    return (
        _safe_getenv("CHAT_REWRITER_MODEL")
        or _safe_getenv("CHAT_ROUTER_MODEL")
        or _safe_getenv("CHAT_RESOLVER_MODEL")
        or _safe_getenv("OPENAI_COMPATIBLE_MODEL")
        or "tongyi-xiaomi-analysis-pro"
    )


def _build_model(*, temperature: float = 0.0, max_tokens: int = 900):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=_rewriter_model_name(),
        openai_api_key=_safe_getenv("OPENAI_COMPATIBLE_API_KEY"),
        openai_api_base=_safe_getenv("OPENAI_COMPATIBLE_BASE_URL"),
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _pydantic_validate(model_cls: Any, data: Any) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)
    return model_cls.parse_obj(data)


def _schema_json(model_cls: type[BaseModel]) -> str:
    def _disallow_additional_properties(node: Any) -> Any:
        if isinstance(node, dict):
            cloned = {key: _disallow_additional_properties(value) for key, value in node.items()}
            if cloned.get("type") == "object" and "additionalProperties" not in cloned:
                cloned["additionalProperties"] = False
            return cloned
        if isinstance(node, list):
            return [_disallow_additional_properties(item) for item in node]
        return node

    if hasattr(model_cls, "model_json_schema"):
        payload = model_cls.model_json_schema()
    else:
        payload = model_cls.schema()
    payload = _disallow_additional_properties(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _resolver_hint_text(resolver_hint: dict[str, Any] | None) -> str:
    hint = dict(resolver_hint or {})
    if not hint:
        return "无"
    display_name = str(hint.get("display_name") or "").strip() or "unknown"
    asset_type = str(hint.get("asset_type") or "").strip() or "unknown"
    symbol = str(hint.get("symbol") or "").strip() or "unknown"
    confidence = float(hint.get("confidence") or 0.0)
    source = str(hint.get("resolver_source") or hint.get("resolver_stage") or "").strip() or "unknown"
    return (
        f"display_name={display_name}\n"
        f"asset_type={asset_type}\n"
        f"symbol={symbol}\n"
        f"confidence={confidence:.4f}\n"
        f"source={source}"
    )


def _inject_resolver_entity(
    entities: list[EntityResolution],
    resolver_hint: dict[str, Any] | None,
) -> list[EntityResolution]:
    hint = dict(resolver_hint or {})
    if not hint or float(hint.get("confidence") or 0.0) < 0.75:
        return list(entities or [])

    asset_type = str(hint.get("asset_type") or "").strip()
    if asset_type not in {"stock", "fund", "sector", "index"}:
        return list(entities or [])

    display_name = str(hint.get("display_name") or "").strip()
    symbol = str(hint.get("symbol") or "").strip() or None
    if not display_name and not symbol:
        return list(entities or [])

    injected = EntityResolution(
        display_name=display_name or str(symbol or ""),
        asset_type=asset_type,
        symbol=symbol,
    )
    existing = list(entities or [])
    for item in existing:
        if symbol and str(item.symbol or "").strip() == symbol:
            return existing
        if display_name and str(item.display_name or "").strip() == display_name and item.asset_type == asset_type:
            return existing
    return [injected, *existing]


def _tool_name(tool: Any) -> str:
    name = str(getattr(tool, "name", "") or "").strip()
    if name:
        return name
    return str(getattr(tool, "__name__", "") or "").strip()


def _tool_doc(tool: Any) -> str:
    desc = str(getattr(tool, "description", "") or "").strip()
    if desc:
        return desc
    return str(getattr(tool, "__doc__", "") or "").strip()


@lru_cache(maxsize=1)
def _toolkit_items() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for tool in get_tushare_toolkit():
        name = _tool_name(tool)
        if not name:
            continue
        items.append((name, _tool_doc(tool)))
    return items


@lru_cache(maxsize=1)
def _build_toolkit_catalog() -> str:
    lines: list[str] = []
    for name, doc in _toolkit_items():
        lines.append(f"- {name}: {doc or 'no description'}")
    return "\n".join(lines) if lines else "- no tools"


def _build_focus_catalog(tool_names: list[str]) -> str:
    wanted = {str(name).strip() for name in tool_names if str(name).strip()}
    lines: list[str] = []
    for name, doc in _toolkit_items():
        if name in wanted:
            lines.append(f"- {name}: {doc or 'no description'}")
    return "\n".join(lines) if lines else _build_toolkit_catalog()


def _split_markdown_sections(markdown: str) -> dict[str, str]:
    if not markdown:
        return {}
    sections: dict[str, list[str]] = {}
    current_key = "_root"
    sections[current_key] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            current_key = line[3:].strip().lower().replace(" ", "_")
            sections.setdefault(current_key, [])
            continue
        sections.setdefault(current_key, []).append(line)
    return {
        key: "\n".join(value).strip()
        for key, value in sections.items()
    }


def _load_skill_doc_sections(skill_id: str) -> dict[str, Any]:
    registry = get_skill_registry()
    meta = registry.get_skill(skill_id)
    markdown = registry.load_skill_markdown(skill_id)
    sections = _split_markdown_sections(markdown)
    return {
        "inputs": sections.get("inputs", ""),
        "decision_rules": sections.get("decision_rules", ""),
        "output_template": sections.get("output_template", ""),
        "fallbacks": sections.get("fallbacks", ""),
        "allowed_tools": list(meta.allowed_tools) if meta else [],
    }


def _skill_specific_constraints(skill_id: str) -> str:
    if skill_id == "stock-first-pass":
        return (
            "- 本 skill 仅支持单标的股票首轮研判，实体基数必须为 1。\n"
            "- 若用户表达为多标的推荐/比较/筛选（例如“推荐4只股票”），不要伪造单一标的。\n"
            "- 缺少明确单一标的时：entities 留空，并在 skill_params 填入 "
            "need_clarification=true、clarification_question。"
        )
    if skill_id == "fund-compare":
        return (
            "- 本 skill 至少需要 2 个明确基金/ETF 对象。\n"
            "- 若对象不足 2 个，不要伪造比较结论；请输出 need_clarification=true。"
        )
    if skill_id == "sector-hotspot-brief":
        return (
            "- 本 skill 需要可执行的 sector_name/index_code。\n"
            "- 若输入是宽泛别名（如“科技”“新能源”），优先标准化；无法稳定命中时输出 need_clarification=true。"
        )
    return "- 无额外约束"


def _tushare_allowed_tool_names() -> set[str]:
    return {name for name, _ in _toolkit_items() if name}


def _validate_tushare_plan(result: TushareRewriteResult) -> None:
    if not result.tool_plan:
        raise ValueError("empty_tool_plan")
    allowed = _tushare_allowed_tool_names()
    n = len(result.tool_plan)
    graph: dict[int, list[int]] = {i: [] for i in range(n)}
    for idx, step in enumerate(result.tool_plan):
        if step.tool_name not in allowed:
            raise ValueError(f"tool_name_not_allowed: {step.tool_name}")
        deps = list(step.depends_on or [])
        for dep in deps:
            if dep < 0 or dep >= n:
                raise ValueError(f"depends_on_out_of_range step={idx} dep={dep} n={n}")
            if dep == idx:
                raise ValueError(f"depends_on_self_ref step={idx}")
            graph[dep].append(idx)

    state: dict[int, int] = {i: 0 for i in range(n)}

    def _dfs(node: int) -> None:
        state[node] = 1
        for nxt in graph[node]:
            if state[nxt] == 1:
                raise ValueError("depends_on_cycle")
            if state[nxt] == 0:
                _dfs(nxt)
        state[node] = 2

    for i in range(n):
        if state[i] == 0:
            _dfs(i)


async def _invoke_structured(prompt: str, model_cls: type[BaseModel]) -> BaseModel:
    from langchain_core.messages import HumanMessage

    llm = _build_model()
    try:
        structured = llm.with_structured_output(model_cls, method="json_schema", strict=True)
    except TypeError:
        structured = llm.with_structured_output(model_cls)
    result = await structured.ainvoke([HumanMessage(content=prompt)])
    if isinstance(result, model_cls):
        return result
    if isinstance(result, dict):
        return _pydantic_validate(model_cls, result)
    return _pydantic_validate(model_cls, result)


def _sanitize_effective_query(candidate: Any, user_message: str) -> str:
    raw = str(candidate or "").strip()
    fallback = str(user_message or "").strip() or str(user_message or "")
    if not raw:
        return fallback
    if not _EFFECTIVE_QUERY_SIGNAL_RE.search(raw):
        return fallback
    if not _preserves_latest_user_intent(raw, fallback):
        return fallback
    return raw


def _meaningful_followup_terms(user_message: str) -> list[str]:
    clean = str(user_message or "").strip()
    if not clean:
        return []
    clean = _ANSWER_POLICY_HINT_RE.sub(" ", clean)
    clean = _FOCUS_CLEANUP_RE.sub(" ", clean)
    terms: list[str] = []
    for term in _FOCUS_TERM_RE.findall(clean):
        normalized = term.strip()
        if len(normalized) < 2:
            continue
        if normalized in _FOCUS_TERM_STOPWORDS:
            continue
        if normalized.isdigit():
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms[:6]


def _preserves_latest_user_intent(candidate_query: str, user_message: str) -> bool:
    latest = str(user_message or "").strip()
    if not latest:
        return True
    if _GENERIC_FOLLOWUP_ONLY_RE.fullmatch(latest):
        return True
    focus_terms = _meaningful_followup_terms(latest)
    if not focus_terms:
        return True
    candidate = str(candidate_query or "").strip()
    return any(term in candidate for term in focus_terms)


def _dedupe_strings(values: list[Any]) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _entity_display_names(entities: list[EntityResolution]) -> list[str]:
    return _dedupe_strings([item.display_name for item in entities if str(item.display_name or "").strip()])


def _normalize_response_pref(skill_params: dict[str, Any]) -> dict[str, Any]:
    params = dict(skill_params or {})
    response_pref = str(params.get("response_pref") or "").strip()
    if response_pref not in _RESPONSE_PREFS:
        params.pop("response_pref", None)
    return params


def _clarification_payload(
    *,
    question: str,
    failure_code: str,
    candidate_sector_names: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "need_clarification": True,
        "clarification_question": question,
        "failure_code": failure_code,
    }
    candidates = _dedupe_strings(list(candidate_sector_names or []))
    if candidates:
        payload["candidate_sector_names"] = candidates[:6]
    return payload


def _sector_clarification_question(cleaned_name: str, candidate_sector_names: list[str]) -> str:
    candidates = _dedupe_strings(candidate_sector_names)
    if candidates:
        joined = "、".join(candidates[:4])
        label = cleaned_name or "这个板块"
        return f"你说的“{label}”可能对应 {joined}。你想看哪一个申万行业？"
    return "请直接说一个更明确的申万行业名称，比如电力设备、汽车、计算机、电子。"


def _fund_compare_subjects(parsed: SopRewriteResult) -> list[str]:
    params = parsed.skill_params or {}
    subjects: list[str] = []
    for key in ("subjects", "candidate_entities"):
        value = params.get(key)
        if isinstance(value, list):
            subjects.extend(value)
    subjects.extend(_entity_display_names(parsed.entities))
    if not subjects:
        subjects.extend(_FUND_ENTITY_RE.findall(parsed.effective_query))
    return _dedupe_strings(subjects)[:4]


def _single_stock_subjects(parsed: SopRewriteResult) -> list[str]:
    params = parsed.skill_params or {}
    subjects: list[str] = []
    for key in ("stock_subject", "candidate_entities", "subjects"):
        value = params.get(key)
        if isinstance(value, list):
            subjects.extend(value)
        elif isinstance(value, str):
            subjects.append(value)
    for entity in parsed.entities:
        if entity.asset_type == "stock":
            subjects.append(entity.display_name)
    return _dedupe_strings(subjects)


async def _validate_and_normalize_sop_params(
    *,
    skill_id: str,
    parsed: SopRewriteResult,
    user_message: str,
) -> SopRewriteResult:
    effective_query = _sanitize_effective_query(parsed.effective_query, user_message)
    normalized = SopRewriteResult(
        effective_query=effective_query,
        entities=list(parsed.entities or []),
        skill_params=_normalize_response_pref(dict(parsed.skill_params or {})),
    )
    params = dict(normalized.skill_params)

    if skill_id == "fund-compare":
        subjects = _fund_compare_subjects(normalized)
        if len(subjects) >= 2:
            params["subjects"] = subjects[:4]
        else:
            params.update(
                _clarification_payload(
                    question="请至少告诉我两只明确的基金或 ETF 名称/代码，我再继续比较。",
                    failure_code="fund_compare_subject_missing",
                )
            )

    elif skill_id == "stock-first-pass":
        stock_subjects = _single_stock_subjects(normalized)
        if len(stock_subjects) == 1:
            params["stock_subject"] = stock_subjects[0]
        elif len(stock_subjects) != 1 or _COMPARE_SIGNAL_RE.search(effective_query):
            params.update(
                _clarification_payload(
                    question="这个技能一次只支持分析一只股票。请告诉我一个明确的股票名称或 6 位代码。",
                    failure_code="stock_subject_missing",
                )
            )

    elif skill_id == "sector-hotspot-brief":
        sector_resolution = await resolve_sector_request(
            query=effective_query,
            sector_name=str(params.get("sector_name") or ""),
        )
        params["raw_sector_query"] = str(sector_resolution.get("requested_name") or effective_query)
        params["candidate_sector_names"] = _dedupe_strings(sector_resolution.get("candidate_sector_names") or [])[:6]
        params["match_confidence"] = float(sector_resolution.get("match_confidence") or 0.0)
        resolved_sector_name = str(sector_resolution.get("normalized_sector_name") or "").strip()
        index_code = str(sector_resolution.get("index_code") or "").strip()
        if resolved_sector_name and index_code:
            params["sector_name"] = resolved_sector_name
            params["index_code"] = index_code
            params["sector_aliases"] = _dedupe_strings(
                [sector_resolution.get("cleaned_name"), *params.get("candidate_sector_names", [])]
            )[:6]
        else:
            params.update(
                _clarification_payload(
                    question=_sector_clarification_question(
                        str(sector_resolution.get("cleaned_name") or ""),
                        list(params.get("candidate_sector_names") or []),
                    ),
                    failure_code=str(sector_resolution.get("failure_code") or "sector_unresolved"),
                    candidate_sector_names=list(params.get("candidate_sector_names") or []),
                )
            )

    elif skill_id == "market-move-explain":
        if params.get("sector_name") or _SECTOR_HINT_RE.search(effective_query):
            sector_resolution = await resolve_sector_request(
                query=effective_query,
                sector_name=str(params.get("sector_name") or ""),
            )
            resolved_sector_name = str(sector_resolution.get("normalized_sector_name") or "").strip()
            index_code = str(sector_resolution.get("index_code") or "").strip()
            if resolved_sector_name and index_code:
                params["sector_name"] = resolved_sector_name
                params["index_code"] = index_code
                params["match_confidence"] = float(sector_resolution.get("match_confidence") or 0.0)
                params["candidate_sector_names"] = _dedupe_strings(
                    sector_resolution.get("candidate_sector_names") or []
                )[:6]
                params["raw_sector_query"] = str(sector_resolution.get("requested_name") or effective_query)

    if params.get("need_clarification") and not str(params.get("clarification_question") or "").strip():
        fallback_question = "请补充更明确的信息后我再继续。"
        if skill_id == "sector-hotspot-brief":
            fallback_question = _sector_clarification_question(
                str(params.get("raw_sector_query") or ""),
                list(params.get("candidate_sector_names") or []),
            )
        elif skill_id == "fund-compare":
            fallback_question = "请至少告诉我两只明确的基金或 ETF 名称/代码，我再继续比较。"
        elif skill_id == "stock-first-pass":
            fallback_question = "请告诉我一个明确的股票名称或 6 位代码。"
        params["clarification_question"] = fallback_question

    normalized.skill_params = params
    return normalized


def _fallback_sop_result(user_message: str) -> SopRewriteResult:
    query = _sanitize_effective_query("", user_message)
    return SopRewriteResult(
        effective_query=query,
        entities=[],
        skill_params={},
    )


def _fallback_tushare_result(user_message: str) -> TushareRewriteResult:
    query = _sanitize_effective_query("", user_message)
    return TushareRewriteResult(
        effective_query=query,
        entities=[],
        tool_plan=[
            ToolPlanStep(
                tool_name="get_market_bars",
                arguments={"query": query, "limit": 30},
                depends_on=None,
            )
        ],
    )


async def rewrite_for_sop(
    decision: SkillRouteDecision,
    user_message: str,
    stm_snapshot: str,
    ltm_summary: str,
    *,
    resolver_hint: dict[str, Any] | None = None,
) -> SopRewriteResult:
    skill_id = str(decision.skill_id or "").strip()
    if not skill_id:
        return _fallback_sop_result(user_message)

    sections = _load_skill_doc_sections(skill_id)
    prompt = _SOP_REWRITER_SYSTEM_PROMPT.format(
        stm_snapshot=stm_snapshot or "无",
        ltm_summary=ltm_summary or "无",
        resolver_hint=_resolver_hint_text(resolver_hint),
        latest_user_message=user_message or "无",
        skill_id=skill_id,
        allowed_tools=", ".join(str(i) for i in sections.get("allowed_tools") or []) or "无",
        skill_specific_constraints=_skill_specific_constraints(skill_id),
        inputs=sections.get("inputs") or "无",
        decision_rules=sections.get("decision_rules") or "无",
        schema=_schema_json(SopRewriteResult),
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with trace_span(
                "rewrite_sop",
                stage="rewrite",
                data={
                    "attempt": attempt + 1,
                    "skill_id": skill_id,
                    "route_context_used": bool(stm_snapshot),
                    "ltm_used": bool(ltm_summary),
                },
                ):
                    out = await _invoke_structured(prompt, SopRewriteResult)
            parsed = _pydantic_validate(SopRewriteResult, out)
            parsed.entities = _inject_resolver_entity(list(parsed.entities or []), resolver_hint)
            parsed = await _validate_and_normalize_sop_params(
                skill_id=skill_id,
                parsed=parsed,
                user_message=user_message,
            )
            with trace_span(
                "rewrite_sop_contract",
                stage="rewrite",
                data={
                    "skill_id": skill_id,
                    "need_clarification": bool(parsed.skill_params.get("need_clarification")),
                    "failure_code": str(parsed.skill_params.get("failure_code") or ""),
                    "normalized_sector_name": str(parsed.skill_params.get("sector_name") or ""),
                    "candidate_sector_names": list(parsed.skill_params.get("candidate_sector_names") or [])[:5],
                    "match_confidence": float(parsed.skill_params.get("match_confidence") or 0.0),
                },
            ):
                pass
            return parsed
        except Exception as exc:
            last_error = exc
            logger.warning("[query_rewriter] rewrite_for_sop attempt=%s failed: %s", attempt + 1, exc, exc_info=True)

    log_degrade_transition(from_stage="rewrite", reason=f"sop_rewrite_failed: {last_error}")
    return _fallback_sop_result(user_message)


async def rewrite_for_tushare(
    decision: SkillRouteDecision,
    user_message: str,
    stm_snapshot: str,
    ltm_summary: str,
    *,
    resolver_hint: dict[str, Any] | None = None,
) -> TushareRewriteResult:
    _ = decision
    base_prompt = _TUSHARE_REWRITER_SYSTEM_PROMPT.format(
        stm_snapshot=stm_snapshot or "无",
        ltm_summary=ltm_summary or "无",
        resolver_hint=_resolver_hint_text(resolver_hint),
        latest_user_message=user_message or "无",
        toolkit_catalog=_build_toolkit_catalog(),
        schema=_schema_json(TushareRewriteResult),
    )

    first_result: TushareRewriteResult | None = None
    first_error: Exception | None = None
    for attempt in range(2):
        try:
            with trace_span(
                "rewrite_tushare",
                stage="rewrite",
                data={"attempt": attempt + 1, "phase": "first_pass"},
            ):
                first_raw = await _invoke_structured(base_prompt, TushareRewriteResult)
            first_result = _pydantic_validate(TushareRewriteResult, first_raw)
            first_result.entities = _inject_resolver_entity(list(first_result.entities or []), resolver_hint)
            _validate_tushare_plan(first_result)
            break
        except Exception as exc:
            first_error = exc
            logger.warning("[query_rewriter] rewrite_for_tushare first_pass attempt=%s failed: %s", attempt + 1, exc, exc_info=True)

    if first_result is None:
        log_degrade_transition(from_stage="rewrite", reason=f"tushare_first_pass_failed: {first_error}")
        return _fallback_tushare_result(user_message)

    focused_catalog = _build_focus_catalog([step.tool_name for step in first_result.tool_plan])
    second_prompt = _TUSHARE_REWRITER_REFINER_PROMPT.format(
        stm_snapshot=stm_snapshot or "无",
        ltm_summary=ltm_summary or "无",
        resolver_hint=_resolver_hint_text(resolver_hint),
        latest_user_message=user_message or "无",
        focused_catalog=focused_catalog,
        previous_plan=(
            json.dumps(first_result.model_dump(), ensure_ascii=False)
            if hasattr(first_result, "model_dump")
            else json.dumps(first_result.dict(), ensure_ascii=False)
        ),
        schema=_schema_json(TushareRewriteResult),
    )

    try:
        with trace_span(
            "rewrite_tushare",
            stage="rewrite",
            data={"attempt": 1, "phase": "refine_pass", "candidate_tools": [step.tool_name for step in first_result.tool_plan]},
        ):
            second_raw = await _invoke_structured(second_prompt, TushareRewriteResult)
        second_result = _pydantic_validate(TushareRewriteResult, second_raw)
        second_result.entities = _inject_resolver_entity(list(second_result.entities or []), resolver_hint)
        _validate_tushare_plan(second_result)
        second_result.effective_query = _sanitize_effective_query(second_result.effective_query, user_message)
        return second_result
    except Exception as exc:
        logger.warning("[query_rewriter] rewrite_for_tushare refine_pass failed, keep first_pass: %s", exc, exc_info=True)
        _validate_tushare_plan(first_result)
        first_result.effective_query = _sanitize_effective_query(first_result.effective_query, user_message)
        return first_result


async def rewrite_for_fallback(
    user_message: str,
    stm_snapshot: str,
    ltm_summary: str,
    *,
    resolver_hint: dict[str, Any] | None = None,
) -> FallbackRewriteResult:
    prompt = _FALLBACK_REWRITER_SYSTEM_PROMPT.format(
        stm_snapshot=stm_snapshot or "无",
        ltm_summary=ltm_summary or "无",
        resolver_hint=_resolver_hint_text(resolver_hint),
        latest_user_message=user_message or "无",
        schema=_schema_json(FallbackRewriteResult),
    )
    try:
        with trace_span(
            "rewrite_fallback",
            stage="rewrite",
            data={"route_context_used": bool(stm_snapshot), "ltm_used": bool(ltm_summary)},
        ):
            raw = await _invoke_structured(prompt, FallbackRewriteResult)
        out = _pydantic_validate(FallbackRewriteResult, raw)
        out.effective_query = _sanitize_effective_query(out.effective_query, user_message)
        return out
    except Exception as exc:
        logger.warning("[query_rewriter] rewrite_for_fallback failed: %s", exc, exc_info=True)
        log_degrade_transition(from_stage="rewrite", reason=f"fallback_rewrite_failed: {exc}")
        return FallbackRewriteResult(
            effective_query=str(user_message or "").strip() or str(user_message or ""),
        )


async def rewrite_for_sop_v2(ctx: RewriteContextPacket) -> SopRewriteResultV2:
    decision = SkillRouteDecision(route="sop", skill_id=ctx.skill_id, execution_policy="deterministic")
    result = await rewrite_for_sop(
        decision,
        ctx.user_query,
        stm_snapshot=json.dumps(ctx.working_state_prev or {}, ensure_ascii=False),
        ltm_summary="",
        resolver_hint=ctx.active_entity,
    )
    return SopRewriteResultV2(
        effective_query=result.effective_query,
        entities=result.entities,
        skill_params=result.skill_params,
        confidence=0.9,
    )


async def rewrite_for_tushare_v2(ctx: RewriteContextPacket) -> TushareRewriteResultV2:
    decision = SkillRouteDecision(route="tushare", execution_policy="deterministic")
    try:
        result = await rewrite_for_tushare(
            decision,
            ctx.user_query,
            stm_snapshot=json.dumps(ctx.working_state_prev or {}, ensure_ascii=False),
            ltm_summary="",
            resolver_hint=ctx.active_entity,
        )
    except Exception as exc:
        logger.warning("[query_rewriter] rewrite_for_tushare_v2 fallback: %s", exc, exc_info=True)
        result = _fallback_tushare_result(ctx.user_query)
    tool_names = [str(step.tool_name) for step in result.tool_plan]
    return TushareRewriteResultV2(
        effective_query=result.effective_query,
        entities=result.entities,
        data_requirements=_tool_names_to_data_requirements(tool_names),
        time_scope=_infer_time_scope(ctx.user_query),
        candidate_tool_hints=tool_names,
        confidence=0.86 if tool_names else 0.5,
    )


async def rewrite_for_fallback_v2(ctx: RewriteContextPacket) -> FallbackRewriteResultV2:
    result = await rewrite_for_fallback(
        ctx.user_query,
        stm_snapshot=json.dumps(ctx.working_state_prev or {}, ensure_ascii=False),
        ltm_summary="",
        resolver_hint=ctx.active_entity,
    )
    return FallbackRewriteResultV2(effective_query=result.effective_query, confidence=0.8)


def _tool_names_to_data_requirements(tool_names: list[str]) -> list[str]:
    mapping = {
        "get_stock_basic_info": "stock_basic",
        "get_daily_bars": "stock_daily",
        "get_market_bars": "market_bars",
        "get_index_bars": "index_context",
        "get_sector_snapshot": "sector_snapshot",
        "get_sector_constituents": "sector_constituents",
        "get_fund_basic_info": "fund_basic",
        "get_fund_nav": "fund_nav",
        "get_fund_market_bars": "fund_market_bars",
        "get_fund_share": "fund_share",
        "get_fina_indicator": "financial_indicator",
        "get_income": "income_statement",
        "get_balance_sheet": "balance_sheet",
        "get_cashflow": "cashflow",
    }
    out: list[str] = []
    for name in tool_names:
        item = mapping.get(str(name), str(name))
        if item not in out:
            out.append(item)
    return out


def _infer_time_scope(query: str) -> dict[str, Any]:
    text = query or ""
    if any(token in text for token in ("今天", "今日", "现在", "当前")):
        return {"trade_date": "latest_trading_day"}
    if "最近" in text or "近期" in text:
        return {"lookback_days": 5}
    return {}


__all__ = [
    "EntityResolution",
    "SopRewriteResult",
    "ToolPlanStep",
    "TushareRewriteResult",
    "TushareRewriteResultV2",
    "FallbackRewriteResult",
    "SopRewriteResultV2",
    "FallbackRewriteResultV2",
    "rewrite_for_sop",
    "rewrite_for_tushare",
    "rewrite_for_fallback",
    "rewrite_for_sop_v2",
    "rewrite_for_tushare_v2",
    "rewrite_for_fallback_v2",
    "_load_skill_doc_sections",
    "_build_toolkit_catalog",
]
