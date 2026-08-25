"""执行版本化、确定性的长期记忆治理离线评测。"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for path in (PROJECT_ROOT, AGENT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.memory.contracts import (  # noqa: E402
    CandidateDraft,
    CandidateEvidence,
    CandidateSignals,
    CandidateStatus,
    MemoryValueKind,
    ProfileField,
)
from src.memory.policy import evaluate_candidate_promotion  # noqa: E402

DATA_PATH = Path(__file__).resolve().parent / "data" / "ltm_v1.jsonl"


def _cases() -> list[dict[str, object]]:
    """读取不包含真实用户内容的 LTM 评测数据。"""
    return [json.loads(line) for line in DATA_PATH.read_text(encoding="utf-8").splitlines()]


@pytest.mark.eval_smoke
@pytest.mark.parametrize("case", _cases(), ids=lambda item: str(item["case_id"]))
def test_ltm_governance_offline_regression(case: dict[str, object]) -> None:
    """同一策略输入必须得到稳定状态和是否晋升结论。"""
    kind = MemoryValueKind(_text(case, "kind"))
    draft = CandidateDraft(
        kind=kind,
        category="response_preference" if kind is MemoryValueKind.TEXT else "profile_suggestion",
        normalized_key="response_preference:conclusion_first"
        if kind is MemoryValueKind.TEXT
        else "profile:risk_level:aggressive",
        confidence=0.95,
        evidence=(
            CandidateEvidence(
                session_id="eval-session",
                message_id=1,
                source_role="user",
                query_hash="eval-query",
                observed_on=datetime(2026, 8, 25, tzinfo=UTC).date(),
                confidence=0.95,
            ),
        ),
        profile_field=ProfileField.RISK_LEVEL if kind is MemoryValueKind.STRUCTURED_PROFILE else None,
        value="aggressive" if kind is MemoryValueKind.STRUCTURED_PROFILE else None,
        content="回答先给结论" if kind is MemoryValueKind.TEXT else None,
        conflict_key="profile:risk_level" if kind is MemoryValueKind.STRUCTURED_PROFILE else None,
    )
    decision = evaluate_candidate_promotion(
        draft,
        CandidateSignals(
            event_count=_integer(case, "event_count"),
            unique_query_count=_integer(case, "unique_query_count"),
            unique_session_count=_integer(case, "unique_session_count"),
            active_days=_integer(case, "active_days"),
            contradiction_count=_integer(case, "contradiction_count"),
            average_confidence=0.95,
                first_seen_at=(
                    datetime.fromisoformat(_text(case, "last_seen")).replace(tzinfo=None)
                    - timedelta(days=10)
                ),
                last_seen_at=datetime.fromisoformat(_text(case, "last_seen")).replace(tzinfo=None),
        ),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert decision.status is CandidateStatus(_text(case, "expected_status"))
    assert decision.eligible is bool(case["expected_eligible"])


def _text(case: dict[str, object], key: str) -> str:
    """读取评测合同中的文本字段。"""
    return cast(str, case[key])


def _integer(case: dict[str, object], key: str) -> int:
    """读取评测合同中的整数门槛。"""
    return cast(int, case[key])
