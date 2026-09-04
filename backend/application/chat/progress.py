"""把领域权威进度显式投影为用户安全的聊天事件。"""

from __future__ import annotations

from src.conversation.contracts import ClaimLevel, ToolArgument
from src.conversation.progress import (
    ConversationProgressEvent,
    PlanPreviewProgress,
    StepStatusProgress,
    ToolStatusProgress,
    TraceSummaryProgress,
    VerificationSummaryProgress,
)

from .contracts import (
    ChatEvidenceSufficiency,
    ChatPlanPreview,
    ChatPlanStepPreview,
    ChatStepLifecycleStatus,
    ChatStepStatus,
    ChatToolLifecycleStatus,
    ChatToolStatus,
    ChatTraceSummary,
    ChatVerificationSummary,
)

_TOOL_LABELS: dict[str, tuple[str, str, str]] = {
    "get_market_bars": ("行情数据工具", "获取行情数据", "补充行情证据"),
    "get_daily_bars": ("日线行情工具", "获取日线行情", "补充行情证据"),
    "get_index_bars": ("指数行情工具", "获取指数行情", "补充指数证据"),
    "get_stock_basic_info": ("股票资料工具", "获取股票资料", "确认标的基本信息"),
    "get_fina_indicator": ("财务指标工具", "获取财务指标", "补充财务指标证据"),
    "get_income": ("利润表工具", "获取利润表", "补充盈利能力证据"),
    "get_balance_sheet": ("资产负债表工具", "获取资产负债表", "补充财务结构证据"),
    "get_cashflow": ("现金流量表工具", "获取现金流量表", "补充现金流证据"),
    "search_web_news": ("公开资讯工具", "检索公开资讯", "补充公开资讯证据"),
}

_ARGUMENT_LABELS = {
    "limit": "数据条数",
    "start_date": "开始日期",
    "end_date": "结束日期",
    "trade_date": "交易日期",
    "period": "报告期",
}

_TRACE_SUMMARIES = {
    ("validate", "SUCCEEDED"): "执行计划已通过校验",
    ("validate", "FAILED"): "执行计划未通过校验",
    ("execute", "SUCCEEDED"): "受控工具执行完成",
    ("execute", "PARTIAL"): "部分受控工具执行失败",
    ("verify", "SUCCEEDED"): "证据校验完成",
    ("verify", "PARTIAL"): "证据校验发现缺口",
    ("replan", "SUCCEEDED"): "已生成补证计划",
    ("replan", "SKIPPED"): "没有可用的补证计划",
}


def project_progress_event(
    event: ConversationProgressEvent,
    *,
    request_id: str,
    session_id: str,
) -> (
    ChatTraceSummary
    | ChatPlanPreview
    | ChatStepStatus
    | ChatToolStatus
    | ChatVerificationSummary
):
    """白名单投影一个领域进度事件。

    Args:
        event: Workflow 或 Executor 产生的强类型权威进度。
        request_id: 当前公开流的请求关联 ID。
        session_id: Repository 准备完成后的会话 ID。

    Returns:
        不含原始参数、事实、Provider 信息或 Trace attributes 的应用事件。

    Raises:
        TypeError: 收到尚未登记投影规则的领域事件。
    """
    common = {"request_id": request_id, "session_id": session_id}
    if isinstance(event, TraceSummaryProgress):
        stage = event.stage.value
        status = event.status.value
        return ChatTraceSummary(
            **common,
            stage=stage,
            status=status,
            elapsed_ms=event.elapsed_ms,
            summary=_TRACE_SUMMARIES.get((stage, status), "受控阶段状态已更新"),
            error_code=event.error_code.value if event.error_code is not None else None,
        )
    if isinstance(event, PlanPreviewProgress):
        plan = event.validated_plan.plan
        entity_names = {item.symbol: item.name for item in plan.entities}
        if plan.entity is not None:
            entity_names.setdefault(plan.entity.symbol, plan.entity.name)
        return ChatPlanPreview(
            **common,
            plan_id=plan.plan_id,
            revision=event.revision,
            validated=True,
            steps=tuple(
                ChatPlanStepPreview(
                    step_id=step.step_id,
                    title=_tool_labels(step.tool_name)[1],
                    purpose=_tool_labels(step.tool_name)[2],
                    required=step.required,
                    status=ChatStepLifecycleStatus.PLANNED,
                    depends_on=step.depends_on,
                    subject_summary=_subject_summary(
                        step.symbol,
                        entity_names.get(step.symbol),
                    ),
                )
                for step in plan.steps
            ),
            replan_reason=(
                "根据证据缺口补充执行计划"
                if event.replan_reason is not None
                else None
            ),
            replaced_step_ids=event.replaced_step_ids,
        )
    if isinstance(event, StepStatusProgress):
        return ChatStepStatus(
            **common,
            plan_id=event.plan_id,
            revision=event.revision,
            step_id=event.step_id,
            status=ChatStepLifecycleStatus(event.status.value),
            elapsed_ms=event.elapsed_ms,
            error_code=event.error_code.value if event.error_code is not None else None,
        )
    if isinstance(event, ToolStatusProgress):
        return ChatToolStatus(
            **common,
            plan_id=event.plan_id,
            revision=event.revision,
            tool_call_id=event.tool_call_id,
            step_id=event.step_id,
            display_name=_tool_labels(event.tool_name)[0],
            status=ChatToolLifecycleStatus(event.status.value),
            attempt=event.attempt,
            elapsed_ms=event.elapsed_ms,
            parameter_summary=_parameter_summary(event.symbol, event.arguments),
            result_summary=_result_summary(event),
            error_code=event.error_code.value if event.error_code is not None else None,
        )
    if isinstance(event, VerificationSummaryProgress):
        verification = event.verification
        covered_dimensions = tuple(
            dict.fromkeys(item.evidence_dimension.value for item in verification.accepted)
        )
        return ChatVerificationSummary(
            **common,
            plan_id=event.plan_id,
            revision=event.revision,
            sufficiency=_evidence_sufficiency(verification.claim_level, bool(verification.missing_dimensions)),
            claim_level=verification.claim_level.value,
            accepted_count=len(verification.accepted),
            rejected_count=len(verification.rejected),
            covered_dimensions=covered_dimensions,
            missing_dimensions=tuple(item.value for item in verification.missing_dimensions),
            limitation=_verification_limitation(
                verification.claim_level,
                bool(verification.missing_dimensions),
            ),
        )
    raise TypeError(f"unsupported progress event: {type(event).__name__}")


