import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.skills.route_metadata import RouteMetadataIndex
from src.skills.skill_registry import get_skill_registry


class RouteMetadataTests(unittest.TestCase):
    def test_build_index_contains_all_workspace_sops(self):
        index = RouteMetadataIndex.build_from_registry(get_skill_registry(refresh=True))
        names = {item.skill_id for item in index.items}
        self.assertIn("fund-compare", names)
        self.assertIn("etf-screen", names)
        self.assertIn("market-move-explain", names)
        self.assertGreaterEqual(len(index.items), 5)

    def test_shortlist_prefers_fund_compare_for_comparison(self):
        index = RouteMetadataIndex.build_from_registry(get_skill_registry())
        shortlist = index.shortlist("华安黄金 ETF 和博时黄金 ETF 哪个适合我", limit=3)
        self.assertEqual(shortlist[0].skill_id, "fund-compare")


if __name__ == "__main__":
    unittest.main()
