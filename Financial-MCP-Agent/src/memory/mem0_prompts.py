"""
金融版 Mem0 Prompt：事实抽取 + 记忆更新策略

提示词已迁移至 src/prompts/ltm_memory.py 统一管理。
本文件保持向后兼容，所有引用不需修改。
"""

from src.prompts.ltm_memory import (
    FINANCE_FACT_EXTRACTION_PROMPT,
    FINANCE_UPDATE_MEMORY_PROMPT,
    PROMPT_VERSION,
)

__all__ = [
    "FINANCE_FACT_EXTRACTION_PROMPT",
    "FINANCE_UPDATE_MEMORY_PROMPT",
    "PROMPT_VERSION",
]
