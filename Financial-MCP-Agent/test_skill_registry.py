import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skills.skill_registry import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def test_loads_vendor_skill_metadata(self):
        registry = SkillRegistry()
        skill = registry.get_skill("tushare-data")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "tushare-data")
        self.assertEqual(skill.official_name, "tushare")
        self.assertIn("get_daily_bars", skill.allowed_tools)
        self.assertIn("get_market_bars", skill.allowed_tools)
        self.assertIn("get_sector_snapshot", skill.allowed_tools)
        self.assertEqual(skill.source, "official_vendor")
        self.assertIn("tushare", skill.aliases)
        self.assertTrue(any(item["title"] == "历史日线" for item in skill.reference_index))

    def test_workspace_skill_overrides_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            skill_dir = tmp_path / "override_skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: tushare-data\ndescription: local override\n---\n",
                encoding="utf-8",
            )

            registry = SkillRegistry(skills_dir=tmp_path)
            skill = registry.get_skill("tushare-data")
            self.assertIsNotNone(skill)
            self.assertEqual(skill.description, "local override")
            self.assertEqual(skill.source, "workspace")

    def test_can_match_relevant_official_references(self):
        registry = SkillRegistry()
        refs = registry.find_references("tushare-data", "分析半导体板块今天行情", limit=5)
        self.assertTrue(refs)
        titles = {item["title"] for item in refs}
        self.assertTrue("通达信板块行情" in titles or "东财概念和行业指数行情" in titles)


if __name__ == "__main__":
    unittest.main()
