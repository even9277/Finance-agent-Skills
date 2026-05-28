import unittest
from unittest.mock import AsyncMock, patch

from backend.services import entity_resolver


class EntityResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        entity_resolver._STOCK_CATALOG_CACHE = None
        entity_resolver._STOCK_CATALOG_CACHED_AT = 0.0
        entity_resolver._FUND_CATALOG_CACHE = None
        entity_resolver._FUND_CATALOG_CACHED_AT = 0.0
        entity_resolver._STOCK_NAME_ALIAS_MAP.clear()

    async def test_resolve_entity_returns_index_from_alias(self):
        result = await entity_resolver.resolve_entity("沪深300今天怎么样")

        self.assertTrue(result.ok)
        self.assertEqual(result.asset_type, "index")
        self.assertEqual(result.symbol, "000300.SH")

    async def test_resolve_entity_returns_sector_from_tushare_sector_resolution(self):
        mocked = {
            "normalized_sector_name": "电力设备",
            "index_code": "801730.SI",
            "match_confidence": 0.84,
            "candidate_details": [{"sector_name": "电力设备", "index_code": "801730.SI", "score": 0.84}],
        }
        with patch.object(entity_resolver, "resolve_sector_request", new=AsyncMock(return_value=mocked)):
            result = await entity_resolver.resolve_entity("新能源板块最近行情怎么样")

        self.assertTrue(result.ok)
        self.assertEqual(result.asset_type, "sector")
        self.assertEqual(result.display_name, "电力设备")
        self.assertEqual(result.symbol, "801730.SI")

    async def test_resolve_entity_returns_fund_from_fund_candidate_search(self):
        mocked_rows = [
            {
                "ts_code": "518880.SH",
                "name": "华安黄金ETF",
                "_score": 120,
            }
        ]
        with patch.object(
            entity_resolver,
            "_search_fund_candidates",
            new=AsyncMock(return_value=(mocked_rows, "华安黄金ETF", None, None, "fund_basic")),
        ):
            result = await entity_resolver.resolve_entity("华安黄金ETF最近走势怎么样")

        self.assertTrue(result.ok)
        self.assertEqual(result.asset_type, "fund")
        self.assertEqual(result.display_name, "华安黄金ETF")
        self.assertEqual(result.symbol, "518880.SH")


if __name__ == "__main__":
    unittest.main()
