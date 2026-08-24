"""验证摘要 Provider 在后台任务创建前完成配置校验。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.infrastructure.memory.summary import (  # noqa: E402
    DeterministicSummaryModelProvider,
    build_summary_model_provider,
)


@pytest.mark.unit
def test_deterministic_summary_provider_bootstraps_without_live_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """离线 Provider 不需要模型密钥且不会建立外部连接。"""
    monkeypatch.setattr(
        "backend.infrastructure.memory.summary.settings.stm_summary_provider",
        "deterministic",
    )

    provider = build_summary_model_provider()

    assert isinstance(provider, DeterministicSummaryModelProvider)


@pytest.mark.unit
def test_openai_summary_provider_rejects_incomplete_configuration_before_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 Provider 配置不完整时必须同步失败，不能留下死亡后台任务。"""
    monkeypatch.setattr(
        "backend.infrastructure.memory.summary.settings.stm_summary_provider",
        "openai",
    )
    monkeypatch.setattr(
        "backend.infrastructure.memory.summary.settings.openai_compatible_api_key",
        "",
    )

    with pytest.raises(RuntimeError, match="configuration is incomplete"):
        build_summary_model_provider()
