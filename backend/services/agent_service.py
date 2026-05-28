"""
Agent 服务层
封装对 Financial-MCP-Agent 工作流的调用，供 FastAPI 后台任务使用。
原有 CLI 入口（Financial-MCP-Agent/src/main.py）不作任何改动，
本模块通过 sys.path 注入后直接 import 复用 agent 代码。

注意事项：
- ExecutionLogger 内部使用全局单例，并发报告生成时每个任务独立创建实例并单独 finalize，
  避免状态污染。
- 工作流编译一次后复用（_COMPILED_WORKFLOW），线程安全（StateGraph.compile() 返回不可变图）。
"""

import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# ─────────────────────────────────────────────────────────────
# sys.path 注入：让 Financial-MCP-Agent/src.* 可导入
# ─────────────────────────────────────────────────────────────
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "Financial-MCP-Agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

# 加载 agent .env（LLM API Key 等），在导入 agent 模块前执行
from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(_AGENT_ROOT / ".env"), override=False)

# ─────────────────────────────────────────────────────────────
# 导入 Agent 模块（依赖 sys.path 注入）
# ─────────────────────────────────────────────────────────────
from src.agents.fundamental_agent import fundamental_agent  # noqa: E402
from src.agents.news_agent import news_agent  # noqa: E402
from src.agents.summary_agent import summary_agent  # noqa: E402
from src.agents.technical_agent import technical_agent  # noqa: E402
from src.agents.value_agent import value_agent  # noqa: E402
from src.agents.stm_nodes import prepare_summary_context, maybe_summarize_state  # noqa: E402
from src.utils.execution_logger import (  # noqa: E402
    finalize_execution_logger,
    get_execution_logger,
    initialize_execution_logger,
)
from src.utils.logging_config import setup_logger  # noqa: E402
from src.utils.state_definition import AgentState, make_stm_defaults  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402

logger = setup_logger("agent_service", log_dir=str(_AGENT_ROOT / "logs"))

# ─────────────────────────────────────────────────────────────
# 工作流（编译一次，全局复用）
# ─────────────────────────────────────────────────────────────
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

        # 按需导入 LTM 节点（只有启用时才 import，避免未配置时的导入错误）
        if enable_memory:
            from src.agents.memory_nodes import memory_read_node, memory_write_node

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


# ─────────────────────────────────────────────────────────────
# P1 修复：引入 stock_resolver 三层解析（正则 → BaoStock → LLM）
# ─────────────────────────────────────────────────────────────
# 注意：保留旧的 extract_stock_info() 作为向后兼容的同步接口（仅走 L1 正则）
# 新增 resolve_stock 异步接口（完整三层解析）
from backend.services.stock_resolver import resolve_stock  # noqa: E402


def extract_stock_info(query: str) -> tuple[str | None, str | None]:
    """
    【已废弃】仅保留用于向后兼容。
    从自然语言查询中提取公司名称和股票代码（仅正则，不做 BaoStock 反查/LLM 兜底）。
    
    新代码请使用 resolve_stock(query) 异步接口，提供更强大的三层解析。
    """
    company_name = None
    stock_code = None

    patterns_with_both = [
        r'请帮我分析一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]',
        r'分析一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]',
        r'分析\s*([^（(]+?)\s*[（(](\d{5,6})[)）]',
        r'我想了解一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]',
        r'帮我看看\s*([^（(]+?)\s*[（(](\d{5,6})[)）]',
        r'^([^（(]+?)\s*[（(](\d{5,6})[)）]',
    ]
    for pattern in patterns_with_both:
        m = re.search(pattern, query)
        if m:
            company_name, stock_code = m.group(1).strip(), m.group(2)
            break

    if not stock_code:
        m = re.search(r'\b(\d{5,6})\b', query)
        if m:
            stock_code = m.group(1)

    if not company_name:
        for pattern in [
            r'分析一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)',
            r'分析\s*([^0-9（）()\s]+)',
            r'([^0-9（）()\s]+)\s*(?:这只|这个|的)?\s*股票',
            r'了解一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)',
            r'给我分析一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)',
        ]:
            m = re.search(pattern, query)
            if m:
                company_name = m.group(1).strip()
                break

    if company_name:
        stop_words = ['的', '这个', '这只', '一下', '看看', '了解', '分析',
                      '帮我', '我想', '给我', '财务状况', '投资价值', '基本面']
        for w in stop_words:
            company_name = company_name.replace(w, '').strip()
        if len(company_name) < 2:
            company_name = None

    return company_name, stock_code


async def _build_initial_state(user_query: str, user_id: str = "") -> AgentState:
    """
    构造 LangGraph 初始状态，与 main.py 的状态结构保持一致。
    
    P1 修复：改为 async，使用 resolve_stock() 三层解析（正则 → BaoStock → LLM）。
    P2 修复：接受 user_id 参数并写入 memory_user_id，确保 LTM 节点能正确读取用户画像。
    """
    # P1: 使用三层解析替代纯正则
    company_name, stock_code = await resolve_stock(user_query)
    now = datetime.now()

    data: dict[str, Any] = {
        "query": user_query,
        "current_date": now.strftime("%Y-%m-%d"),
        "current_date_cn": now.strftime("%Y年%m月%d日"),
        "current_time": now.strftime("%H:%M:%S"),
        "current_weekday_cn": ["星期一", "星期二", "星期三", "星期四",
                               "星期五", "星期六", "星期日"][now.weekday()],
        "current_time_info": now.strftime("%Y年%m月%d日 %Y-%m-%d") + f" {now.strftime('%H:%M:%S')}",
        "analysis_timestamp": now.isoformat(),
    }
    if company_name:
        data["company_name"] = company_name
    if stock_code:
        data["stock_code"] = stock_code  # canonical format: XXXXXX.SH/SZ

    # 合并 STM + LTM 默认字段
    stm_defaults = make_stm_defaults()
    # P2: 设置 memory_user_id，确保 memory_read_node 能识别用户
    if user_id:
        stm_defaults["memory_user_id"] = user_id
    
    return AgentState(messages=[], data=data, metadata={}, **stm_defaults)


