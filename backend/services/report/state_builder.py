import re
from datetime import datetime
from typing import Any

from backend.integrations.agent_runtime.report_runtime import AgentState, make_stm_defaults

from backend.services.stock_resolver import resolve_stock


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
