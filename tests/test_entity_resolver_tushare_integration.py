import os
import unittest

from backend.services import entity_resolver


@unittest.skipUnless(os.getenv("TUSHARE_TOKEN"), "requires TUSHARE_TOKEN")
class EntityResolverTuShareIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        entity_resolver._STOCK_CATALOG_CACHE = None
        entity_resolver._STOCK_CATALOG_CACHED_AT = 0.0
        entity_resolver._FUND_CATALOG_CACHE = None
        entity_resolver._FUND_CATALOG_CACHED_AT = 0.0
        entity_resolver._STOCK_NAME_ALIAS_MAP.clear()

    async def test_resolve_stock_with_real_tushare_catalog(self):
        result = await entity_resolver.resolve_entity("贵州茅台今天怎么样")

        self.assertTrue(result.ok)
        self.assertEqual(result.asset_type, "stock")
        self.assertEqual(result.symbol, "600519.SH")

    async def test_resolve_fund_with_real_tushare_catalog(self):
        result = await entity_resolver.resolve_entity("华安黄金ETF最近走势怎么样")

        self.assertTrue(result.ok)
        self.assertEqual(result.asset_type, "fund")
        self.assertTrue(result.symbol.endswith((".SH", ".SZ")))
        self.assertIn("ETF", result.display_name.upper())

    async def test_resolve_sector_with_real_tushare_catalog(self):
        result = await entity_resolver.resolve_entity("新能源板块最近行情怎么样")

        self.assertTrue(result.ok)
        self.assertEqual(result.asset_type, "sector")
        self.assertTrue(result.symbol.endswith(".SI"))
        self.assertTrue(result.display_name)


if __name__ == "__main__":
    unittest.main()
