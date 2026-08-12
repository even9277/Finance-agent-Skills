"""报告工作流事件解析回归测试。"""

import unittest

from backend.services.agent_service import _extract_final_state_from_event


class AgentServiceEventTests(unittest.TestCase):
    """验证 LangGraph 根图结束事件不会触发重复执行。"""

    def test_extracts_final_state_from_capitalized_langgraph_event(self):
        """当前 LangGraph 使用 ``LangGraph`` 作为根图事件名。"""
        expected = {"data": {"final_report": "done"}}
        event = {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": expected},
            "metadata": {},
        }

        self.assertEqual(_extract_final_state_from_event(event), expected)

    def test_ignores_node_level_chain_end_event(self):
        """普通节点的输出不能覆盖根图最终状态。"""
        event = {
            "event": "on_chain_end",
            "name": "summary_agent",
            "data": {"output": {"data": {"final_report": "partial"}}},
        }

        self.assertIsNone(_extract_final_state_from_event(event))


if __name__ == "__main__":
    unittest.main()
