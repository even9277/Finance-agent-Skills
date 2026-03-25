"""
持仓/自选股路由
Phase 1: 接口结构完整，返回 stub 数据或空列表
Phase 4: 完整实现
"""

import uuid

from fastapi import APIRouter, Depends, UploadFile

from backend.middleware.auth import AuthContext, require_auth, require_query_user
from backend.schemas.portfolio import (
    HoldingCreateRequest,
    HoldingItem,
    SyncResponse,
    WatchlistAddRequest,
    WatchlistItem,
)

router = APIRouter()

_STUB_NOTE = "Phase 1 预留接口，Phase 4 完整实现"


@router.post("/holdings/upload", summary="CSV 批量上传持仓（Phase 4）")
async def upload_holdings(file: UploadFile, _: AuthContext = Depends(require_auth)):
    return {"message": _STUB_NOTE, "filename": file.filename}


@router.post("/holdings", summary="单条录入持仓（Phase 4）")
async def create_holding(body: HoldingCreateRequest, _: AuthContext = Depends(require_auth)):
    return {"message": _STUB_NOTE}


@router.get("/holdings", response_model=list[HoldingItem], summary="获取持仓列表（Phase 4）")
async def get_holdings(user_id: str = Depends(require_query_user)):
    return []


@router.put("/holdings/{holding_id}", summary="修改持仓（Phase 4）")
async def update_holding(holding_id: str, body: HoldingCreateRequest, _: AuthContext = Depends(require_auth)):
    return {"message": _STUB_NOTE}


@router.delete("/holdings/{holding_id}", summary="删除持仓（Phase 4）")
async def delete_holding(holding_id: str, _: AuthContext = Depends(require_auth)):
    return {"message": _STUB_NOTE}


@router.post("/watchlist", summary="添加自选股（Phase 4）")
async def add_watchlist(body: WatchlistAddRequest, user_id: str = Depends(require_query_user)):
    return {"message": _STUB_NOTE}


@router.get("/watchlist", response_model=list[WatchlistItem], summary="获取自选股列表（Phase 4）")
async def get_watchlist(user_id: str = Depends(require_query_user)):
    return []


@router.delete("/watchlist/{stock_code}", summary="删除自选股（Phase 4）")
async def delete_watchlist(stock_code: str, user_id: str = Depends(require_query_user)):
    return {"message": _STUB_NOTE}


@router.get("/prices/daily", summary="批量获取前日收盘价及涨跌幅（Phase 4）")
async def get_daily_prices(user_id: str = Depends(require_query_user)):
    return {"prices": {}, "note": _STUB_NOTE}


@router.post("/sync", response_model=SyncResponse, summary="一键同步最新行情（Phase 4）")
async def sync_prices(user_id: str = Depends(require_query_user)):
    return SyncResponse(task_id=str(uuid.uuid4()))


@router.get("/template/csv", summary="下载持仓 CSV 模板")
async def download_csv_template():
    from fastapi.responses import Response

    content = "股票代码,股票名称,成本价,持仓数量\nsh.600519,贵州茅台,1800.00,100\n"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="holdings_template.csv"'},
    )
