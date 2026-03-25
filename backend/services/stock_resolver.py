"""
stock_resolver.py — 股票名称/代码预解析模块

职责：在多 Agent 工作流启动前，将用户自然语言中的股票标识
解析为确定的 (company_name, stock_code) 二元组。

当前策略：
  - 直接使用 LLM 做结构化抽取
  - 不再在主链路中使用正则拆分或 BaoStock 名称反查

设计原则：
  - 本模块是纯函数/工具模块，不修改任何 Agent 或工作流逻辑
  - 解析失败不阻断流程，返回部分结果或空值
  - 可被 agent_service.py 和 main.py 共同调用，消除重复维护
"""

import os
import logging
from typing import Optional
from pathlib import Path
import asyncio

# 加载环境变量（确保 LLM API 配置可用）
try:
    from dotenv import load_dotenv
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / "backend" / ".env", override=False)
except Exception:
    pass

logger = logging.getLogger("stock_resolver")

_LLM_EXTRACT_PROMPT = """从用户输入中提取 A 股股票信息，只输出 JSON：

用户：{query}

提取规则：
1. company_name：标准股票名称，尽量提取真实上市公司简称或全称，如"贵州茅台"、"比亚迪"
2. stock_code：标准 A 股代码，必须输出带交易所前缀的 9 位格式，如"sh.600519"、"sz.300750"
3. 如果用户只给了公司名，请根据常识补全对应 A 股代码
4. 如果用户的句子里含有"今天""最近""行情""分析""帮我""请你"等口语词，不要把这些词当作公司名的一部分
5. 如果无法确定是哪个 A 股标的，两个字段都填 null

输出格式：{{"company_name": "xxx", "stock_code": "sh.600519"}}
无法识别：{{"company_name": null, "stock_code": null}}"""


def _resolver_model_name() -> str:
    return (
        os.getenv("CHAT_RESOLVER_MODEL")
        or os.getenv("OPENAI_COMPATIBLE_MODEL")
        or "kimi-k2.5"
    )


async def _llm_extract(query: str) -> tuple[Optional[str], Optional[str]]:
    """
    调用 LLM 做结构化抽取。
    使用与各 Agent 相同的 OpenAI 兼容 API。
    """
    import json as _json
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        
        api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        model_name = _resolver_model_name()
        
        if not all([api_key, base_url, model_name]):
            logger.debug("[stock_resolver] L3 LLM 配置不完整，跳过")
            return None, None
        
        logger.info("[stock_resolver] 使用解析模型: %s", model_name)
        llm = ChatOpenAI(
            model=model_name, api_key=api_key, base_url=base_url,
            temperature=0, max_tokens=150,
        )
        
        resp = await llm.ainvoke([HumanMessage(content=_LLM_EXTRACT_PROMPT.format(query=query))])
        text = resp.content.strip()
        
        # 提取 JSON（兼容 LLM 可能输出 markdown code block）
        if '```' in text:
            lines = text.split('```')
            for line in lines:
                if line.strip().startswith('json'):
                    text = line[4:].strip()
                    break
                elif line.strip().startswith('{'):
                    text = line.strip()
                    break
        
        # 移除可能的多余文本，只保留 JSON
        if '{' in text:
            start = text.index('{')
            end = text.rindex('}') + 1
            text = text[start:end]
        
        data = _json.loads(text)
        company = data.get("company_name")
        code = data.get("stock_code")

        if isinstance(code, str) and code.strip():
            code = code.strip()
            if not code.startswith(("sh.", "sz.")):
                code = add_exchange_prefix(code)
        
        logger.info(f"[stock_resolver] L3 LLM 抽取成功: company='{company}', code='{code}'")
        return company, code
    except Exception as exc:
        logger.warning(f"[stock_resolver] L3 LLM 抽取失败: {exc}")
        return None, None


# ═══════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════

def add_exchange_prefix(stock_code: str) -> str:
    """为纯数字股票代码添加交易所前缀。"""
    code = stock_code.replace('sh.', '').replace('sz.', '')
    if code.startswith('6'):
        return f"sh.{code}"
    elif code.startswith('0') or code.startswith('3'):
        return f"sz.{code}"
    return stock_code


async def resolve_stock(query: str) -> tuple[Optional[str], Optional[str]]:
    """
    统一入口：从用户自然语言中解析股票信息。
    
    返回：(company_name, stock_code)
    - stock_code 已包含交易所前缀（如 "sh.600519"）
    - 任一字段可能为 None（未能解析时）
    
    直接使用 LLM 结构化抽取。
    """
    logger.info("[stock_resolver] 使用 LLM 单入口解析股票信息")
    try:
        company_name, stock_code = await asyncio.wait_for(_llm_extract(query), timeout=20)
    except asyncio.TimeoutError:
        logger.warning("[stock_resolver] LLM 解析超时，返回空结果")
        company_name, stock_code = None, None

    logger.info(f"[stock_resolver] 最终结果: company='{company_name}', code='{stock_code}'")
    return company_name, stock_code
