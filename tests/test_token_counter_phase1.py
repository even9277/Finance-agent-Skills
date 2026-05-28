import unittest
import sys
from pathlib import Path
from unittest.mock import patch

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from backend.db.models import Session
from backend.services import token_counter
from backend.services.stm_context_service import build_context_window_payload


class _Encoding:
    def encode(self, text: str):
        return list(text)


class _TikTokenStub:
    def encoding_for_model(self, model: str):
        if model == "gpt-4o-mini":
            return _Encoding()
        raise KeyError(model)

    def get_encoding(self, name: str):
        if name != "o200k_base":
            raise KeyError(name)
        return _Encoding()


class TokenCounterPhase1Tests(unittest.TestCase):
    def test_current_model_name_falls_back_to_router_model(self):
        with patch.object(token_counter.settings, "openai_compatible_model", ""):
            with patch.object(token_counter.settings, "chat_router_model", "kimi-k2.5"):
                with patch.object(token_counter.settings, "chat_resolver_model", ""):
                    with patch.object(token_counter.settings, "stm_compaction_model", ""):
                        self.assertEqual(token_counter.current_model_name(), "kimi-k2.5")

    def test_count_text_tokens_returns_exact_for_supported_tiktoken_model(self):
        with patch.object(token_counter, "tiktoken", _TikTokenStub()):
            tokens, mode = token_counter.count_text_tokens("abcd", model_name="gpt-4o-mini")

        self.assertEqual(tokens, 4)
        self.assertEqual(mode, token_counter.COUNTING_MODE_EXACT)

    def test_count_text_tokens_marks_unknown_model_as_estimated_fallback(self):
        with patch.object(token_counter, "tiktoken", _TikTokenStub()):
            tokens, mode = token_counter.count_text_tokens("abcd", model_name="custom-unknown-model")

        self.assertEqual(tokens, 4)
        self.assertEqual(mode, token_counter.COUNTING_MODE_ESTIMATED_FALLBACK)

    def test_count_text_tokens_keeps_known_approximate_models_as_estimated(self):
        with patch.object(token_counter, "tiktoken", _TikTokenStub()):
            tokens, mode = token_counter.count_text_tokens("你好世界", model_name="kimi-k2.5")

        self.assertGreater(tokens, 0)
        self.assertEqual(mode, token_counter.COUNTING_MODE_ESTIMATED)

    def test_merge_counting_modes_prefers_lowest_confidence_mode(self):
        self.assertEqual(
            token_counter.merge_counting_modes(["exact", "estimated"]),
            token_counter.COUNTING_MODE_ESTIMATED,
        )
        self.assertEqual(
            token_counter.merge_counting_modes(["exact", "estimated_fallback"]),
            token_counter.COUNTING_MODE_ESTIMATED_FALLBACK,
        )
        self.assertEqual(
            token_counter.merge_counting_modes(["exact", "exact"]),
            token_counter.COUNTING_MODE_EXACT,
        )

    def test_build_context_window_payload_uses_phase1_budget_baseline(self):
        session = Session(
            id="session-test",
            user_id="user-test",
            mode="chat",
            title="test",
            context_token_count=30000,
            compression_status="idle",
        )

        with patch("backend.services.stm_context_service.settings.chat_context_window_tokens", 100000):
            with patch("backend.services.stm_context_service.settings.stm_summary_reserve_tokens_floor", 20000):
                with patch("backend.services.stm_context_service.settings.stm_summary_soft_threshold_tokens", 4000):
                    with patch("backend.services.stm_context_service.settings.stm_summary_overhead_tokens", 1000):
                        payload = build_context_window_payload(
                            session,
                            counting_mode=token_counter.COUNTING_MODE_ESTIMATED_FALLBACK,
                        )

        self.assertEqual(payload.model_window_tokens, 100000)
        self.assertEqual(payload.working_budget_tokens, 75000)
        self.assertEqual(payload.reserved_output_tokens, 20000)
        self.assertEqual(payload.budget_tokens, 45000)
        self.assertEqual(payload.usage_percent, 40)
        self.assertEqual(payload.counting_mode, token_counter.COUNTING_MODE_ESTIMATED_FALLBACK)
        self.assertEqual(payload.strategy, "dynamic_budget")
        self.assertEqual(payload.budget_status, "healthy")


if __name__ == "__main__":
    unittest.main()
