from pathlib import Path
import sys

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[3] / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import ContextPacket  # noqa: E402
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


@pytest.mark.eval_smoke
def test_entity_eval_executes_authoritative_resolver() -> None:
    """执行版本化实体样例并验证显式、歧义、多实体和继承结果。"""
    rows = load_jsonl(Path("tests/evals/entity/data/smoke.jsonl"))
    resolver = AuthoritativeEntityResolver()

    for row in rows:
        turns = row["turns"]
        result = resolver.resolve(
            ContextPacket(
                current_message=str(turns[-1]["content"]),
                recent_messages=tuple(str(turn["content"]) for turn in turns[:-1]),
            )
        )
        gold = row["gold"]
        actual_status = (
            "ambiguous"
            if result.clarification
            else "resolved_multi"
            if len(result.resolved_entities) > 1
            else "resolved"
            if result.entity is not None
            else "no_entity"
        )
        assert actual_status == gold["resolution_status"], row["case_id"]
        assert (result.entity.entity_type.value if result.entity else "none") == gold["entity_type"]
        assert (result.entity.symbol if result.entity else "") == gold["canonical_id"]
        assert result.inherited is bool(gold["inherited"])
        if "candidate_ids" in gold:
            assert [item.symbol for item in result.candidates] == gold["candidate_ids"]
        if "resolved_ids" in gold:
            assert [item.symbol for item in result.resolved_entities] == gold["resolved_ids"]
