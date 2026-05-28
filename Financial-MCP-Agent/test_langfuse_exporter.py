import os
import unittest
from unittest.mock import patch

from src.tools.trace_exporters.langfuse_exporter import LangfuseTraceExporter


class _DummyClient:
    def create_trace_id(self, *, seed=None):
        return "a" * 32


class _DummyObservation:
    def __init__(self, observation_id: str):
        self.id = observation_id


class LangfuseExporterTestCase(unittest.TestCase):
    def _build_exporter(self) -> LangfuseTraceExporter:
        exporter = object.__new__(LangfuseTraceExporter)
        exporter.host = "https://us.cloud.langfuse.com"
        exporter.base_url = "https://us.cloud.langfuse.com"
        exporter.environment = "dev"
        exporter.release = "local-dev"
        exporter.enabled = True
        exporter.disabled_reason = ""
        exporter._client = _DummyClient()
        exporter._langfuse_trace_ids = {}
        exporter._trace_state = {}
        exporter._span_cache = {}
        return exporter

    def test_flatten_metadata_prefers_scalar_fields(self):
        exporter = self._build_exporter()
        record = {
            "record_type": "span",
            "workflow_name": "chat-skill-turn",
            "trace_schema_version": "2026-04-07.1",
            "policy_version": "trace-v1",
            "group_id": "sess_001",
            "session_id": "sess_001",
            "user_id": "user_001",
            "turn_index": 1,
            "stage": "executor",
            "status": "ok",
            "name": "tool_call",
            "data": {
                "tool_name": "get_sector_snapshot",
                "skill_name": "sector-hotspot-brief",
                "analysis_mode": "sector_hotspot_brief",
                "payload": {"nested": True},
            },
            "metrics": {
                "route_confidence": 0.9,
                "p95_latency": 123.4,
                "raw": {"nested": True},
            },
            "refs": {
                "prompt_ref": "/tmp/prompt.json",
                "payload_refs": ["/tmp/tool.json"],
            },
        }

        metadata = exporter._flatten_metadata(record)

        self.assertEqual(metadata["tool_name"], "get_sector_snapshot")
        self.assertEqual(metadata["skill_name"], "sector-hotspot-brief")
        self.assertEqual(metadata["route_confidence"], 0.9)
        self.assertEqual(metadata["prompt_ref"], "/tmp/prompt.json")
        self.assertEqual(metadata["span_name"], "tool:get_sector_snapshot")
        self.assertNotIn("payload", metadata)
        self.assertNotIn("raw", metadata)
        self.assertNotIn("payload_refs", metadata)

    def test_event_parent_prefers_current_span(self):
        exporter = self._build_exporter()
        exporter._span_cache["sp_current"] = _DummyObservation("obs_current")
        exporter._span_cache["sp_parent"] = _DummyObservation("obs_parent")

        event_record = {
            "record_type": "event",
            "span_id": "sp_current",
            "parent_span_id": "sp_parent",
        }
        span_record = {
            "record_type": "span",
            "span_id": "sp_current",
            "parent_span_id": "sp_parent",
        }

        self.assertEqual(exporter._resolve_parent_observation_id(event_record), "obs_current")
        self.assertEqual(exporter._resolve_parent_observation_id(span_record), "obs_parent")

    def test_trace_output_masks_prompt_reply_by_default(self):
        exporter = self._build_exporter()
        record = {
            "status": "ok",
            "data": {
                "prompt": "full prompt",
                "reply_text": "full reply",
                "prompt_ref": "/tmp/prompt.json",
                "reply_ref": "/tmp/reply.json",
                "skill_name": "stock-first-pass",
            },
        }

        with patch.dict(os.environ, {"LANGFUSE_UPLOAD_PROMPT_REPLY": "false"}, clear=False):
            payload = exporter._trace_output(record)

        self.assertNotIn("prompt", payload)
        self.assertNotIn("reply_text", payload)
        self.assertEqual(payload["prompt_ref"], "/tmp/prompt.json")
        self.assertEqual(payload["reply_ref"], "/tmp/reply.json")
        self.assertEqual(payload["skill_name"], "stock-first-pass")

    def test_trace_output_can_upload_prompt_reply_when_explicitly_enabled(self):
        exporter = self._build_exporter()
        record = {
            "status": "ok",
            "data": {
                "prompt": "full prompt",
                "reply_text": "full reply",
                "prompt_ref": "/tmp/prompt.json",
            },
        }

        with patch.dict(os.environ, {"LANGFUSE_UPLOAD_PROMPT_REPLY": "true"}, clear=False):
            payload = exporter._trace_output(record)

        self.assertEqual(payload["prompt"], "full prompt")
        self.assertEqual(payload["reply_text"], "full reply")


if __name__ == "__main__":
    unittest.main()
