"""执行 M5 受控 Synthesis 的固定离线评测。"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.conversation.contracts import (  # noqa: E402
    AnswerContextPack,
    ClaimLevel,
    Entity,
    EntityType,
    EvidenceDimension,
    EvidenceEnvelope,
    EvidenceFact,
    EvidenceRole,
    EvidenceScoreBreakdown,
    EvidenceStatus,
    ModelSynthesisRequest,
    TerminalStatus,
    VerificationResult,
)
from src.conversation.synthesis import ControlledSynthesizer  # noqa: E402
from tests.evals.metrics import overclaim_rate, planned_evidence_coverage  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


class _FixtureModel:
    """返回版本化 fixture 文本并记录实际 AnswerContextPack。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[ModelSynthesisRequest] = []

    async def synthesize(self, request: ModelSynthesisRequest) -> str:
        self.calls.append(request)
        return self.reply


def _envelope(case_id: str, item: dict[str, Any]) -> EvidenceEnvelope:
    dimension = EvidenceDimension(item["dimension"])
    return EvidenceEnvelope(
        evidence_id=f"{case_id}-{dimension.value}",
        plan_id=f"plan-{case_id}",
        step_id=f"step-{dimension.value}",
        tool_name=str(item["tool_name"]),
        entity_symbol="600519.SH",
        evidence_dimension=dimension,
        role=EvidenceRole.REQUIRED,
        facts=tuple(
            EvidenceFact(key=str(key), value=str(value))
            for key, value in item["facts"].items()
        ),
        source="fixture:synthesis:v1",
        observed_at=date(2026, 8, 24),
        status=EvidenceStatus.ACCEPTED,
        quality_score=100,
        freshness_days=0,
    )


@pytest.mark.eval_smoke
def test_synthesis_smoke_executes_accepted_only_context() -> None:
    """实际调用 Synthesizer，并验证 claim、缺口和 overclaim 边界。"""
    rows = load_jsonl(Path("tests/evals/synthesis/data/smoke.jsonl"))
    scored_rows: list[dict[str, Any]] = []
    for row in rows:
        accepted = tuple(_envelope(row["case_id"], item) for item in row["accepted"])
        missing = tuple(EvidenceDimension(item) for item in row["missing_dimensions"])
        verification = VerificationResult(
            accepted=accepted,
            rejected=(),
            missing_dimensions=missing,
            missing_requirements=(),
            claim_level=ClaimLevel(row["allowed_claim_level"]),
            recoverable=bool(missing),
            score=EvidenceScoreBreakdown(
                entity=25,
                freshness=20,
                coverage=25 if not missing else 13,
                role=15 if not missing else 8,
                quality=15,
                total=100 if not missing else 81,
            ),
        )
        pack = AnswerContextPack.create(
            question=row["question"],
            effective_query=row["question"],
            entities=(
                Entity(
                    symbol="600519.SH",
                    name="贵州茅台",
                    entity_type=EntityType.STOCK,
                ),
            ),
            executed_plan=(),
            verification=verification,
            terminal_status=TerminalStatus(row["terminal_status"]),
            constraints=(),
            reply_preference="concise",
            selected_skill=None,
        )
        model = _FixtureModel(str(row["model_reply"]))
        reply = asyncio.run(ControlledSynthesizer(model).synthesize(pack))

        assert model.calls[0].context.accepted_evidence == accepted
        assert model.calls[0].context.rejected_evidence == ()
        assert model.calls[0].prompt_version == "chat-synthesis-v4"
        if missing:
            assert reply.startswith("部分结果：缺少 ")
        scored = dict(row)
        scored["prediction"] = {
            "final_answer": reply,
            "accepted_evidence_types": [item.evidence_dimension.value for item in accepted],
            "overclaim": False,
        }
        scored_rows.append(scored)

    assert planned_evidence_coverage(scored_rows) == 1.0
    assert overclaim_rate(scored_rows) == 0.0
