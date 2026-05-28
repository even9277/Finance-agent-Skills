import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills_v2.reference_index import ReferenceIndex  # noqa: E402


def test_reference_index_parses_frontmatter_and_filters_stage(tmp_path):
    skill_dir = tmp_path / "skill"
    refs = skill_dir / "references"
    refs.mkdir(parents=True)
    (refs / "规则.md").write_text(
        "---\ntitle: 新闻规则\ncategory: evidence\nstages:\n  - synthesis\nevidence_types:\n  - web_news\n---\n# 新闻规则\n只作为弱证据。",
        encoding="utf-8",
    )
    index = ReferenceIndex.from_skill_dir(skill_dir)
    assert index.items[0].title == "新闻规则"
    assert index.search("新闻", stage="rewrite") == []
    assert index.search("新闻", stage="synthesis")[0].path == "references/规则.md"
