import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents.response_normalizer import extract_final_text

try:
    from langchain.messages import AIMessage, ToolMessage
except Exception:
    from langchain_core.messages import AIMessage, ToolMessage


class ResponseNormalizerTests(unittest.TestCase):
    def test_extracts_output_field(self):
        self.assertEqual(extract_final_text({"output": "final text"}), "final text")

    def test_extracts_string_content_from_ai_message(self):
        response = {"messages": [AIMessage(content="final text")]}
        self.assertEqual(extract_final_text(response), "final text")

    def test_extracts_list_content_from_ai_message(self):
        response = {"messages": [AIMessage(content=[{"type": "text", "text": "final text"}])]}
        self.assertEqual(extract_final_text(response), "final text")

    def test_prefers_ai_message_over_tool_message(self):
        response = {
            "messages": [
                ToolMessage(content="tool output", tool_call_id="call-1"),
                AIMessage(content="final text"),
            ]
        }
        self.assertEqual(extract_final_text(response), "final text")


if __name__ == "__main__":
    unittest.main()
