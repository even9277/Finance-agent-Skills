import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills_v2.version import SkillVersion, stable_hash_text  # noqa: E402


def test_stable_hash_text_normalizes_line_endings():
    assert stable_hash_text("a\r\nb\n") == stable_hash_text("a\nb")


def test_skill_version_defaults_and_normalizes_non_semver():
    assert SkillVersion("").normalized == "0.1.0"
    assert SkillVersion("1.2.3").normalized == "1.2.3"
    assert SkillVersion("draft").normalized.startswith("0.1.0+")
