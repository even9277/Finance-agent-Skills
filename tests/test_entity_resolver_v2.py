import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.entity_resolver_v2 import resolve_authoritative_entity


class EntityResolverV2Tests(unittest.TestCase):
    def test_resolved_from_catalog_candidate(self):
        async def run():
            with patch(
                "backend.services.entity_resolver.gather_candidates",
                new=AsyncMock(
                    return_value=[
                        {
                            "entity_type": "stock",
                            "canonical_id": "600519.SH",
                            "display_name": "贵州茅台",
                            "score": 0.95,
                            "source": "catalog",
                        }
                    ]
                ),
            ):
                result = await resolve_authoritative_entity("贵州茅台今天怎么样")
            self.assertEqual(result.resolution_status, "resolved")
            self.assertEqual(result.primary_entity.canonical_id, "600519.SH")

        asyncio.run(run())

    def test_competing_candidates_clarify(self):
        async def run():
            with patch(
                "backend.services.entity_resolver.gather_candidates",
                new=AsyncMock(
                    return_value=[
                        {"entity_type": "stock", "canonical_id": "601318.SH", "display_name": "中国平安", "score": 0.8},
                        {"entity_type": "stock", "canonical_id": "000001.SZ", "display_name": "平安银行", "score": 0.74},
                    ]
                ),
            ):
                result = await resolve_authoritative_entity("平安现在能买吗")
            self.assertTrue(result.need_clarification)
            self.assertIn(result.resolution_status, {"ambiguous", "competing_candidates"})

        asyncio.run(run())

    def test_gated_inheritance(self):
        async def run():
            with patch("backend.services.entity_resolver.gather_candidates", new=AsyncMock(return_value=[])):
                result = await resolve_authoritative_entity(
                    "那它估值呢",
                    previous_active_entity={"entity_type": "stock", "canonical_id": "600519.SH", "display_name": "贵州茅台"},
                )
            self.assertTrue(result.should_inherit)
            self.assertEqual(result.primary_entity.canonical_id, "600519.SH")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
