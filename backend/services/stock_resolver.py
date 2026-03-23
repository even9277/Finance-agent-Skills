"""
stock_resolver.py — 股票名称/代码预解析模块

职责：在多 Agent 工作流启动前，将用户自然语言中的股票标识
解析为确定的 (company_name, stock_code) 二元组。

三层递进策略：
  L1 - 增强正则：覆盖"分析/看看/了解/怎么样"等常见句式 + 纯代码
  L2 - BaoStock 名称反查：用户只给名称时，查 get_all_stock 匹配全称/简称
  L3 - LLM 兜底：正则和反查都失败时，调用 LLM 做一次结构化抽取

设计原则：
  - 本模块是纯函数/工具模块，不修改任何 Agent 或工作流逻辑
  - 错误不阻断流程：任何一层失败均静默降级到下一层
  - 可被 agent_service.py 和 main.py 共同调用，消除重复维护
"""

import os
import re
import logging
from typing import Optional
from functools import lru_cache
from pathlib import Path

# 加载环境变量（确保 LLM API 配置可用）
try:
    from dotenv import load_dotenv
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_PROJECT_ROOT / "Financial-MCP-Agent" / ".env", override=False)
except Exception:
    pass

logger = logging.getLogger("stock_resolver")


# ═══════════════════════════════════════════════════════════════
# L1: 增强正则提取
# ═══════════════════════════════════════════════════════════════

# 合并 agent_service.py + main.py 的所有模式，并新增口语化模式
_PATTERNS_BOTH = [
    # 名称(代码) 格式
    r'([^（(,，\s]{2,8}?)\s*[（(](\d{6})[)）]',
    # 代码.名称 格式：600519.贵州茅台
    r'(\d{6})[.\s]+([^\s,，]{2,8})',
]

_PATTERNS_CODE_ONLY = [
    r'\b(\d{6})\b',          # 纯6位数字
    r'[shSH]{2}\.?(\d{6})',  # sh.600519 / SH600519
    r'[szSZ]{2}\.?(\d{6})',  # sz.000001
]

_PATTERNS_NAME_ONLY = [
    # 优先匹配"帮我看看X"、"看看X"这类口语化表达
    r'帮我(?:看看|了解)\s*([^\d（）()\s,，]{2,8}?)(?:\s*(?:最近|怎么样|走势|的|这只|这个|股票)|\s*$)',
    r'(?:看看|了解)\s*([^\d（）()\s,，]{2,8}?)(?:\s*(?:最近|怎么样|走势|的|这只|这个|股票)|\s*$)',
    # 常规分析句式
    r'(?:分析|研究|查一下|查查|评估|调研)\s*(?:一下\s*)?([^\d（）()\s,，]{2,8}?)(?:\s*(?:的|这只|这个|股票|怎么样|最近|走势|基本面|技术面|财务)|\s*$)',
    r'([^\d（）()\s,，]{2,8}?)\s*(?:这只|这个|的)?\s*(?:股票|走势|行情|基本面)',
    r'(?:关于|对于)\s*([^\d（）()\s,，]{2,8}?)\s*(?:的|，)',
]

_STOP_WORDS = frozenset([
    '的', '这个', '这只', '一下', '看看', '了解', '分析', '帮我', '我想',
    '给我', '财务状况', '投资价值', '基本面', '技术面', '请', '能否',
    '最近', '怎么样', '研究', '调研', '评估', '查一下', '查查', '光伏龙头',
    '新能源龙头', '科技龙头', '龙头', '走势', '行情',  # 新增常见描述词
])


