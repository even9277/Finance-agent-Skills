"""锁定 OpenAI-compatible Provider 的真实异步 chunk 转换。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessageChunk

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.infrastructure.chat.providers import OpenAICompatibleModelProvider  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    AnswerContextPack,
    ClaimLevel,
    ModelSynthesisRequest,
    TerminalStatus,
)


class _ChunkingClient:
    """模拟 LangChain 依次产生内容、空 usage chunk 和内容。"""

    def __init__(self) -> None:
        self.calls: list[list[object]] = []

    async def astream(self, messages: list[object]):
        self.calls.append(messages)
        for content in ("第一段", "", "第二段"):
            yield AIMessageChunk(content=content)


def _request() -> ModelSynthesisRequest:
    """构造只包含安全结构化上下文的模型请求。"""
    pack = AnswerContextPack(
        question="离线问题",
        effective_query="离线问题",
        entities=(),
        executed_plan=(),
        accepted_evidence=(),
        rejected_evidence=(),
        rejection_summaries=(),
        missing_dimensions=(),
        claim_level=ClaimLevel.DESCRIPTIVE,
        terminal_status=TerminalStatus.SUCCEEDED,
        constraints=(),
        reply_preference="concise",
        selected_skill=None,
    )
    return ModelSynthesisRequest(
        prompt_version="test-v1", system_prompt="安全系统提示", context=pack
    )


@pytest.mark.unit
def test_provider_yields_each_non_empty_langchain_chunk_without_post_slicing() -> None:
    """Provider 必须过滤空 chunk，并保持真实上游顺序和序号。"""

    async def run_case() -> None:
        client = _ChunkingClient()
        provider = cast(Any, object.__new__(OpenAICompatibleModelProvider))
        provider._client = client
        provider._model_name = "offline-model"

        chunks = [chunk async for chunk in provider.stream_synthesize(_request())]

        assert [(item.index, item.content) for item in chunks] == [
            (1, "第一段"),
            (2, "第二段"),
        ]
        assert len(client.calls) == 1

    asyncio.run(run_case())
