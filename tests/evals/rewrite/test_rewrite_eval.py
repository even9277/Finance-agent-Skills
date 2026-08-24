from pathlib import Path
import sys

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[3] / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.contracts import ContextPacket  # noqa: E402
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from src.conversation.rewriting import RouteAwareRewriter  # noqa: E402
from src.conversation.routing import TwoStageRouter  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


@pytest.mark.eval_smoke
def test_rewrite_eval_executes_route_specific_rewriters() -> None:
    """执行三路 Rewrite 并验证约束、偏好、时间和实体不会丢失。"""
    rows = load_jsonl(Path("tests/evals/rewrite/data/smoke.jsonl"))
    snapshot = SkillRegistry().conversation_snapshot()
    router = TwoStageRouter(snapshot)
    resolver = AuthoritativeEntityResolver()
    rewriter = RouteAwareRewriter(snapshot)

    for row in rows:
        turns = row["turns"]
        packet = ContextPacket(
            current_message=str(turns[-1]["content"]),
            recent_messages=tuple(str(turn["content"]) for turn in turns[:-1]),
        )
        entities = resolver.resolve(packet)
        route = router.route(packet, entities)
        result = rewriter.rewrite(packet, entities, route)
        gold = row["gold"]
        assert route.family.value == gold["final_route"], row["case_id"]
        assert result.kind.value == gold["rewrite_kind"], row["case_id"]
        assert result.skill_name == gold.get("skill_id"), row["case_id"]
        assert list(result.data_requirements) == gold["data_requirements"], row["case_id"]
        assert result.reply_preference.hint == gold["reply_preference_hint"], row["case_id"]
        assert result.time_scope.value == gold["time_scope"], row["case_id"]
        if "constraints" in gold:
            assert list(result.constraints.items) == gold["constraints"]
        if "entity_ids" in gold:
            assert [item.symbol for item in result.entities] == gold["entity_ids"]
