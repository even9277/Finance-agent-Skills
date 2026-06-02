"""
src.prompts — 提示词集中管理包

所有对话链路提示词均在此目录中统一版本管理。
各子模块可单独导入，也可通过此 __init__ 获取概览。
"""

from src.prompts.ltm_memory import FINANCE_FACT_EXTRACTION_PROMPT, FINANCE_UPDATE_MEMORY_PROMPT
from src.prompts.memory import SUMMARIZE_CONVERSATION_PROMPT, TOOL_DIGEST_PROMPT
from src.prompts.query_rewrite import (
    FALLBACK_REWRITER_SYSTEM_PROMPT,
    SOP_REWRITER_SYSTEM_PROMPT,
    TUSHARE_REWRITER_REFINER_PROMPT,
    TUSHARE_REWRITER_SYSTEM_PROMPT,
)
from src.prompts.routing import build_stage1_prompt
from src.prompts.skill_routing import ROUTER_PROMPT

__all__ = [
    "SOP_REWRITER_SYSTEM_PROMPT",
    "TUSHARE_REWRITER_SYSTEM_PROMPT",
    "TUSHARE_REWRITER_REFINER_PROMPT",
    "FALLBACK_REWRITER_SYSTEM_PROMPT",
    "ROUTER_PROMPT",
    "build_stage1_prompt",
    "SUMMARIZE_CONVERSATION_PROMPT",
    "TOOL_DIGEST_PROMPT",
    "FINANCE_FACT_EXTRACTION_PROMPT",
    "FINANCE_UPDATE_MEMORY_PROMPT",
]