def _tool_labels(tool_name: str) -> tuple[str, str, str]:
    """返回固定展示名、标题和用途，未知工具使用不泄露内部名称的兜底。"""
    return _TOOL_LABELS.get(tool_name, ("受控数据工具", "获取受控数据", "补充分析证据"))


def _subject_summary(symbol: str, name: str | None) -> str:
    """生成有界标的摘要。"""
    safe_symbol = symbol[:32]
    if name:
        return f"{name[:32]}（{safe_symbol}）"
    return safe_symbol


def _parameter_summary(
    symbol: str,
    arguments: tuple[ToolArgument, ...],
) -> tuple[str, ...]:
    """只序列化确定无敏感含义的工具参数。"""
    summaries = [f"标的：{symbol[:32]}"]
    for argument in arguments:
        label = _ARGUMENT_LABELS.get(argument.name)
        if label is None or not isinstance(argument.value, (str, int, float)):
            continue
        summaries.append(f"{label}：{str(argument.value)[:32]}")
        if len(summaries) >= 5:
            break
    return tuple(summaries)


def _result_summary(event: ToolStatusProgress) -> str | None:
    """由归一化状态生成固定短结果，不读取事实内容或异常原文。"""
    if event.status.value == "SUCCEEDED" and event.observation is not None:
        return f"已返回 {len(event.observation.facts)} 条可校验证据"
    if event.status.value == "FAILED":
        return "调用失败"
    if event.status.value == "SKIPPED":
        return "未执行"
    if event.status.value == "CANCELLED":
        return "已取消"
    return None


def _evidence_sufficiency(
    claim_level: ClaimLevel,
    has_missing_dimensions: bool,
) -> ChatEvidenceSufficiency:
    """仅依据 Verifier 的结论等级和证据缺口计算公开充分性。"""
    if claim_level is ClaimLevel.REFUSE:
        return ChatEvidenceSufficiency.INSUFFICIENT
    if has_missing_dimensions or claim_level is ClaimLevel.DESCRIPTIVE:
        return ChatEvidenceSufficiency.PARTIAL
    return ChatEvidenceSufficiency.SUFFICIENT


def _verification_limitation(
    claim_level: ClaimLevel,
    has_missing_dimensions: bool,
) -> str:
    """把 Verifier 结果转换为固定、可口述的证据限制。"""
    if claim_level is ClaimLevel.REFUSE:
        return "关键证据不足，无法形成可靠结论。"
    if has_missing_dimensions or claim_level is ClaimLevel.DESCRIPTIVE:
        return "部分关键证据缺失，结论仅作描述性参考。"
    return "证据满足当前分析要求。"
