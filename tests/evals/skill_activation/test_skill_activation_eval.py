from pathlib import Path
import sys

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[3] / "Financial-MCP-Agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from src.conversation.skill_discovery import SkillDiscovery  # noqa: E402
from src.skills.skill_registry import SkillRegistry  # noqa: E402
from tests.evals.runner import load_jsonl  # noqa: E402


@pytest.mark.eval_smoke
def test_skill_activation_eval_executes_metadata_only_discovery() -> None:
    """执行五个 Skill 激活案例，禁止依赖完整 Skill 正文或模型调用。"""
    rows = load_jsonl(Path("tests/evals/skill_activation/data/smoke.jsonl"))
    snapshot = SkillRegistry().conversation_snapshot()
    discovery = SkillDiscovery(snapshot)

    for row in rows:
        match = discovery.discover(str(row["query"]), entities=())
        assert match.skill_name == row["gold"]["skill_id"], row["case_id"]
        assert match.confidence >= 0.85

    assert len(rows) == 5
