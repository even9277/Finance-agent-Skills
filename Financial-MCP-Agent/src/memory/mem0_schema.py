"""
Mem0 记忆类别与来源枚举，以及统一的 LTM metadata 契约。

所有写入 Mem0 的记忆必须携带符合 LTMMemoryMeta 结构的 metadata，
用于过滤、优先级判断和审计追溯。
"""

from enum import Enum
from typing import Optional, TypedDict


class MemoryCategory(str, Enum):
    RISK_PROFILE = "risk_profile"          # 风险偏好
    HORIZON = "horizon"                    # 持有周期
    MARKET_SCOPE = "market_scope"          # 市场范围（A股/ETF/QDII）
    SECTOR_FOCUS = "sector_focus"          # 关注板块
    WATCHLIST_STOCK = "watchlist_stock"    # 自选股/关注标的
    CONSTRAINTS = "constraints"            # 约束（不碰ST、仓位限制等）
    RESPONSE_PREF = "response_preference"  # 回答偏好（简洁/详细/先风险）
    CORRECTION = "correction"              # 用户主动纠正


class MemorySource(str, Enum):
    COLD_START = "cold_start"              # 冷启动引导写入（高优先级）
    UI = "ui"                              # 前端卡片/滑块/标签显式操作（高优先级）
    EXPLICIT_CORR = "explicit_correction"  # 对话中用户明确纠正（中优先级）
    CHAT_INFERRED = "chat_inferred"        # 对话中 LLM 推断（低优先级）
    REPORT_INFERRED = "report_inferred"    # 报告生成时推断（低优先级）


# 优先级数值：高优先级来源写入的字段，低优先级来源不得覆盖
SOURCE_PRIORITY: dict[MemorySource, int] = {
    MemorySource.UI: 4,
    MemorySource.COLD_START: 3,
    MemorySource.EXPLICIT_CORR: 2,
    MemorySource.CHAT_INFERRED: 1,
    MemorySource.REPORT_INFERRED: 1,
}


class LTMMemoryMeta(TypedDict, total=False):
    """每条写入 Mem0 的记忆必须携带的 metadata 结构（应用层约定）"""
    category: str      # MemoryCategory 值
    source: str        # MemorySource 值
    confidence: float  # 0.0-1.0；LLM 抽取时填入，UI 操作置 1.0
    updated_by: str    # 'user' | 'llm' | 'system'
    session_id: str    # 来源会话 UUID（对话触发）
    run_id: str        # 来源报告 task_id（报告触发）
    evidence_ref: str  # 指向 messages.id 或 reports.id，逗号分隔
    active: bool       # 当前是否有效（False=软删除，过滤时排除）


# 风险偏好值到中文显示名的映射
RISK_LEVEL_DISPLAY: dict[str, str] = {
    "conservative": "保守",
    "moderate": "稳健",
    "balanced": "平衡",
    "aggressive": "进取",
    "speculative": "激进",
}

# 投资周期值到中文显示名的映射
HORIZON_DISPLAY: dict[str, str] = {
    "ultra_short": "超短线（日内~1周）",
    "short": "短线（1周~1月）",
    "swing": "波段（1~6个月）",
    "long": "中长线（6个月以上）",
}

# 回答偏好值到中文显示名的映射
RESPONSE_PREF_DISPLAY: dict[str, str] = {
    "concise": "简洁",
    "balanced": "均衡",
    "detailed": "详细",
    "risk_first": "先讲风险",
}
