"""锁定 D06 报告幂等键与持久快照的纯应用合同。"""

from __future__ import annotations

import importlib
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _contracts() -> ModuleType:
    """加载 D06 目标合同，使缺失实现表现为明确的测试失败。"""
    target = PROJECT_ROOT / "backend/application/report_tasks/contracts.py"
    assert target.is_file(), "D06 合同尚未实现：backend/application/report_tasks/contracts.py"
    return importlib.import_module("backend.application.report_tasks.contracts")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  分析   贵州茅台\t600519  ", "分析 贵州茅台 600519"),
        ("ＡＢＣ　１２３", "ABC 123"),
        ("Mix Case，保留！", "Mix Case,保留!"),
    ],
)
def test_normalize_report_command_is_cross_instance_deterministic(
    raw: str,
    expected: str,
) -> None:
    """D06-T01：NFKC 与空白折叠结果必须稳定且不擅自改大小写。"""
    contracts = _contracts()

    normalized = contracts.normalize_report_command(raw)

    assert normalized == expected
    assert contracts.normalize_report_command(normalized) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "short",
        "x" * 129,
        "contains space",
        "含中文的键值",
        "line-break\nkey",
    ],
)
def test_validate_idempotency_key_rejects_unsafe_values_without_echo(value: str) -> None:
    """D06-T01：非法显式键使用稳定错误码，且异常文本不得回显键值。"""
    contracts = _contracts()

    with pytest.raises(contracts.ReportIdempotencyValidationError) as error:
        contracts.validate_idempotency_key(value)

    assert error.value.error_code == "INVALID_IDEMPOTENCY_KEY"
    assert value not in str(error.value)


@pytest.mark.unit
def test_effective_key_preserves_legacy_command_hash_and_explicit_intent() -> None:
    """D06-T01：旧客户端走命令哈希，新请求显式键可表达新的生成意图。"""
    contracts = _contracts()
    command = "分析 贵州茅台 600519"

    implicit_a = contracts.build_effective_idempotency_material(command, None)
    implicit_b = contracts.build_effective_idempotency_material(
        "  分析   贵州茅台　600519 ",
        None,
    )
    explicit = contracts.build_effective_idempotency_material(
        command,
        "request-00000001",
    )

    assert implicit_a == implicit_b
    assert implicit_a.startswith("command:")
    assert explicit == "client:request-00000001"
    assert explicit != implicit_a


@pytest.mark.unit
def test_fingerprint_and_scoped_digest_hide_raw_identity_and_request() -> None:
    """D06-T01：数据库/Redis 使用固定 SHA-256 摘要，不扩散原始输入。"""
    contracts = _contracts()
    user_id = "private-user-d06"
    command = "分析隐私标的 600519"
    client_key = "request-private-0001"

    fingerprint = contracts.build_report_request_fingerprint(command)
    material = contracts.build_effective_idempotency_material(command, client_key)
    digest = contracts.build_scoped_idempotency_digest(
        user_id=user_id,
        effective_material=material,
        secret="fixture-secret-at-least-thirty-two-bytes",
    )

    assert len(fingerprint) == 64
    assert len(digest) == 64
    assert set(fingerprint) <= set(string.hexdigits.lower())
    assert set(digest) <= set(string.hexdigits.lower())
    assert all(raw not in digest for raw in (user_id, command, client_key))
    assert digest != contracts.build_scoped_idempotency_digest(
        user_id="another-user-d06",
        effective_material=material,
        secret="fixture-secret-at-least-thirty-two-bytes",
    )


@pytest.mark.unit
def test_report_task_snapshot_contract_is_typed_and_versioned() -> None:
    """D06-T04：最新快照必须显式承载版本、阶段和安全终态字段。"""
    contracts = _contracts()

    snapshot = contracts.ReportTaskSnapshot(
        task_id="task-d06",
        report_id="report-d06",
        snapshot_version=7,
        status="running",
        progress=65,
        stages=(
            contracts.ReportStageSnapshot(
                stage="FUNDAMENTAL_ANALYSIS",
                status="SUCCEEDED",
            ),
        ),
        updated_at="2026-09-05T00:00:00+00:00",
        error_code=None,
        message=None,
    )

    assert snapshot.snapshot_version == 7
    assert snapshot.progress == 65
    assert snapshot.stages[0].stage.value == "FUNDAMENTAL_ANALYSIS"
    with pytest.raises((TypeError, ValueError)):
        contracts.ReportTaskSnapshot(
            task_id="task-d06",
            report_id="report-d06",
            snapshot_version=6,
            status="running",
            progress=101,
            stages=(),
            updated_at="2026-09-05T00:00:00+00:00",
            error_code=None,
            message=None,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("fingerprint_matches", "status", "expired", "expected"),
    [
        (False, "pending", False, "CONFLICT"),
        (False, "completed", True, "CONFLICT"),
        (True, "pending", True, "REPLAY"),
        (True, "running", True, "REPLAY"),
        (True, "completed", False, "REPLAY"),
        (True, "failed", False, "REPLAY"),
        (True, "completed", True, "ROTATE"),
        (True, "failed", True, "ROTATE"),
    ],
)
def test_existing_task_decision_table_protects_running_and_rotates_expired_terminal(
    fingerprint_matches: bool,
    status: str,
    expired: bool,
    expected: str,
) -> None:
    """D06-T01：TTL 只允许过期终态换代，运行中任务始终复用。"""
    contracts = _contracts()
    now = datetime(2026, 9, 5, tzinfo=UTC)

    decision = contracts.decide_existing_report_task(
        existing_fingerprint="a" * 64,
        request_fingerprint="a" * 64 if fingerprint_matches else "b" * 64,
        task_status=status,
        expires_at=now + (timedelta(seconds=-1) if expired else timedelta(seconds=1)),
        now=now,
    )

    assert decision.value == expected
