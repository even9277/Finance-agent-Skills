import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Financial-MCP-Agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from src.agents.tool_discovery.capability_index import build_capability_index  # noqa: E402
from src.agents.tool_discovery.executable_registry import build_default_registry  # noqa: E402


class CapabilityIndexTests(unittest.TestCase):
    def test_capabilities_have_stable_unique_ids(self):
        capabilities = build_capability_index()
        ids = [item.capability_id for item in capabilities]
        self.assertGreaterEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))

    def test_each_capability_primary_evidence_is_tool_covered(self):
        registry = build_default_registry()
        covered = {spec.evidence_type for spec in registry.specs()}
        for capability in build_capability_index():
            self.assertTrue(capability.primary_evidence_types, capability.capability_id)
            self.assertTrue(
                set(capability.primary_evidence_types) & covered,
                f"{capability.capability_id} has no executable primary evidence coverage",
            )

    def test_each_registry_spec_has_capability_coverage(self):
        capabilities = build_capability_index()
        capability_evidence = set()
        for capability in capabilities:
            capability_evidence.update(capability.primary_evidence_types)
            capability_evidence.update(capability.secondary_evidence_types)

        registry = build_default_registry()
        uncovered = [
            spec.name
            for spec in registry.specs()
            if spec.evidence_type not in capability_evidence
        ]
        self.assertEqual(uncovered, [])


if __name__ == "__main__":
    unittest.main()
