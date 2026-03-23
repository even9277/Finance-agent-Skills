"""
Financial-MCP-Agent 长期记忆（LTM）模块 - Phase 3

架构：
  双轨 LTM 体系：
  - PostgreSQL user_invest_profiles 表（权威主数据，UI直接读写）
  - Mem0 + pgvector（语义增强层，通过 outbox 异步同步）

暴露的主要接口：MemoryService（统一入口，所有上层代码仅调用此类）
"""

from .memory_service import MemoryService

__all__ = ["MemoryService"]
