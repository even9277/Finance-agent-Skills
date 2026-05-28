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

FIX-4 升级：
  - 全链路统一 canonical symbol 格式为 XXXXXX.SH / XXXXXX.SZ / XXXXXX.BJ
  - 提供 canonicalize_symbol / format_symbol_for_display / parse_symbol_to_parts 公共工具
  - resolver 输出始终使用 canonical 格式
"""

import os
import logging
import re
from typing import Optional
from pathlib import Path
import asyncio

try:
    from dotenv import load_dotenv
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / "backend" / ".env", override=False)
except Exception:
    pass

logger = logging.getLogger("stock_resolver")

# ═══════════════════════════════════════════════════════════════
# FIX-4: Symbol Canonicalization Utilities
# Canonical format: "XXXXXX.SH" / "XXXXXX.SZ" / "XXXXXX.BJ"
# ═══════════════════════════════════════════════════════════════

_EXCHANGE_PREFIXES = {"sh", "sz", "bj"}
_EXCHANGE_SUFFIXES = {"SH", "SZ", "BJ"}


def canonicalize_symbol(raw: str | None) -> str:
    """Convert any known symbol format to canonical `XXXXXX.SH` form.

    Accepted inputs:
      - "sh.600519"  / "SH.600519"  (BaoStock style)
      - "600519.SH"  / "600519.sh"  (canonical/Tushare style)
      - "600519"                     (bare 6-digit code)
      - "SH600519"   / "sh600519"   (no-dot prefix)
    Returns empty string when input is not recognizable.
    """
    text = str(raw or "").strip()
    if not text:
        return ""

    upper = text.upper()
    if "." in upper:
        parts = upper.split(".", 1)
        if len(parts) == 2:
            left, right = parts
            if left.isdigit() and len(left) == 6 and right in _EXCHANGE_SUFFIXES:
                return upper
            if left in _EXCHANGE_SUFFIXES and right.isdigit() and len(right) == 6:
                return f"{right}.{left}"

    no_dot = re.sub(r"[.\-]", "", upper)
    for prefix in ("SH", "SZ", "BJ"):
        if no_dot.startswith(prefix) and len(no_dot) == len(prefix) + 6 and no_dot[len(prefix):].isdigit():
            return f"{no_dot[len(prefix):]}.{prefix}"

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        return f"{digits}.{_infer_exchange(digits)}"
    return upper


def _infer_exchange(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SH"


def format_symbol_for_display(canonical: str) -> str:
    """Render canonical symbol for user-facing display, e.g. '600519.SH'."""
    return canonicalize_symbol(canonical)


def parse_symbol_to_parts(canonical: str) -> tuple[str, str]:
    """Return (code, exchange) from canonical symbol, e.g. ('600519', 'SH')."""
    sym = canonicalize_symbol(canonical)
    if "." in sym:
        code, exchange = sym.split(".", 1)
        return code, exchange
    return sym, ""


def _to_baostock_format(canonical: str) -> str:
    """Convert canonical to BaoStock format: 'sh.600519'."""
    code, exchange = parse_symbol_to_parts(canonical)
    if exchange:
        return f"{exchange.lower()}.{code}"
    return canonical

_LLM_EXTRACT_PROMPT = """从用户输入中提取 A 股股票信息，只输出 JSON：

用户：{query}

提取规则：
1. company_name：标准股票名称，尽量提取真实上市公司简称或全称，如"贵州茅台"、"比亚迪"
2. stock_code：标准 A 股代码，格式为 "XXXXXX.SH" 或 "XXXXXX.SZ"，如 "600519.SH"、"300750.SZ"
3. 如果用户只给了公司名，请根据常识补全对应 A 股代码
4. 如果用户的句子里含有"今天""最近""行情""分析""帮我""请你"等口语词，不要把这些词当作公司名的一部分
5. 如果无法确定是哪个 A 股标的，两个字段都填 null

输出格式：{{"company_name": "xxx", "stock_code": "600519.SH"}}
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
            code = canonicalize_symbol(code.strip())
        
        logger.info("[stock_resolver] L3 LLM 抽取成功: company='%s', code='%s'", company, code)
        return company, code
    except Exception as exc:
        logger.warning(f"[stock_resolver] L3 LLM 抽取失败: {exc}")
        return None, None


# ═══════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════

def add_exchange_prefix(stock_code: str) -> str:
    """[Legacy] 为纯数字股票代码添加交易所前缀。
    新代码请直接使用 canonicalize_symbol()。
    """
    return canonicalize_symbol(stock_code)


async def resolve_stock(
    query: str,
    *,
    session_symbols: list[str] | None = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    统一入口：从用户自然语言中解析股票信息。

    返回：(company_name, stock_code)
    - stock_code 为 canonical 格式（如 "600519.SH"）
    - 任一字段可能为 None（未能解析时）

    新增 session_symbols 参数用于 FIX-3 追问继承（后续启用）。
    """
    resolution = await resolve_stock_entity(query, session_symbols=session_symbols)
    logger.info(
        "[stock_resolver] 最终结果: company='%s', code='%s' stage=%s confidence=%.4f",
        resolution.display_name,
        resolution.symbol,
        resolution.resolver_stage,
        float(resolution.confidence or 0.0),
    )
    return resolution.display_name or None, resolution.symbol or None


async def resolve_stock_entity(
    query: str,
    *,
    session_symbols: list[str] | None = None,
):
    from backend.services.entity_resolver import resolve_stock_entity as _resolve_stock_entity_impl

    try:
        return await asyncio.wait_for(
            _resolve_stock_entity_impl(query, session_symbols=session_symbols),
            timeout=20,
        )
    except asyncio.TimeoutError:
        logger.warning("[stock_resolver] 实体解析超时，退回空结果")
        from backend.services.entity_resolver import EntityResolutionResult

        return EntityResolutionResult(
            asset_type="stock",
            failure_code="stock_resolver_timeout",
            audit={"input_text": str(query or "").strip()},
        )
