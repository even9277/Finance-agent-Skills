"""锁定模型 Provider 与受控合成器的真实增量合同。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.conversation.contracts import (  # noqa: E402
    AnswerContextPack,
    ClaimLevel,
    EvidenceDimension,
    ModelSynthesisChunk,
    ModelSynthesisRequest,
    TerminalStatus,
)
from src.conversation.synthesis import ControlledSynthesizer  # noqa: E402


def _pack(*, partial: bool = False) -> AnswerContextPack:
    """构造不依赖工具执行的最小安全合成上下文。"""
    return AnswerContextPack(
        question="给出受控结论",
        effective_query="给出受控结论",
        entities=(),
        executed_plan=(),
        accepted_evidence=(),
        rejected_evidence=(),
        rejection_summaries=(),
        missing_dimensions=(EvidenceDimension.MARKET_SNAPSHOT,) if partial else (),
        claim_level=ClaimLevel.DESCRIPTIVE,
        terminal_status=TerminalStatus.PARTIAL if partial else TerminalStatus.SUCCEEDED,
        constraints=(),
        reply_preference="concise",
        selected_skill=None,
    )


class _StreamingModel:
    """只实现新增量 Port，防止合成器继续依赖完整字符串接口。"""

    def __init__(self, chunks: tuple[str, ...]) -> None:
        self._chunks = chunks
        self.calls: list[ModelSynthesisRequest] = []

    async def stream_synthesize(self, request: ModelSynthesisRequest):
        """按固定顺序返回多个非空模型增量。"""
        self.calls.append(request)
        for index, content in enumerate(self._chunks, start=1):
            yield ModelSynthesisChunk(content=content, index=index)


@pytest.mark.unit
def test_controlled_synthesizer_forwards_chunks_and_reconstructs_same_reply() -> None:
    """增量顺序与最终聚合文本必须来自同一模型流。"""

    async def run_case() -> None:
        stream_model = _StreamingModel(("第一段", "第二段"))
        streamed = [
            content async for content in ControlledSynthesizer(stream_model).stream(_pack())
        ]
        assert streamed == ["第一段", "第二段"]
        assert len(stream_model.calls) == 1

        aggregate_model = _StreamingModel(("第一段", "第二段"))
        reply = await ControlledSynthesizer(aggregate_model).synthesize(_pack())
        assert reply == "第一段第二段"
        assert len(aggregate_model.calls) == 1

    asyncio.run(run_case())


@pytest.mark.unit
def test_partial_prefix_is_an_explicit_first_delta() -> None:
    """业务 PARTIAL 的缺口说明必须进入可见流且只出现一次。"""

    async def run_case() -> None:
        model = _StreamingModel(("保守结论。",))
        chunks = [
            content async for content in ControlledSynthesizer(model).stream(_pack(partial=True))
        ]

        assert chunks == ["部分结果：缺少 market_snapshot 证据。", "保守结论。"]
        assert "".join(chunks) == await ControlledSynthesizer(
            _StreamingModel(("保守结论。",))
        ).synthesize(_pack(partial=True))

    asyncio.run(run_case())
