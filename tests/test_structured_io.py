import asyncio
import sys
import unittest
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.structured_io import extract_json_object, structured_call


class Payload(BaseModel):
    route: str
    confidence: float = 0.0


class StructuredIOTests(unittest.TestCase):
    def test_extract_json_object_ignores_fence_and_noise(self):
        data = extract_json_object('noise\n```json\n{"route":"fallback"}\n```')
        self.assertEqual(data["route"], "fallback")

    def test_structured_call_repairs_syntax(self):
        calls = []

        async def invoke(prompt: str):
            calls.append(prompt)
            if len(calls) == 1:
                return "not json"
            return '{"route":"tushare","confidence":0.9}'

        result = asyncio.run(structured_call(invoke=invoke, prompt="p", schema=Payload))
        self.assertEqual(result.payload.route, "tushare")
        self.assertTrue(result.syntax_repaired)
        self.assertIn("syntax_repair", result.stages_run)

    def test_structured_call_repairs_semantics(self):
        calls = []

        async def invoke(prompt: str):
            calls.append(prompt)
            if len(calls) == 1:
                return '{"route":"fallback","confidence":1.2}'
            return '{"route":"fallback","confidence":0.2}'

        def validator(payload: Payload):
            return ["confidence_out_of_range"] if payload.confidence > 1 else []

        result = asyncio.run(
            structured_call(
                invoke=invoke,
                prompt="p",
                schema=Payload,
                semantic_validator=validator,
            )
        )
        self.assertTrue(result.semantic_repaired)
        self.assertEqual(result.payload.confidence, 0.2)


if __name__ == "__main__":
    unittest.main()
