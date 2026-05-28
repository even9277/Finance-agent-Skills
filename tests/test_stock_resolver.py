import unittest
from unittest.mock import patch

from backend.services import entity_resolver, stock_resolver


class _FakeFrame:
    def __init__(self, rows):
        self._rows = list(rows)

    def to_dict(self, orient="records"):
        if orient != "records":
            raise ValueError(f"unexpected orient: {orient}")
        return list(self._rows)


class _FakeTushareClient:
    def __init__(self):
        self.stock_rows = [
            {
                "ts_code": "600519.SH",
                "symbol": "600519",
                "name": "贵州茅台",
                "fullname": "贵州茅台酒股份有限公司",
                "cnspell": "gzmt",
                "exchange": "SSE",
                "market": "主板",
                "list_status": "L",
            },
            {
                "ts_code": "002594.SZ",
                "symbol": "002594",
                "name": "比亚迪",
                "fullname": "比亚迪股份有限公司",
                "cnspell": "byd",
                "exchange": "SZSE",
                "market": "主板",
                "list_status": "L",
            },
            {
                "ts_code": "300750.SZ",
                "symbol": "300750",
                "name": "宁德时代",
                "fullname": "宁德时代新能源科技股份有限公司",
                "cnspell": "ndsd",
                "exchange": "SZSE",
                "market": "创业板",
                "list_status": "L",
            },
            {
                "ts_code": "601012.SH",
                "symbol": "601012",
                "name": "隆基绿能",
                "fullname": "隆基绿能科技股份有限公司",
                "cnspell": "ljln",
                "exchange": "SSE",
                "market": "主板",
                "list_status": "L",
            },
            {
                "ts_code": "600848.SH",
                "symbol": "600848",
                "name": "上海临港",
                "fullname": "上海临港控股股份有限公司",
                "cnspell": "shlg",
                "exchange": "SSE",
                "market": "主板",
                "list_status": "L",
            },
        ]
        self.namechange_rows = {
            "600848.SH": [
                {"ts_code": "600848.SH", "name": "上海临港", "start_date": "20151118", "end_date": None, "change_reason": "改名"},
                {"ts_code": "600848.SH", "name": "自仪股份", "start_date": "19940324", "end_date": "20151117", "change_reason": "曾用名"},
            ]
        }

    async def stock_basic(self, **kwargs):
        ts_code = stock_resolver.canonicalize_symbol(kwargs.get("ts_code"))
        list_status = str(kwargs.get("list_status") or "")
        rows = list(self.stock_rows)
        if ts_code:
            rows = [row for row in rows if row["ts_code"] == ts_code]
        elif list_status:
            rows = [row for row in rows if row["list_status"] == list_status]
        return _FakeFrame(rows)

    async def namechange(self, **kwargs):
        ts_code = stock_resolver.canonicalize_symbol(kwargs.get("ts_code"))
        return _FakeFrame(self.namechange_rows.get(ts_code, []))

    async def fund_basic(self, **kwargs):  # pragma: no cover - defensive only
        return _FakeFrame([])


class StockResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        entity_resolver._STOCK_CATALOG_CACHE = None
        entity_resolver._STOCK_CATALOG_CACHED_AT = 0.0
        entity_resolver._STOCK_NAME_ALIAS_MAP.clear()

    async def test_resolve_stock_by_name_with_noise(self):
        fake_client = _FakeTushareClient()
        with patch.object(entity_resolver, "get_tushare_client", return_value=fake_client):
            company_name, stock_code = await stock_resolver.resolve_stock("帮我看看比亚迪最近走势")

        self.assertEqual(company_name, "比亚迪")
        self.assertEqual(stock_code, "002594.SZ")

    async def test_resolve_stock_by_explicit_code(self):
        fake_client = _FakeTushareClient()
        with patch.object(entity_resolver, "get_tushare_client", return_value=fake_client):
            company_name, stock_code = await stock_resolver.resolve_stock("600519")

        self.assertEqual(company_name, "贵州茅台")
        self.assertEqual(stock_code, "600519.SH")

    async def test_resolve_stock_uses_session_symbol_for_follow_up(self):
        fake_client = _FakeTushareClient()
        with patch.object(entity_resolver, "get_tushare_client", return_value=fake_client):
            company_name, stock_code = await stock_resolver.resolve_stock(
                "它的基本面如何",
                session_symbols=["300750.SZ"],
            )

        self.assertEqual(company_name, "宁德时代")
        self.assertEqual(stock_code, "300750.SZ")

    async def test_resolve_stock_rejects_non_stock_fund_query(self):
        fake_client = _FakeTushareClient()
        with patch.object(entity_resolver, "get_tushare_client", return_value=fake_client):
            company_name, stock_code = await stock_resolver.resolve_stock("华安黄金ETF最近走势怎么样")

        self.assertIsNone(company_name)
        self.assertIsNone(stock_code)

    async def test_resolve_stock_warms_alias_cache_from_namechange(self):
        fake_client = _FakeTushareClient()
        with patch.object(entity_resolver, "get_tushare_client", return_value=fake_client):
            first_name, first_code = await stock_resolver.resolve_stock("600848.SH")
            second_name, second_code = await stock_resolver.resolve_stock("自仪股份最近怎么样")

        self.assertEqual(first_name, "上海临港")
        self.assertEqual(first_code, "600848.SH")
        self.assertEqual(second_name, "上海临港")
        self.assertEqual(second_code, "600848.SH")


if __name__ == "__main__":
    unittest.main()
