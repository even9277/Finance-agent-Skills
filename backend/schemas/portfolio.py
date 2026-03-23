"""
持仓/自选股相关 Pydantic 模型
Phase 1: 预留结构，接口返回 stub 数据
Phase 4: 完整实现
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HoldingItem(BaseModel):
    id: str
    stock_code: str
    stock_name: Optional[str] = None
    cost_price: Optional[float] = None
    quantity: Optional[int] = None
    current_price: Optional[float] = None    # 行情同步后填充
    pct_change: Optional[float] = None       # 前日涨跌幅
    market_value: Optional[float] = None     # 市值
    profit_loss: Optional[float] = None      # 盈亏额
    profit_loss_pct: Optional[float] = None  # 盈亏比

    model_config = {"from_attributes": True}


class HoldingCreateRequest(BaseModel):
    stock_code: str
    stock_name: Optional[str] = None
    cost_price: Optional[float] = None
    quantity: Optional[int] = None


class WatchlistItem(BaseModel):
    id: str
    stock_code: str
    stock_name: Optional[str] = None
    pct_change: Optional[float] = None  # 行情同步后填充
    added_at: datetime

    model_config = {"from_attributes": True}


class WatchlistAddRequest(BaseModel):
    stock_code: str
    stock_name: Optional[str] = None


class SyncResponse(BaseModel):
    task_id: str
    message: str = "行情同步已触发，请稍后刷新"
