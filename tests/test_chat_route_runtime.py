import unittest

from backend.services import chat_route_runtime


class ChatRouteRuntimeTests(unittest.TestCase):
    def setUp(self):
        chat_route_runtime._ROUTE_RUNTIME_BY_SESSION.clear()

    def test_record_route_runtime_uses_resolved_entity_hint_for_fund(self):
        state = chat_route_runtime.record_route_runtime_state(
            session_id="sess-1",
            user_message="华安黄金ETF最近走势怎么样",
            route_trace={
                "selected_skill": "financial-sop",
                "confidence": 0.9,
                "arguments": {
                    "effective_query": "华安黄金ETF最近走势怎么样",
                    "resolved_entity_hint": {
                        "display_name": "华安黄金ETF",
                        "asset_type": "fund",
                        "symbol": "518880.SH",
                        "resolver_source": "tushare.fund_basic",
                    },
                    "entities": [
                        {
                            "display_name": "华安黄金ETF",
                            "asset_type": "fund",
                            "symbol": "518880.SH",
                        }
                    ],
                },
                "executor": {},
            },
            reply_text="已完成基金解析。",
        )

        self.assertEqual(state.active_entity_type, "fund")
        self.assertEqual(state.active_entity_id, "518880.SH")
        self.assertEqual(state.active_entity_display_name, "华安黄金ETF")
        self.assertEqual(state.last_active_entity, "华安黄金ETF")


if __name__ == "__main__":
    unittest.main()
