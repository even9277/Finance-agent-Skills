import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools import tushare_client


class TushareClientTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.get("TUSHARE_TOKEN")
        tushare_client.configure_tushare_client_factory(None)

    def tearDown(self):
        tushare_client.configure_tushare_client_factory(None)
        if self.original_env is None:
            os.environ.pop("TUSHARE_TOKEN", None)
        else:
            os.environ["TUSHARE_TOKEN"] = self.original_env

    def test_uses_environment_token_when_no_factory_is_configured(self):
        os.environ["TUSHARE_TOKEN"] = "env-token-for-test"
        client = tushare_client.get_tushare_client()
        self.assertEqual(client.token, "env-token-for-test")


if __name__ == "__main__":
    unittest.main()
