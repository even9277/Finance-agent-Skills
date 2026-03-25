import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents import agent_factory


class AgentFactoryTests(unittest.TestCase):
    def test_prefers_v1_create_agent_when_available(self):
        sentinel = object()
        with patch.object(agent_factory, "_create_agent", return_value=sentinel) as create_agent_mock:
            with patch.object(agent_factory, "_legacy_create_react_agent") as legacy_mock:
                result = agent_factory.build_analysis_agent(model="m", tools=["t"], system_prompt="p")
        self.assertIs(result, sentinel)
        create_agent_mock.assert_called_once_with(model="m", tools=["t"], system_prompt="p")
        legacy_mock.assert_not_called()

    def test_falls_back_to_legacy_builder(self):
        sentinel = object()
        with patch.object(agent_factory, "_create_agent", None):
            with patch.object(agent_factory, "_legacy_create_react_agent", return_value=sentinel) as legacy_mock:
                result = agent_factory.build_analysis_agent(model="m", tools=["t"])
        self.assertIs(result, sentinel)
        legacy_mock.assert_called_once_with("m", ["t"])

    def test_raises_when_no_builder_is_available(self):
        with patch.object(agent_factory, "_create_agent", None):
            with patch.object(agent_factory, "_legacy_create_react_agent", None):
                with self.assertRaises(RuntimeError):
                    agent_factory.build_analysis_agent(model="m", tools=["t"])


if __name__ == "__main__":
    unittest.main()