# ─────────────────────────────────────────────────────────────
# 后台任务主函数
# ─────────────────────────────────────────────────────────────
async def run_report_task(
    task_id: str,
    report_id: str,
    command: str,
    user_id: str,
) -> None:
    """
    后台任务：运行完整多 Agent 分析工作流，结果写入数据库。
    由 report router 的 BackgroundTasks 调用，不直接返回给 HTTP 请求。
    """
    from sqlalchemy import select

    from backend.db.database import AsyncSessionFactory
    from backend.db.models import Report

    # 关键：复用 Financial-MCP-Agent 的全局 ExecutionLogger（与各 agent 的落盘日志同一个 execution_id）
    # 这样 final_report.md 会出现在 /root/Finance/logs/<execution_id>/reports/ 下，而不是另起目录。
    from backend.config import settings

    exec_logger = initialize_execution_logger(base_log_dir=str(settings.project_root / "logs"))
    logger.info(
        f"[task:{task_id}] 开始报告生成，execution_id={exec_logger.execution_id} "
        f"log_dir={exec_logger.execution_dir}"
    )

    async def _update_report(**kwargs):
        async with AsyncSessionFactory() as db:
            result = await db.execute(select(Report).where(Report.task_id == task_id))
            rpt = result.scalar_one_or_none()
            if rpt:
                for k, v in kwargs.items():
                    setattr(rpt, k, v)
                await db.commit()

    try:
        await _update_report(status="running", progress=10)

        # P1+P2: _build_initial_state 改为 async，传入 user_id
        initial_state = await _build_initial_state(command, user_id=user_id)
        company_name = initial_state["data"].get("company_name")
        stock_code = initial_state["data"].get("stock_code")

        # P1: 解析结果日志（便于调试）
        if not stock_code:
            logger.warning(
                f"[task:{task_id}] ⚠️ 未能解析股票代码！原始指令: '{command}', "
                f"识别到名称: '{company_name}'. 各 Agent 将使用原始 query 调用 MCP 工具。"
            )
            print(
                f"[Report] ⚠️ 股票代码未解析到，各 Agent 将尝试用名称 '{company_name}' "
                f"直接调用 MCP 工具（可能需要 Agent 自行查询代码）"
            )
        else:
            logger.info(
                f"[task:{task_id}] ✅ 股票信息解析成功: {company_name} ({stock_code})"
            )

        await _update_report(
            stock_code=stock_code,
            company_name=company_name,
            progress=20,
        )

        # ── 执行多 Agent 工作流（使用事件流做进度更新） ─────
        app = _get_workflow()
        node_progress = {
            "fundamental_analyst": 35,
            "technical_analyst": 50,
            "value_analyst": 65,
            "news_analyst": 80,
            "memory_read_node": 85,
            "summarizer": 95,
            "memory_write_node": 98,
        }
        finished_nodes: set[str] = set()

        final_state = None
        if hasattr(app, "astream_events"):
            async for event in app.astream_events(initial_state, version="v1"):
                # 兼容不同事件结构：优先取 name，其次取 metadata.langgraph_node
                event_name = event.get("name")
                md = event.get("metadata") or {}
                node = event_name or md.get("langgraph_node") or md.get("node")

                # 以“链/节点结束”为信号更新进度（避免频繁写 DB）
                if event.get("event") in {"on_chain_end", "on_chain_complete"} and node in node_progress:
                    if node not in finished_nodes:
                        finished_nodes.add(node)
                        await _update_report(progress=node_progress[node])

                # 最终结果：on_chain_end 时 output 里会带最终 state（不同版本字段名略有差异）
                if event.get("event") == "on_chain_end" and node in {"__end__", "langgraph"}:
                    final_state = event.get("data", {}).get("output") or final_state

            if final_state is None:
                # 兜底：某些版本不会在 events 中返回 output，回退到 ainvoke 拿最终 state
                final_state = await app.ainvoke(initial_state)
        else:
            # 兼容老版本：无法流式拿事件，则保持原逻辑
            final_state = await app.ainvoke(initial_state)

        # ── 提取结果 ─────────────────────────────────────
        report_content = None
        report_path = None
        if final_state and final_state.get("data"):
            report_content = final_state["data"].get("final_report")
            report_path = final_state["data"].get("report_path")

        if not report_content:
            raise ValueError("工作流未返回报告内容，final_report 字段为空")

        # 与 agent 相同的 execution_dir 下写 final_report.md / final_report_info.json
        get_execution_logger().log_final_report(
            report_content, report_path or f"task_{task_id}"
        )
        finalize_execution_logger(success=True)

        await _update_report(
            status="completed",
            progress=100,
            content=report_content,
        )
        logger.info(f"[task:{task_id}] 报告生成成功，长度={len(report_content)}")

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"[task:{task_id}] 报告生成失败: {error_msg}", exc_info=True)
        finalize_execution_logger(success=False, error=error_msg)
        await _update_report(status="failed", progress=0, error_msg=error_msg)
