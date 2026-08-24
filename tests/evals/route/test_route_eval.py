from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "Financial-MCP-Agent"
for import_root in (PROJECT_ROOT, AGENT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from src.conversation.contracts import ContextPacket  # noqa: E402
from src.conversation.entity import AuthoritativeEntityResolver  # noqa: E402
from src.conversation.routing import TwoStageRouter  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


@pytest.mark.eval_smoke
def test_route_eval_executes_two_stage_router() -> None:
    """执行两阶段路由样例并校验最终路由和真实 Skill 名。"""
    rows = load_jsonl(Path("tests/evals/route/data/smoke.jsonl"))
    router = TwoStageRouter(SkillRegistry().conversation_snapshot())
    resolver = AuthoritativeEntityResolver()

    for row in rows:
        turns = row["turns"]
        packet = ContextPacket(
            current_message=str(turns[-1]["content"]),
            recent_messages=tuple(str(turn["content"]) for turn in turns[:-1]),
        )
        decision = router.route(packet, resolver.resolve(packet))
        assert decision.family.value == row["gold"]["final_route"], row["case_id"]
        assert decision.skill_name == row["gold"].get("skill_id"), row["case_id"]
        assert decision.confidence >= 0.85 or decision.family.value == "fallback"
