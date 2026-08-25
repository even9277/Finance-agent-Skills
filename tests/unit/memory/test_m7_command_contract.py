"""M7 记忆命令解析和结果合同的先行约束。

这些用例在实现前以严格 ``xfail`` 形式锁定目标行为；M2 完成后必须移除
``TARGET_GAP``，让它们成为默认离线门禁。
"""

from __future__ import annotations

import importlib

import pytest


TARGET_GAP = pytest.mark.xfail(
    strict=True,
    reason="M7 command parser/application contract is not implemented yet",
)


def _commands_module():
    """加载 M7 命令模块；模块缺失时由严格 xfail 暴露实现缺口。"""
    return importlib.import_module("backend.application.memory.commands")


@pytest.mark.unit
def test_explicit_low_impact_update_is_parsed_without_model_call() -> None:
    """明确的低影响偏好更新应形成确定性 UPDATE 意图。"""
    module = _commands_module()
    intent = module.parse_memory_command(
        "以后回答简短一点",
        user_id="fixture-user-memory",
        session_id="fixture-session-memory",
    )

    assert intent is not None
    assert intent.kind.value == "UPDATE"
    assert intent.scope.profile_field == "response_pref"
    assert intent.requires_confirmation is False
    assert intent.parser_version == "memory-command-v1"


@pytest.mark.unit
def test_broad_forget_creates_confirmation_required_intent() -> None:
    """宽范围文本记忆清理必须先预览并等待一次性确认。"""
    module = _commands_module()
    intent = module.parse_memory_command(
        "忘掉我的文本记忆",
        user_id="fixture-user-memory",
        session_id="fixture-session-memory",
    )

    assert intent is not None
    assert intent.kind.value == "FORGET"
    assert intent.scope.category == "text"
    assert intent.requires_confirmation is True


@pytest.mark.unit
def test_ordinary_finance_message_falls_through_as_non_command() -> None:
    """普通金融问题不能被误判为记忆命令。"""
    module = _commands_module()
    intent = module.parse_memory_command(
        "分析一下宁德时代近期的估值和风险",
        user_id="fixture-user-memory",
        session_id="fixture-session-memory",
    )

    assert intent is None


@pytest.mark.unit
def test_command_result_has_safe_shared_status_contract() -> None:
    """命令结果必须具备 REST、WebSocket 和前端共用的稳定字段。"""
    module = _commands_module()
    result = module.MemoryCommandResult(
        status=module.MemoryCommandStatus.SUCCEEDED,
        command_kind=module.MemoryCommandKind.UPDATE,
        command_ref="mcmd_fixture_001",
        affected_count=1,
        consistency_status="CONSISTENT",
        user_message="已更新你的回答偏好。",
    )

    assert result.status.value == "SUCCEEDED"
    assert result.command_ref == "mcmd_fixture_001"
    assert result.affected_count == 1
    assert result.user_message
    assert not hasattr(result, "raw_message")
