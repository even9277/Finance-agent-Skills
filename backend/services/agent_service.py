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

import re
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.application.report_progress.contracts import (
    ReportProgressNotification,
    ReportProgressPublisher,
    ReportTaskStatus,
    ReportTerminalNotification,
)
from backend.application.report_progress.hub import report_progress_hub
from backend.application.report_progress.snapshot import (
    REPORT_GENERATION_FAILED_CODE,
    REPORT_GENERATION_FAILED_MESSAGE,
)
from backend.application.report_progress.tracker import ReportProgressTracker

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


def _extract_final_state_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """从 LangGraph 根图结束事件中提取最终状态。

    Args:
        event: ``astream_events(version="v2")`` 返回的单条事件。LangGraph 可能把
            根图命名为 ``LangGraph``、``langgraph`` 或 ``__end__``。

    Returns:
        根图输出状态；非根图结束事件或输出结构不合法时返回 ``None``。
    """
    if event.get("event") != "on_chain_end":
        return None

    metadata = event.get("metadata") or {}
    event_name = event.get("name") or metadata.get("langgraph_node") or metadata.get("node")
    if str(event_name or "").lower() not in {"__end__", "langgraph"}:
        return None

    output = (event.get("data") or {}).get("output")
    return output if isinstance(output, dict) else None


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
# P1 修复：统一复用 stock_resolver 股票解析入口
# ─────────────────────────────────────────────────────────────
# 注意：保留旧的 extract_stock_info() 作为向后兼容的同步接口（仅走 L1 正则）
# 新增 resolve_stock 异步接口；具体解析策略由 stock_resolver 统一维护
from backend.services.stock_resolver import resolve_stock  # noqa: E402


