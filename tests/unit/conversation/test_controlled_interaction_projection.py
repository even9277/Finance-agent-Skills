"""锁定 D04 Application 白名单投影与同一背压事件流。"""

from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.application.chat.contracts import (  # noqa: E402
    ChatCommand,
    ChatContentDelta,
    ChatStreamCompleted,
    ChatStreamStarted,
)
from backend.application.chat.use_case import ControlledChatUseCase  # noqa: E402
from backend.infrastructure.chat.testing import InMemoryConversationRepository  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    ClaimLevel,
    ConversationResult,
    ConversationRunContext,
    Entity,
    EntityType,
    ErrorCode,
    EvidenceDimension,
    EvidenceFact,
    EvidenceRequirement,
    EvidenceScoreBreakdown,
    StageName,
    StageStatus,
    TerminalStatus,
    ToolArgument,
    ToolObservation,
    ToolPermissionSnapshot,
    ToolPlan,
    ToolPlanStep,
    ValidatedToolPlan,
    VerificationResult,
)


def _progress_api() -> Any:
    """加载领域进度合同。"""
    return importlib.import_module("src.conversation.progress")


def _projection_api() -> Any:
    """加载 Application 安全投影模块。"""
    return importlib.import_module("backend.application.chat.progress")


def _plan() -> ValidatedToolPlan:
    """构造包含可公开字段和禁止字段的已校验计划。"""
    step = ToolPlanStep(
        step_id="market-step",
        tool_name="get_market_bars",
        symbol="600519.SH",
        evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
        required=True,
        arguments=(ToolArgument(name="limit", value=5),),
        idempotency_key="PRIVATE_IDEMPOTENCY_KEY",
        template_step="market_snapshot",
    )
    return ValidatedToolPlan(
        plan=ToolPlan(
            plan_id="plan-d04",
            entity=Entity(
                symbol="600519.SH",
                name="贵州茅台",
                entity_type=EntityType.STOCK,
            ),
            entities=(
                Entity(
                    symbol="600519.SH",
                    name="贵州茅台",
                    entity_type=EntityType.STOCK,
                ),
            ),
            steps=(step,),
            requirements=(
                EvidenceRequirement(
                    dimension=EvidenceDimension.MARKET_SNAPSHOT,
                    required=True,
                    entity_symbol="600519.SH",
                ),
            ),
            objective="分析行情证据",
        ),
        permissions=ToolPermissionSnapshot(
            permissions=(),
            source="fixture",
            version="v1",
            snapshot_hash="PRIVATE_PERMISSION_HASH",
        ),
        execution_layers=((step.step_id,),),
    )


def _verification() -> VerificationResult:
    """构造权威 Verifier 的部分证据结果。"""
    return VerificationResult(
        accepted=(),
        rejected=(),
        missing_dimensions=(EvidenceDimension.FINANCIAL_INDICATOR,),
        missing_requirements=(
            EvidenceRequirement(
                dimension=EvidenceDimension.FINANCIAL_INDICATOR,
                required=True,
                entity_symbol="600519.SH",
            ),
        ),
        claim_level=ClaimLevel.DESCRIPTIVE,
        recoverable=False,
        score=EvidenceScoreBreakdown(
            entity=20,
            freshness=20,
            coverage=10,
            role=10,
            quality=10,
            total=70,
        ),
    )


def _project(event: Any) -> Any:
    """使用稳定关联字段执行一次公开投影。"""
    return _projection_api().project_progress_event(
        event,
        request_id="request-d04",
        session_id="session-d04",
    )


@pytest.mark.unit
def test_validated_plan_projection_contains_only_user_safe_fields() -> None:
    """D04-C01：计划预览必须来自 ValidatedToolPlan 且禁止整体透传。"""
    progress = _progress_api()
    public = _project(
        progress.PlanPreviewProgress(
            validated_plan=_plan(),
            revision=1,
        )
    )

    assert public.kind.value == "PLAN_PREVIEW"
    assert public.plan_id == "plan-d04"
    assert public.revision == 1
    assert public.validated is True
    assert len(public.steps) == 1
    assert public.steps[0].step_id == "market-step"
    assert public.steps[0].status.value == "PLANNED"
    assert public.steps[0].subject_summary == "贵州茅台（600519.SH）"
    serialized = repr(public)
    assert "PRIVATE_IDEMPOTENCY_KEY" not in serialized
    assert "PRIVATE_PERMISSION_HASH" not in serialized
    assert "arguments=" not in serialized


