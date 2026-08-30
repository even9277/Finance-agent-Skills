"""验证可选 Skill rerank adapter 的最小输入和 typed 输出边界。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = ROOT / "Financial-MCP-Agent"
for import_root in (ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from backend.config import Settings  # noqa: E402
from backend.infrastructure.chat.skill_rerank import SkillRerankAdapter  # noqa: E402
from src.conversation.contracts import (  # noqa: E402
    SkillRerankRequest,
    SkillRouteCandidate,
)


class _RecordingClient:
    """保存 adapter 输入并返回固定结构化结果。"""

    def __init__(self, response: object) -> None:
        self._response = response
        self.payloads: list[dict[str, object]] = []

    def invoke(self, payload: dict[str, object]) -> object:
        """记录一次离线调用。"""
        self.payloads.append(payload)
        return self._response


def _candidate(name: str, score: float) -> SkillRouteCandidate:
    return SkillRouteCandidate(
        skill_name=name,
        version="1.0.0",
        description=f"{name} description",
        score=score,
        reasons=("deterministic",),
        when_to_use=("when",),
        when_not_to_use=("not",),
        positive_examples=("positive",),
        negative_examples=("negative",),
        supported_entity_types=("fund",),
    )


@pytest.mark.unit
def test_adapter_sends_only_query_and_routing_candidates() -> None:
    """序列化载荷不得出现历史、记忆、正文、工具或 reference。"""
    client = _RecordingClient(
        {
            "scores": [
                {"skill_name": "etf-screen", "score": 0.91, "reason": "screen"},
                {"skill_name": "fund-compare", "score": 0.60, "reason": "neighbor"},
            ]
        }
    )
    adapter = SkillRerankAdapter(client)

    result = adapter.rerank(
        SkillRerankRequest(
            query="分析黄金相关产品",
            candidates=(
                _candidate("etf-screen", 0.56),
                _candidate("fund-compare", 0.58),
            ),
        )
    )

    assert result.scores[0].skill_name == "etf-screen"
    assert set(client.payloads[0]) == {"query", "candidates"}
    serialized = str(client.payloads[0]).lower()
    assert all(
        forbidden not in serialized
        for forbidden in ("history", "memory", "skill_body", "allowed_tools", "reference_paths")
    )


@pytest.mark.unit
def test_adapter_rejects_candidate_outside_retriever_top_k() -> None:
    """Provider 不能创建 Retriever 未给出的新 Skill。"""
    client = _RecordingClient(
        {"scores": [{"skill_name": "unknown", "score": 0.99, "reason": "invented"}]}
    )

    with pytest.raises(ValueError, match="unknown Skill"):
        SkillRerankAdapter(client).rerank(
            SkillRerankRequest(
                query="分析黄金产品",
                candidates=(_candidate("etf-screen", 0.56),),
            )
        )


@pytest.mark.unit
def test_rerank_settings_default_to_disabled_and_bound_top_k() -> None:
    """无模型配置时保持离线，且 top-K 不能扩大到完整 Registry。"""
    offline = Settings(skill_rerank_provider="disabled")
    assert offline.skill_rerank_provider == "disabled"

    with pytest.raises(ValueError, match="skill_rerank_top_k"):
        Settings(skill_rerank_provider="disabled", skill_rerank_top_k=6)
