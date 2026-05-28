from __future__ import annotations

from typing import Any

from src.agents.query_rewriter import ToolPlanStep, TushareRewriteResultV2, rewrite_for_tushare
from src.agents.skill_router_node import SkillRouteDecision
from src.tools.chat_tushare_tools import get_tushare_toolkit
from src.tools.skill_trace import log_degrade_transition, skill_trace_context, trace_span
from src.utils.logging_config import setup_logger

logger = setup_logger("tushare_plan_executor")


def _tool_name(tool: Any) -> str:
    name = str(getattr(tool, "name", "") or "").strip()
    if name:
        return name
    return str(getattr(tool, "__name__", "") or "").strip()


def _toolkit_by_name() -> dict[str, Any]:
    return {
        _tool_name(tool): tool
        for tool in get_tushare_toolkit()
        if _tool_name(tool)
    }


def _normalize_step(item: ToolPlanStep | dict[str, Any]) -> ToolPlanStep:
    if isinstance(item, ToolPlanStep):
        return item
    if hasattr(ToolPlanStep, "model_validate"):
        return ToolPlanStep.model_validate(item)
    return ToolPlanStep.parse_obj(item)


def _normalize_tool_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize common planner aliases to the chat tool contract.

    External planners and model outputs often emit `ts_code`, while the
    Tushare chat tools expect `symbol`. Normalize here so execution stays
    stable even when the model uses an equivalent field name.
    """
    normalized = dict(arguments or {})
    ts_code = str(normalized.get("ts_code") or "").strip()
    if ts_code and not str(normalized.get("symbol") or "").strip():
        normalized["symbol"] = ts_code
    return normalized


def _normalize_plan(tool_plan: list[ToolPlanStep] | list[dict[str, Any]]) -> list[ToolPlanStep]:
    return [_normalize_step(item) for item in (tool_plan or [])]


def adapt_rewrite_v2_to_tool_plan(rewrite: TushareRewriteResultV2 | dict[str, Any]) -> list[ToolPlanStep]:
    """Compatibility adapter: V2 rewrite semantics -> current executable plan."""

    payload = rewrite.model_dump() if hasattr(rewrite, "model_dump") else dict(rewrite or {})
    hints = [str(item) for item in (payload.get("candidate_tool_hints") or []) if str(item).strip()]
    requirements = [str(item) for item in (payload.get("data_requirements") or [])]
    if not hints:
        mapping = {
            "stock_basic": "get_stock_basic_info",
            "stock_daily": "get_daily_bars",
            "market_bars": "get_market_bars",
            "index_context": "get_index_bars",
            "sector_snapshot": "get_sector_snapshot",
            "sector_constituents": "get_sector_constituents",
            "fund_basic": "get_fund_basic_info",
            "fund_nav": "get_fund_nav",
            "fund_market_bars": "get_fund_market_bars",
            "fund_share": "get_fund_share",
            "financial_indicator": "get_fina_indicator",
            "income_statement": "get_income",
            "balance_sheet": "get_balance_sheet",
            "cashflow": "get_cashflow",
        }
        hints = [mapping[item] for item in requirements if item in mapping]
    allowed = set(_toolkit_by_name().keys())
    steps: list[ToolPlanStep] = []
    for name in hints:
        if name not in allowed or any(step.tool_name == name for step in steps):
            continue
        steps.append(ToolPlanStep(tool_name=name, arguments={}, depends_on=None))
    if not steps:
        steps.append(ToolPlanStep(tool_name="get_stock_basic_info", arguments={"limit": 3}, depends_on=None))
    _validate_plan(steps)
    return steps


def _validate_plan(steps: list[ToolPlanStep]) -> None:
    allowed = set(_toolkit_by_name().keys())
    n = len(steps)
    for idx, step in enumerate(steps):
        if step.tool_name not in allowed:
            raise ValueError(f"tool_name_not_allowed: {step.tool_name}")
        for dep in list(step.depends_on or []):
            if dep < 0 or dep >= n:
                raise ValueError(f"depends_on_out_of_range step={idx} dep={dep} n={n}")
            if dep == idx:
                raise ValueError(f"depends_on_self_ref step={idx}")

    visiting = [0] * n
    deps_map = {i: list(steps[i].depends_on or []) for i in range(n)}

    def _dfs(node: int) -> None:
        visiting[node] = 1
        for dep in deps_map[node]:
            if visiting[dep] == 1:
                raise ValueError("depends_on_cycle")
            if visiting[dep] == 0:
                _dfs(dep)
        visiting[node] = 2

    for i in range(n):
        if visiting[i] == 0:
            _dfs(i)


def _topological_order(steps: list[ToolPlanStep]) -> list[int]:
    n = len(steps)
    indegree = [0] * n
    edges: dict[int, list[int]] = {i: [] for i in range(n)}
    for idx, step in enumerate(steps):
        for dep in list(step.depends_on or []):
            edges[dep].append(idx)
            indegree[idx] += 1
    queue = [i for i in range(n) if indegree[i] == 0]
    order: list[int] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in edges[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != n:
        raise ValueError("depends_on_cycle")
    return order


def _entity_payload(entities: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in entities or []:
        if hasattr(item, "model_dump"):
            out.append(item.model_dump())
        elif isinstance(item, dict):
            out.append(dict(item))
        else:
            out.append({"display_name": str(item)})
    return out


def _resolved_entity_trace_fields(entities: list[Any]) -> tuple[str, str]:
    for item in _entity_payload(entities):
        symbol = str(item.get("symbol") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        if symbol or display_name:
            return display_name, symbol
    return "", ""


def _executor_trace_payload(
    *,
    planned_tools: list[str],
    tool_results: list[tuple[str, dict[str, Any]]],
    entities: list[Any],
    failure_code: str = "",
    missing_reasons: list[str] | None = None,
) -> dict[str, Any]:
    missing = list(missing_reasons or [])
    success = [name for name, res in tool_results if isinstance(res, dict) and not res.get("error")]
    accepted = [
        {
            "tool_name": name,
            "source": str((res or {}).get("source") or "tushare"),
            "trade_date": (res or {}).get("trade_date"),
            "data_time": (res or {}).get("data_time"),
        }
        for name, res in tool_results
        if isinstance(res, dict) and not res.get("error")
    ]
    evidence_ok = bool(success)
    if failure_code:
        evidence_ok = False
    resolved_company, resolved_symbol = _resolved_entity_trace_fields(entities)
    return {
        "selected_skill_family": "tushare-data",
        "selected_skill": "tushare-data",
        "skill_name": None,
        "analysis_mode": "general_chat",
        "execution_policy": "deterministic",
        "reply_mode": "tushare" if not failure_code else "tool-error",
        "planned_tools": planned_tools,
        "tool_batch_size": len(planned_tools),
        "prefetched_tool_names": [name for name, _ in tool_results],
        "used_tools": bool(tool_results),
        "evidence_ok": evidence_ok,
        "accepted_evidences": accepted,
        "rejected_evidences": [],
        "missing_evidence_reasons": missing,
        "failure_code": failure_code,
        "payload_refs": [],
        "prompt_ref": None,
        "reply_ref": None,
        "resolved_company": resolved_company,
        "resolved_symbol": resolved_symbol,
    }


async def execute_tushare_plan(
    tool_plan: list[ToolPlanStep] | list[dict[str, Any]],
    entities: list[Any],
    *,
    session_id: str | None,
    user_id: str | None,
    decision: SkillRouteDecision | None = None,
    user_message: str = "",
    stm_snapshot: str = "",
    ltm_summary: str = "",
    max_replans: int = 2,
) -> dict[str, Any]:
    current_plan = _normalize_plan(tool_plan)
    attempts = 0
    last_error: str = ""

    with skill_trace_context(
        session_id=session_id,
        user_id=user_id,
        selected_skill_family="tushare-data",
        selected_skill="tushare-data",
        analysis_mode="general_chat",
        execution_policy="deterministic",
    ):
        while True:
            try:
                _validate_plan(current_plan)
                order = _topological_order(current_plan)
                toolkit = _toolkit_by_name()
                tool_results: list[tuple[str, dict[str, Any]]] = []
                for i in order:
                    step = current_plan[i]
                    args = _normalize_tool_arguments(step.arguments)
                    if user_message:
                        args.setdefault("query", user_message)
                    with trace_span(
                        "tushare_tool_call",
                        stage="executor",
                        data={
                            "step": i,
                            "tool_name": step.tool_name,
                            "depends_on": list(step.depends_on or []),
                            "args_summary": {k: str(v)[:200] for k, v in args.items()},
                        },
                    ):
                        tool = toolkit.get(step.tool_name)
                        if tool is None:
                            raise RuntimeError(f"tool_not_found: {step.tool_name}")
                        result = await tool.ainvoke(args)
                        if not isinstance(result, dict):
                            raise RuntimeError(
                                f"unexpected_tool_result_type tool={step.tool_name} type={type(result).__name__}"
                            )
                    tool_results.append((step.tool_name, result))

                planned_tools = [step.tool_name for step in current_plan]
                trace_payload = _executor_trace_payload(
                    planned_tools=planned_tools,
                    tool_results=tool_results,
                    entities=entities,
                )
                return {
                    "ok": True,
                    "entities": _entity_payload(entities),
                    "planned_tools": planned_tools,
                    "results": [{"tool_name": name, "result": res} for name, res in tool_results],
                    "result_by_tool": {name: res for name, res in tool_results},
                    "executor_trace": trace_payload,
                    "replan_attempts": attempts,
                }
            except Exception as exc:
                last_error = str(exc)
                logger.warning("[tushare_plan_executor] execute attempt=%s failed: %s", attempts + 1, exc, exc_info=True)
                can_replan = attempts < max_replans and decision is not None
                if not can_replan:
                    log_degrade_transition(from_stage="executor", reason=f"tushare_execute_failed: {last_error}")
                    planned_tools = [step.tool_name for step in current_plan]
                    trace_payload = _executor_trace_payload(
                        planned_tools=planned_tools,
                        tool_results=[],
                        entities=entities,
                        failure_code="tool_invocation_error",
                        missing_reasons=[last_error],
                    )
                    return {
                        "ok": False,
                        "entities": _entity_payload(entities),
                        "planned_tools": planned_tools,
                        "results": [],
                        "result_by_tool": {},
                        "executor_trace": trace_payload,
                        "replan_attempts": attempts,
                        "error": last_error,
                    }

                attempts += 1
                with trace_span(
                    "tushare_replan",
                    stage="executor",
                    data={"attempt": attempts, "error": last_error},
                ):
                    replan_query = f"{user_message}\n\n[上一轮执行错误]\n{last_error}"
                    rewritten = await rewrite_for_tushare(
                        decision,
                        replan_query,
                        stm_snapshot=stm_snapshot,
                        ltm_summary=ltm_summary,
                    )
                    current_plan = _normalize_plan(rewritten.tool_plan)
                    if not current_plan:
                        raise RuntimeError("replan_empty_tool_plan")


__all__ = [
    "execute_tushare_plan",
]