def _regex_extract(query: str) -> tuple[Optional[str], Optional[str]]:
    """L1: 纯正则提取，返回 (company_name, stock_code)"""
    company_name = None
    stock_code = None

    # 尝试同时提取名称和代码
    for pattern in _PATTERNS_BOTH:
        m = re.search(pattern, query)
        if m:
            g1, g2 = m.group(1).strip(), m.group(2).strip()
            if g1.isdigit():
                stock_code, company_name = g1, g2
            else:
                company_name, stock_code = g1, g2
            break

    # 仅代码
    if not stock_code:
        for pattern in _PATTERNS_CODE_ONLY:
            m = re.search(pattern, query)
            if m:
                stock_code = m.group(1)
                break

    # 仅名称
    if not company_name:
        for pattern in _PATTERNS_NAME_ONLY:
            m = re.search(pattern, query)
            if m:
                candidate = m.group(1).strip()
                # 清理停用词（多次循环确保完全清除）
                for _ in range(3):  # 最多清理3轮
                    before = candidate
                    for w in _STOP_WORDS:
                        candidate = candidate.replace(w, '').strip()
                    if candidate == before:  # 没有更多停用词了
                        break
                if len(candidate) >= 2:
                    company_name = candidate
                    break

    return company_name, stock_code


# ═══════════════════════════════════════════════════════════════
# L2: BaoStock 名称 → 代码反查
# ═══════════════════════════════════════════════════════════════

_STOCK_NAME_MAP: dict[str, str] = {}  # name -> "sh.600519"
_STOCK_NAME_MAP_READY = False


def _init_stock_name_map() -> None:
    """
    一次性加载 BaoStock 全市场股票列表，构建 名称→代码 映射表。
    在首次调用时触发，后续走内存缓存。
    
    失败时静默降级（映射表为空，L2 跳过）。
    """
    global _STOCK_NAME_MAP, _STOCK_NAME_MAP_READY
    if _STOCK_NAME_MAP_READY:
        return
    _STOCK_NAME_MAP_READY = True
    
    try:
        import sys
        from pathlib import Path
        
        # 确保能导入 baostock 和 utils（可能在不同的虚拟环境）
        _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
        _MCP_ROOT = _PROJECT_ROOT / "a-share-mcp-is-just-i-need"
        if str(_MCP_ROOT / "src") not in sys.path:
            sys.path.insert(0, str(_MCP_ROOT / "src"))
        
        import baostock as bs
        
        # 尝试导入 baostock_login_context，如果不存在则自己实现
        try:
            from utils import baostock_login_context
        except ImportError:
            from contextlib import contextmanager
            @contextmanager
            def baostock_login_context():
                lg = bs.login()
                if lg.error_code != '0':
                    logger.warning(f"[stock_resolver] BaoStock login 失败: {lg.error_msg}")
                try:
                    yield
                finally:
                    bs.logout()
        
        with baostock_login_context():
            rs = bs.query_all_stock()
            if rs.error_code != '0':
                logger.warning(f"[stock_resolver] query_all_stock 失败: {rs.error_msg}")
                return
            
            count = 0
            while rs.next():
                row = rs.get_row_data()
                # row: [code, tradeStatus, code_name]
                if len(row) >= 3:
                    code, name = row[0], row[2]
                    if name and code:
                        _STOCK_NAME_MAP[name] = code
                        count += 1
                        # 简称映射：去掉常见后缀
                        short = name.replace('股份', '').replace('集团', '').replace('控股', '').strip()
                        if short and short != name and len(short) >= 2:
                            _STOCK_NAME_MAP.setdefault(short, code)
        
        logger.info(f"[stock_resolver] BaoStock 名称映射加载完成: {len(_STOCK_NAME_MAP)} 条 (原始={count})")
    except Exception as exc:
        logger.warning(f"[stock_resolver] BaoStock 名称映射加载失败（L2 降级）: {exc}", exc_info=True)


