import sys
import unittest
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.tool_discovery.executable_registry import (  # noqa: E402
    OUTPUT_ENVELOPE_FIELDS,
    build_default_registry,
    default_tool_specs,
)
from src.tools.chat_tushare_tools import get_tushare_toolkit  # noqa: E402


class ExecutableRegistryTests(unittest.TestCase):
    def test_default_specs_cover_exact_toolkit(self):
        toolkit_names = {
            getattr(tool, "name", getattr(tool, "__name__", ""))
            for tool in get_tushare_toolkit()
        }
        spec_names = set(default_tool_specs())
        self.assertEqual(spec_names, toolkit_names)
        self.assertEqual(len(spec_names), 15)

    def test_build_default_registry_has_complete_required_metadata(self):
        registry = build_default_registry()
        self.assertEqual(len(registry.names()), 15)
        for spec in registry.specs():
            self.assertTrue(spec.name)
            self.assertTrue(spec.description)
            self.assertTrue(spec.supported_entity_types)
            self.assertTrue(spec.input_fields)
            self.assertTrue(spec.evidence_type)
            self.assertTrue(spec.source_api)
            self.assertTrue(spec.api_family)
            self.assertTrue(spec.rate_limit_group)
            self.assertTrue(spec.read_only)
            self.assertTrue(spec.planner_visible)
            self.assertGreater(spec.timeout_ms, 0)
            self.assertIn("max", spec.retry_policy)
            for field in OUTPUT_ENVELOPE_FIELDS:
                self.assertIn(field, spec.output_envelope_fields)

    def test_input_and_output_schemas_are_planner_safe(self):
        registry = build_default_registry()
        search_spec = registry.spec("search_web_news")
        input_schema = search_spec.input_schema()
        self.assertFalse(input_schema["additionalProperties"])
        self.assertIn("query", input_schema["required"])

        output_schema = search_spec.output_schema()
        self.assertEqual(output_schema["type"], "object")
        self.assertIn("ok", output_schema["required"])
        self.assertIn("fetch_ts", output_schema["properties"])
        self.assertIn("api_family", output_schema["properties"])

    def test_snapshot_is_read_only(self):
        registry = build_default_registry()
        snapshot = registry.snapshot()
        with self.assertRaises(TypeError):
            snapshot["new_tool"] = snapshot["search_web_news"]

    def test_points_level_disabled_tool_is_hidden_from_planner(self):
        old = os.environ.get("TUSHARE_DISABLED_TOOLS")
        os.environ["TUSHARE_DISABLED_TOOLS"] = "fund_share"
        try:
            registry = build_default_registry()
            self.assertFalse(registry.spec("get_fund_share").planner_visible)
            self.assertNotIn("get_fund_share", registry.names(planner_visible_only=True))
        finally:
            if old is None:
                os.environ.pop("TUSHARE_DISABLED_TOOLS", None)
            else:
                os.environ["TUSHARE_DISABLED_TOOLS"] = old


if __name__ == "__main__":
    unittest.main()
