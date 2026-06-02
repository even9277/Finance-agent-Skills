from sqlalchemy import select

from backend.config import settings
from backend.db.database import AsyncSessionFactory
from backend.db.models import Report
from backend.services.report.workflow_factory import logger


def _agent_service_facade():
    from backend.services import agent_service

    return agent_service


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
    agent_service = _agent_service_facade()

    # 关键：复用 Financial-MCP-Agent 的全局 ExecutionLogger（与各 agent 的落盘日志同一个 execution_id）
    # 这样 final_report.md 会出现在 /root/Finance/logs/<execution_id>/reports/ 下，而不是另起目录。
    exec_logger = agent_service.initialize_execution_logger(base_log_dir=str(settings.project_root / "logs"))
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
        initial_state = await agent_service._build_initial_state(command, user_id=user_id)
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
        app = agent_service._get_workflow()
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
        agent_service.get_execution_logger().log_final_report(
            report_content, report_path or f"task_{task_id}"
        )
        agent_service.finalize_execution_logger(success=True)

        await _update_report(
            status="completed",
            progress=100,
            content=report_content,
        )
        logger.info(f"[task:{task_id}] 报告生成成功，长度={len(report_content)}")

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"[task:{task_id}] 报告生成失败: {error_msg}", exc_info=True)
        agent_service.finalize_execution_logger(success=False, error=error_msg)
        await _update_report(status="failed", progress=0, error_msg=error_msg)
