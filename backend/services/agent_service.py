"""
Agent 服务层门面。

保留旧导入路径，实际报告工作流实现已迁入 backend.services.report.*。
"""

from backend.integrations.agent_runtime.report_runtime import (
    finalize_execution_logger,
    get_execution_logger,
    initialize_execution_logger,
)

from backend.services.report.state_builder import _build_initial_state, extract_stock_info
from backend.services.report.workflow_factory import _get_workflow
from backend.services.report.workflow_runner import run_report_task

__all__ = [
    "_build_initial_state",
    "_get_workflow",
    "extract_stock_info",
    "finalize_execution_logger",
    "get_execution_logger",
    "initialize_execution_logger",
    "run_report_task",
]