def _baostock_lookup(company_name: str) -> Optional[str]:
    """
    L2: 通过名称在全市场列表中查找股票代码。
    支持精确匹配 + 包含匹配（优先精确）。
    返回 BaoStock 格式的代码，如 "sh.600519"。
    """
    _init_stock_name_map()
    if not _STOCK_NAME_MAP:
        logger.warning("[stock_resolver] L2 名称映射表为空，跳过反查")
        return None
    
    logger.debug(f"[stock_resolver] L2 反查: '{company_name}', 映射表大小={len(_STOCK_NAME_MAP)}")
    
    # 精确匹配
    if company_name in _STOCK_NAME_MAP:
        logger.info(f"[stock_resolver] L2 精确匹配: '{company_name}' → {_STOCK_NAME_MAP[company_name]}")
        return _STOCK_NAME_MAP[company_name]
    
    # 包含匹配（名称是某个全称的子串）
    candidates = []
    for name, code in _STOCK_NAME_MAP.items():
        if company_name in name or name in company_name:
            candidates.append((name, code))
    
    logger.debug(f"[stock_resolver] L2 包含匹配候选: {len(candidates)} 个")
    
    if len(candidates) == 1:
        logger.info(f"[stock_resolver] L2 唯一候选: '{candidates[0][0]}' → {candidates[0][1]}")
        return candidates[0][1]
    elif len(candidates) > 1:
        # 多个匹配时取最短名称（最精确）
        candidates.sort(key=lambda x: len(x[0]))
        logger.info(
            f"[stock_resolver] L2 多个匹配: query='{company_name}', "
            f"选择='{candidates[0][0]}' ({candidates[0][1]})"
        )
        return candidates[0][1]
    
    logger.debug(f"[stock_resolver] L2 未找到匹配: '{company_name}'")
    return None


# ═══════════════════════════════════════════════════════════════
# L3: LLM 兜底抽取
# ═══════════════════════════════════════════════════════════════

_LLM_EXTRACT_PROMPT = """从用户输入中提取股票信息，只输出 JSON：

用户：{query}

提取规则：
1. company_name：公司名称（如"贵州茅台"、"比亚迪"）
2. stock_code：6位代码（如"600519"），无代码填null

输出格式：{{"company_name": "xxx", "stock_code": "123456"}}
无法识别：{{"company_name": null, "stock_code": null}}"""


async def _llm_extract(query: str) -> tuple[Optional[str], Optional[str]]:
    """
    L3: 调用 LLM 做结构化抽取（仅在 L1+L2 均失败时使用）。
    使用与各 Agent 相同的 OpenAI 兼容 API。
    """
    import json as _json
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        
        api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")
        
        if not all([api_key, base_url, model_name]):
            logger.debug("[stock_resolver] L3 LLM 配置不完整，跳过")
            return None, None
        
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
    
    三层递进：L1 正则 → L2 BaoStock 反查 → L3 LLM 兜底
    """
    # L1: 正则
    company_name, stock_code = _regex_extract(query)
    
    # 如果有代码但无名称 → 补名称（BaoStock 反查）
    if stock_code and not company_name:
        prefixed = add_exchange_prefix(stock_code)
        _init_stock_name_map()
        for name, code in _STOCK_NAME_MAP.items():
            if code == prefixed:
                company_name = name
                break
    
    # 如果有名称但无代码 → L2 BaoStock 名称反查
    if company_name and not stock_code:
        resolved_code = _baostock_lookup(company_name)
        if resolved_code:
            stock_code = resolved_code
            logger.info(f"[stock_resolver] L2 反查成功: '{company_name}' → {stock_code}")
    
    # 如果 L1+L2 都未能解析出代码 → L3 LLM 兜底
    if not stock_code or not company_name:  # 任一为空就尝试 LLM
        logger.info(f"[stock_resolver] L1+L2 不完整 (name={company_name}, code={stock_code})，尝试 L3 LLM")
        llm_name, llm_code = await _llm_extract(query)
        
        # 优先使用 LLM 结果，如果 LLM 提供了更完整的信息
        if llm_code and not stock_code:
            stock_code = llm_code
            logger.info(f"[stock_resolver] L3 LLM 提供代码: {llm_code}")
        if llm_name and not company_name:
            company_name = llm_name
            logger.info(f"[stock_resolver] L3 LLM 提供名称: {llm_name}")
        
        # LLM 给出名称后再尝试一次 L2 反查
        if company_name and not stock_code:
            resolved_code = _baostock_lookup(company_name)
            if resolved_code:
                stock_code = resolved_code
                logger.info(f"[stock_resolver] L3→L2 反查成功: '{company_name}' → {stock_code}")
    
    # 统一添加交易所前缀
    if stock_code and not stock_code.startswith(('sh.', 'sz.')):
        stock_code = add_exchange_prefix(stock_code)
    
    logger.info(f"[stock_resolver] 最终结果: company='{company_name}', code='{stock_code}'")
    return company_name, stock_code