def extract_stock_info(query: str) -> tuple[str | None, str | None]:
    """
    【已废弃】仅保留用于向后兼容。
    从自然语言查询中提取公司名称和股票代码（仅正则，不做 BaoStock 反查/LLM 兜底）。
    
    新代码请使用 resolve_stock(query) 异步接口，避免复制解析策略。
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
    
    P1 修复：改为 async，使用统一的 resolve_stock() 解析入口。
    P2 修复：接受 user_id 参数并写入 memory_user_id，确保 LTM 节点能正确读取用户画像。
    """
    # P1: 复用统一解析服务，具体策略由 stock_resolver 所有。
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
        data["stock_code"] = stock_code  # resolve_stock 已包含 sh./sz. 前缀

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
    publisher: ReportProgressPublisher | None = None,
) -> None:
    """运行完整多 Agent 报告工作流并提交权威状态与低延迟通知。

    Args:
        task_id: 数据库报告任务标识。
        report_id: 最终报告标识。
        command: 用户报告指令，只传给既有 Agent 工作流。
        user_id: 报告所属用户，用于既有记忆读取。
        publisher: 可替换的非阻塞进度发布端口；默认使用当前进程 Hub。

    Notes:
        数据库始终是恢复权威。阶段通知在对应 progress 提交后发送，任务终态
        在 ``completed``/``failed`` 提交后发送；发布器故障不得改变报告结果。
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

    active_publisher = publisher or report_progress_hub
    personalization_completion_node = (
        "prepare_summary_context" if settings.enable_stm else "memory_read_node"
    )
    tracker = ReportProgressTracker(
        task_id=task_id,
        report_id=report_id,
        personalization_completion_nodes={personalization_completion_node},
    )
    persisted_progress = 0

    def _publish(message: ReportProgressNotification | ReportTerminalNotification) -> None:
        """以 best-effort 方式发布通知，不让观察层决定报告成败。"""
        try:
            active_publisher.publish(message)
        except Exception as exc:
            logger.warning(
                "report_progress_publish_failed stage=%s task_id=%s report_id=%s "
                "status=%s error_code=%s error_type=%s",
                "report_progress",
                task_id,
                report_id,
                "DEGRADED",
                "REPORT_PROGRESS_PUBLISH_FAILED",
                type(exc).__name__,
            )

    async def _update_report(**kwargs: object) -> None:
        """短事务更新报告，并在数据库边界强制 progress 单调。"""
        async with AsyncSessionFactory() as db:
            result = await db.execute(select(Report).where(Report.task_id == task_id))
            rpt = result.scalar_one_or_none()
            if rpt:
                for k, v in kwargs.items():
                    if k == "progress":
                        if not isinstance(v, int):
                            raise TypeError("progress 更新值必须为 int")
                        v = max(int(rpt.progress or 0), v)
                    setattr(rpt, k, v)
                await db.commit()

    async def _record_stage(notification: ReportProgressNotification) -> None:
        """先持久化单调百分比，再发布真实阶段状态。"""
        nonlocal persisted_progress
        if notification.progress > persisted_progress:
            await _update_report(progress=notification.progress)
            persisted_progress = notification.progress
        _publish(notification)

    try:
        await _update_report(status="running", progress=10)
        persisted_progress = 10
        _publish(tracker.begin_preparing())

        # P1+P2: _build_initial_state 改为 async，传入 user_id
        initial_state = await _build_initial_state(command, user_id=user_id)
        company_name = initial_state["data"].get("company_name")
        stock_code = initial_state["data"].get("stock_code")

        # 只记录解析状态和任务标识，避免把用户指令或公司名写入日志。
        if not stock_code:
            logger.warning(
                "report_stock_unresolved stage=%s task_id=%s status=%s error_code=%s",
                "report.prepare",
                task_id,
                "DEGRADED",
                "REPORT_STOCK_CODE_UNRESOLVED",
            )
        else:
            logger.info(
                "report_stock_resolved stage=%s task_id=%s status=%s",
                "report.prepare",
                task_id,
                "SUCCEEDED",
            )

        await _update_report(
            stock_code=stock_code,
            company_name=company_name,
            progress=20,
        )
        persisted_progress = 20
        _publish(tracker.complete_preparing())

        # ── 执行多 Agent 工作流（使用事件流做进度更新） ─────
        app = _get_workflow()
        personalization_skipped = False

        final_state = None
        if hasattr(app, "astream_events"):
            # v2 根结束事件返回完整 state；v1 在当前 LangGraph 中只返回按节点分块，
            # 会被误判为缺少 final_report，且该协议已进入弃用路径。
            async for event in app.astream_events(initial_state, version="v2"):
                md = event.get("metadata") or {}
                node = md.get("langgraph_node") or md.get("node") or event.get("name")

                # 无 STM/LTM 时，在真实 summarizer 启动前显式关闭可选阶段。
                if (
                    node == "summarizer"
                    and not settings.enable_stm
                    and not settings.enable_memory
                    and not personalization_skipped
                ):
                    await _record_stage(tracker.skip_optional_personalization())
                    personalization_skipped = True

                notification = tracker.observe_langgraph_event(event)
                if notification is not None:
                    await _record_stage(notification)

                # 最终结果：on_chain_end 时 output 里会带最终 state（不同版本字段名略有差异）
                root_state = _extract_final_state_from_event(event)
                if root_state is not None:
                    final_state = root_state

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
            error_msg=None,
        )
        persisted_progress = 100
        _publish(
            ReportTerminalNotification(
                task_id=task_id,
                report_id=report_id,
                status=ReportTaskStatus.COMPLETED,
                progress=100,
            )
        )
        logger.info(f"[task:{task_id}] 报告生成成功，长度={len(report_content)}")

    except Exception as exc:
        for failed_stage in tracker.fail_active_stages():
            _publish(failed_stage)
        logger.error(
            "report_generation_failed stage=%s task_id=%s report_id=%s status=%s "
            "error_code=%s error_type=%s",
            "report.generate",
            task_id,
            report_id,
            "FAILED",
            REPORT_GENERATION_FAILED_CODE,
            type(exc).__name__,
        )
        finalize_execution_logger(success=False, error=REPORT_GENERATION_FAILED_MESSAGE)
        failed_progress = max(persisted_progress, tracker.current_progress)
        await _update_report(
            status="failed",
            progress=failed_progress,
            error_msg=REPORT_GENERATION_FAILED_MESSAGE,
        )
        _publish(
            ReportTerminalNotification(
                task_id=task_id,
                report_id=report_id,
                status=ReportTaskStatus.FAILED,
                progress=failed_progress,
                error_code=REPORT_GENERATION_FAILED_CODE,
                message=REPORT_GENERATION_FAILED_MESSAGE,
            )
        )
