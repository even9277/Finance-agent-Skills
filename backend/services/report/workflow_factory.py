from langgraph.graph import END, StateGraph  # noqa: E402

from backend.integrations.agent_runtime.env import agent_root
from backend.integrations.agent_runtime.report_runtime import (
    AgentState,
    fundamental_agent,
    get_memory_nodes,
    maybe_summarize_state,
    news_agent,
    prepare_summary_context,
    setup_logger,
    summary_agent,
    technical_agent,
    value_agent,
)

logger = setup_logger("agent_service", log_dir=str(agent_root() / "logs"))

_COMPILED_WORKFLOW = None


def _get_workflow():
    """
    编译 LangGraph 工作流（全局复用）。
    支持 4 种拓扑，与 main.py 保持一致：
      模式 1（原始）    : 4 analyst → summarizer → END
      模式 2（仅 STM）  : 4 analyst → prepare_summary_context → summarizer → maybe_summarize_state → END
      模式 3（仅 LTM）  : 4 analyst → memory_read_node → summarizer → memory_write_node → END
      模式 4（STM+LTM） : 4 analyst → memory_read_node → prepare_summary_context → summarizer
                              → maybe_summarize_state → memory_write_node → END
    """
    global _COMPILED_WORKFLOW
    if _COMPILED_WORKFLOW is None:
        from backend.config import settings
        enable_stm = settings.enable_stm
        enable_memory = settings.enable_memory
        memory_read_node = memory_write_node = None
        if enable_memory:
            memory_read_node, memory_write_node = get_memory_nodes()

        # 按需导入 LTM 节点（只有启用时才 import，避免未配置时的导入错误）
        wf = StateGraph(AgentState)
        wf.add_node("start_node", lambda state: state)
        wf.add_node("fundamental_analyst", fundamental_agent)
        wf.add_node("technical_analyst", technical_agent)
        wf.add_node("value_analyst", value_agent)
        wf.add_node("news_analyst", news_agent)
        wf.add_node("summarizer", summary_agent)
        wf.set_entry_point("start_node")

        wf.add_edge("start_node", "fundamental_analyst")
        wf.add_edge("start_node", "technical_analyst")
        wf.add_edge("start_node", "value_analyst")
        wf.add_edge("start_node", "news_analyst")

        if enable_stm and enable_memory:
            # ── 模式 4：STM + LTM ──
            wf.add_node("memory_read_node", memory_read_node)
            wf.add_node("prepare_summary_context", prepare_summary_context)
            wf.add_node("maybe_summarize_state", maybe_summarize_state)
            wf.add_node("memory_write_node", memory_write_node)

            wf.add_edge("fundamental_analyst", "memory_read_node")
            wf.add_edge("technical_analyst", "memory_read_node")
            wf.add_edge("value_analyst", "memory_read_node")
            wf.add_edge("news_analyst", "memory_read_node")
            wf.add_edge("memory_read_node", "prepare_summary_context")
            wf.add_edge("prepare_summary_context", "summarizer")
            wf.add_edge("summarizer", "maybe_summarize_state")
            wf.add_edge("maybe_summarize_state", "memory_write_node")
            wf.add_edge("memory_write_node", END)
            logger.info("Financial analysis workflow compiled [STM + LTM].")
            print("[Workflow] 已启用 STM + LTM 模式")

        elif enable_stm:
            # ── 模式 2：仅 STM ──
            wf.add_node("prepare_summary_context", prepare_summary_context)
            wf.add_node("maybe_summarize_state", maybe_summarize_state)
            wf.add_edge("fundamental_analyst", "prepare_summary_context")
            wf.add_edge("technical_analyst", "prepare_summary_context")
            wf.add_edge("value_analyst", "prepare_summary_context")
            wf.add_edge("news_analyst", "prepare_summary_context")
            wf.add_edge("prepare_summary_context", "summarizer")
            wf.add_edge("summarizer", "maybe_summarize_state")
            wf.add_edge("maybe_summarize_state", END)
            logger.info("Financial analysis workflow compiled [STM only].")
            print("[Workflow] 已启用仅 STM 模式")

        elif enable_memory:
            # ── 模式 3：仅 LTM ──
            wf.add_node("memory_read_node", memory_read_node)
            wf.add_node("memory_write_node", memory_write_node)
            wf.add_edge("fundamental_analyst", "memory_read_node")
            wf.add_edge("technical_analyst", "memory_read_node")
            wf.add_edge("value_analyst", "memory_read_node")
            wf.add_edge("news_analyst", "memory_read_node")
            wf.add_edge("memory_read_node", "summarizer")
            wf.add_edge("summarizer", "memory_write_node")
            wf.add_edge("memory_write_node", END)
            logger.info("Financial analysis workflow compiled [LTM only].")
            print("[Workflow] 已启用仅 LTM 模式")

        else:
            # ── 模式 1：原始模式 ──
            wf.add_edge("fundamental_analyst", "summarizer")
            wf.add_edge("technical_analyst", "summarizer")
            wf.add_edge("value_analyst", "summarizer")
            wf.add_edge("news_analyst", "summarizer")
            wf.add_edge("summarizer", END)
            logger.info("Financial analysis workflow compiled [original mode].")

        _COMPILED_WORKFLOW = wf.compile()
    return _COMPILED_WORKFLOW
