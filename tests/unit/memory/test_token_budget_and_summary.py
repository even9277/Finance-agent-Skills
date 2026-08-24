"""验证短期记忆预算、protected tail 与结构化摘要门控。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.application.memory.context import (  # noqa: E402
    ContextBudgetPolicy,
    ContextTextItem,
)
from backend.application.memory.summary import (  # noqa: E402
    SUMMARY_PROMPT_VERSION,
    SummaryDraft,
    SummaryValidationError,
    validate_summary_draft,
)


def test_context_budget_keeps_current_input_and_newest_raw_tail() -> None:
    """预算不足时优先保留当前输入和最近原文，较早消息才可丢弃。"""
    policy = ContextBudgetPolicy(
        model_window_tokens=120,
        output_reserve_tokens=30,
        safety_margin_tokens=10,
        stage_overhead_tokens=10,
    )
    messages = tuple(
        ContextTextItem(message_id=index, text=f"user: 第 {index} 条历史消息" * 4)
        for index in range(1, 7)
    )

    packed = policy.pack(
        current_message="当前必须保留的问题",
        recent_messages=messages,
        running_summary="更早历史摘要" * 5,
    )

    assert packed.current_message == "当前必须保留的问题"
    assert packed.used_tokens <= packed.input_budget_tokens
    assert packed.recent_messages[-1].message_id == 6
    assert tuple(item.message_id for item in packed.recent_messages) == tuple(
        sorted(item.message_id for item in packed.recent_messages)
    )
    assert packed.dropped_message_count > 0


def test_context_budget_never_builds_a_non_contiguous_raw_tail() -> None:
    """最新消息装不下时不得跳过它并注入更旧、更短的消息。"""
    policy = ContextBudgetPolicy(
        model_window_tokens=80,
        output_reserve_tokens=20,
        safety_margin_tokens=10,
        stage_overhead_tokens=10,
    )
    packed = policy.pack(
        current_message="当前问题",
        recent_messages=(
            ContextTextItem(message_id=1, text="旧"),
            ContextTextItem(message_id=2, text="最新消息" * 100),
        ),
        running_summary=None,
    )

    assert packed.recent_messages == ()
    assert packed.dropped_message_count == 2


def test_summary_boundary_must_end_before_protected_tail() -> None:
    """摘要来源边界不得覆盖 protected tail 中的任何消息。"""
    draft = SummaryDraft(
        summary="此前讨论了贵州茅台的基本面，用户要求风险优先。",
        source_start_message_id=1,
        source_end_message_id=8,
        source_message_count=8,
        prompt_version=SUMMARY_PROMPT_VERSION,
    )

    with pytest.raises(SummaryValidationError, match="protected tail"):
        validate_summary_draft(
            draft,
            expected_start_message_id=1,
            expected_end_message_id=7,
            expected_message_count=7,
            protected_tail_start_message_id=8,
        )


def test_valid_summary_preserves_frozen_source_boundary() -> None:
    """合格摘要必须完整匹配任务冻结的来源区间和 Prompt 版本。"""
    draft = SummaryDraft(
        summary="此前讨论了贵州茅台的基本面；待继续核对估值。",
        source_start_message_id=1,
        source_end_message_id=7,
        source_message_count=7,
        prompt_version=SUMMARY_PROMPT_VERSION,
    )

    validated = validate_summary_draft(
        draft,
        expected_start_message_id=1,
        expected_end_message_id=7,
        expected_message_count=7,
        protected_tail_start_message_id=8,
    )

    assert validated == draft
