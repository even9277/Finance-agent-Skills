"""验证旧报告分析 Agent 不向普通终端日志写入 Prompt 或模型正文。"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

_PROMPT_SENTINEL = "D05_PRIVATE_PROMPT_SENTINEL"
_OUTPUT_SENTINEL = "D05_PRIVATE_MODEL_OUTPUT_SENTINEL"
_EXCEPTION_SENTINEL = "Authorization=Bearer D05_PRIVATE_EXCEPTION_SENTINEL"


def _set_fake_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 fake Agent 测试不依赖开发机 `.env` 或 CI secrets。"""
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://offline.invalid/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "offline-test-model")


@pytest.mark.parametrize(
    ("module_name", "function_name"),
    [
        ("src.agents.fundamental_agent", "fundamental_agent"),
        ("src.agents.technical_agent", "technical_agent"),
        ("src.agents.value_agent", "value_agent"),
        ("src.agents.news_agent", "news_agent"),
    ],
)
def test_analysis_agent_terminal_logs_exclude_prompt_and_model_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    module_name: str,
    function_name: str,
) -> None:
    """完整运行轻量 fake Agent，确保普通日志与 stdout 只保留低敏元数据。"""
    module = importlib.import_module(module_name)
    logger = MagicMock()
    execution_logger = MagicMock()
    fake_agent = SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": []}))

    _set_fake_provider_env(monkeypatch)
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "get_execution_logger", lambda: execution_logger)
    monkeypatch.setattr(module, "ChatOpenAI", lambda **kwargs: object())
    monkeypatch.setattr(module, "get_mcp_tools", AsyncMock(return_value=[SimpleNamespace(name="safe")]))
    monkeypatch.setattr(module, "build_analysis_agent", lambda **kwargs: fake_agent)
    monkeypatch.setattr(module, "extract_final_text", lambda response: _OUTPUT_SENTINEL)

    agent = getattr(module, function_name)
    state: dict[str, Any] = {
        "data": {
            "query": _PROMPT_SENTINEL,
            "stock_code": "sh.600519",
            "company_name": "贵州茅台",
            "current_time_info": "2026年09月05日 03:00:00",
            "current_date": "2026-09-05",
        },
        "messages": [],
        "metadata": {},
    }
    asyncio.run(agent(state))

    captured = capsys.readouterr()
    public_output = captured.out + captured.err
    info_calls = "\n".join(str(call) for call in logger.info.call_args_list)
    assert _PROMPT_SENTINEL not in public_output
    assert _OUTPUT_SENTINEL not in public_output
    assert _PROMPT_SENTINEL not in info_calls
    assert _OUTPUT_SENTINEL not in info_calls


@pytest.mark.parametrize(
    ("module_name", "function_name"),
    [
        ("src.agents.fundamental_agent", "fundamental_agent"),
        ("src.agents.technical_agent", "technical_agent"),
        ("src.agents.value_agent", "value_agent"),
        ("src.agents.news_agent", "news_agent"),
    ],
)
def test_analysis_agent_failure_artifacts_exclude_raw_provider_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    module_name: str,
    function_name: str,
) -> None:
    """Provider 异常只能留下稳定错误类型和安全消息，不能进入状态或日志。"""
    module = importlib.import_module(module_name)
    logger = MagicMock()
    execution_logger = MagicMock()
    fake_agent = SimpleNamespace(
        ainvoke=AsyncMock(side_effect=RuntimeError(_EXCEPTION_SENTINEL))
    )

    _set_fake_provider_env(monkeypatch)
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "get_execution_logger", lambda: execution_logger)
    monkeypatch.setattr(module, "ChatOpenAI", lambda **kwargs: object())
    monkeypatch.setattr(
        module,
        "get_mcp_tools",
        AsyncMock(return_value=[SimpleNamespace(name="safe")]),
    )
    monkeypatch.setattr(module, "build_analysis_agent", lambda **kwargs: fake_agent)

    agent = getattr(module, function_name)
    state: dict[str, Any] = {
        "data": {
            "query": "分析贵州茅台 600519",
            "stock_code": "sh.600519",
            "company_name": "贵州茅台",
            "current_time_info": "2026年09月05日 03:00:00",
            "current_date": "2026-09-05",
        },
        "messages": [],
        "metadata": {},
    }
    result = asyncio.run(agent(state))

    captured = capsys.readouterr()
    public_evidence = "\n".join(
        (
            captured.out,
            captured.err,
            repr(result),
            repr(logger.method_calls),
            repr(execution_logger.method_calls),
        )
    )
    assert _EXCEPTION_SENTINEL not in public_evidence
    assert "RuntimeError" in repr(result)
