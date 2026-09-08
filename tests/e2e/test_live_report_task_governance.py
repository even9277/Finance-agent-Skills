"""D06 受保护真实报告并发幂等验收入口。"""

from __future__ import annotations

import importlib
import os

import pytest

_LIVE_SWITCH = "RUN_PROTECTED_LIVE_REPORT_GOVERNANCE_E2E"


def _require_live_gate() -> None:
    """默认跳过；只有显式授权开关存在时才允许进入真实报告装配。"""
    if os.getenv(_LIVE_SWITCH, "").strip().lower() != "true":
        pytest.skip(f"需要显式设置 {_LIVE_SWITCH}=true")


@pytest.mark.live
@pytest.mark.e2e
def test_live_twenty_retries_execute_one_real_report() -> None:
    """D06-T10：最终必须以一份真实报告证明二十次重试只执行一次。"""
    _require_live_gate()
    try:
        harness = importlib.import_module("tests.e2e.report_task_governance_live_harness")
    except ModuleNotFoundError:
        pytest.fail("D06 protected live harness 尚未实现", pytrace=False)

    evidence = harness.run_protected_live_report_governance_case(request_count=20)
    assert evidence.request_count == 20
    assert evidence.app_instance_count == 2
    assert evidence.request_distribution == (10, 10)
    assert evidence.unique_task_count == 1
    assert evidence.unique_report_count == 1
    assert evidence.created_count == 1
    assert evidence.replayed_count == 19
    assert evidence.workflow_execution_count == 1
    assert evidence.workflow_fallback_count == 0
    assert evidence.model_call_count >= 5
    assert evidence.tushare_call_count >= 1
    assert evidence.snapshot_version >= 2
    assert evidence.sse_sequences == tuple(sorted(set(evidence.sse_sequences)))
    assert evidence.terminal_status == "completed"
    assert evidence.rest_status == "completed"
    assert len(evidence.content_sha256) == 64
    assert evidence.redaction_check == "passed"
