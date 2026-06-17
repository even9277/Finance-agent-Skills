__all__ = [
    "_build_initial_state",
    "_get_workflow",
    "extract_stock_info",
    "run_report_task",
]


def __getattr__(name: str):
    """避免导入轻量 report 子模块时提前加载 Agent runtime。"""
    if name in {"_build_initial_state", "extract_stock_info"}:
        from backend.services.report.state_builder import _build_initial_state, extract_stock_info

        return {
            "_build_initial_state": _build_initial_state,
            "extract_stock_info": extract_stock_info,
        }[name]
    if name == "_get_workflow":
        from backend.services.report.workflow_factory import _get_workflow

        return _get_workflow
    if name == "run_report_task":
        from backend.services.report.workflow_runner import run_report_task

        return run_report_task
    raise AttributeError(name)