@pytest.mark.unit
def test_tool_projection_redacts_raw_arguments_facts_and_exception_text() -> None:
    """D04-C03：工具卡只允许显示白名单摘要和稳定错误码。"""
    progress = _progress_api()
    observation = ToolObservation(
        step_id="market-step",
        tool_name="get_market_bars",
        symbol="600519.SH",
        evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
        facts=(EvidenceFact(key="secret_fact", value="SECRET_FACT_VALUE"),),
        source="PRIVATE_PROVIDER_SOURCE",
        observed_at=date(2026, 9, 3),
        attempts=1,
        error_code=ErrorCode.TOOL_EXECUTION_FAILED,
        error_message="SECRET_EXCEPTION_DETAIL",
    )
    public = _project(
        progress.ToolStatusProgress(
            plan_id="plan-d04",
            revision=1,
            tool_call_id="call-d04",
            step_id="market-step",
            tool_name="get_market_bars",
            symbol="600519.SH",
            evidence_dimension=EvidenceDimension.MARKET_SNAPSHOT,
            arguments=(
                ToolArgument(name="limit", value=5),
                ToolArgument(name="token", value="SECRET_TOKEN"),
            ),
            status=progress.ProgressToolStatus.FAILED,
            attempt=1,
            elapsed_ms=12.5,
            observation=observation,
            error_code=ErrorCode.TOOL_EXECUTION_FAILED,
        )
    )

    assert public.display_name == "行情数据工具"
    assert public.status.value == "FAILED"
    assert public.parameter_summary == ("标的：600519.SH", "数据条数：5")
    assert public.result_summary == "调用失败"
    assert public.error_code == "TOOL_EXECUTION_FAILED"
    serialized = repr(public)
    for forbidden in (
        "SECRET_TOKEN",
        "SECRET_FACT_VALUE",
        "PRIVATE_PROVIDER_SOURCE",
        "SECRET_EXCEPTION_DETAIL",
    ):
        assert forbidden not in serialized


@pytest.mark.unit
def test_verification_projection_uses_authoritative_result_not_tool_count() -> None:
    """D04-C03：充分性、结论等级与缺口只能由 Verifier 结果投影。"""
    progress = _progress_api()
    public = _project(
        progress.VerificationSummaryProgress(
            plan_id="plan-d04",
            revision=1,
            verification=_verification(),
        )
    )

    assert public.sufficiency.value == "PARTIAL"
    assert public.claim_level == "DESCRIPTIVE"
    assert public.accepted_count == 0
    assert public.rejected_count == 0
    assert public.covered_dimensions == ()
    assert public.missing_dimensions == ("financial_indicator",)
    assert public.limitation == "部分关键证据缺失，结论仅作描述性参考。"


@pytest.mark.unit
def test_application_progress_shares_stream_backpressure_and_order() -> None:
    """D04-C01/C06：控制事件必须经过 D03 同一确认队列并先于正文。"""

    class _ProgressWorkflow:
        async def run(self, *args: Any, **kwargs: Any) -> ConversationResult:
            del args
            progress = _progress_api()
            observer = kwargs["progress_observer"]
            await observer.on_progress(
                progress.TraceSummaryProgress(
                    stage=StageName.VALIDATE,
                    status=StageStatus.SUCCEEDED,
                    elapsed_ms=1.5,
                )
            )
            await kwargs["on_content_delta"]("正文")
            return ConversationResult(
                status=TerminalStatus.SUCCEEDED,
                reply="正文",
                context=ConversationRunContext(
                    trace_id="trace-d04",
                    run_id="run-d04",
                    session_id="session-d04",
                    request_id="request-d04",
                    turn_index=1,
                ),
                events=(),
            )

    async def run_case() -> None:
        app_contracts = importlib.import_module("backend.application.chat.contracts")
        repository = InMemoryConversationRepository()
        use_case = ControlledChatUseCase(
            workflow=_ProgressWorkflow(),  # type: ignore[arg-type]
            repository=repository,
        )
        events = [
            event
            async for event in use_case.stream(
                ChatCommand(
                    user_id="user-d04",
                    message="固定问题",
                    session_id="session-d04",
                    request_id="request-d04",
                )
            )
        ]

        assert [type(event) for event in events] == [
            ChatStreamStarted,
            app_contracts.ChatTraceSummary,
            ChatContentDelta,
            ChatStreamCompleted,
        ]
        assert repository.committed is True
        assert repository.rolled_back is False

    asyncio.run(run_case())
