"""行情数据 API 路由"""

from typing import Optional

from fastapi import APIRouter, Query

from services.akshare_service import data_service

router = APIRouter(prefix="/api/market", tags=["行情数据"])


@router.get("/realtime")
async def get_realtime_quotes(codes: str = Query(..., description="股票代码, 逗号分隔")):
    """获取实时行情"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    data = data_service.get_realtime_quotes(codes=code_list)
    return {"code": 0, "data": data, "count": len(data)}


@router.get("/realtime/etf")
async def get_etf_realtime(codes: Optional[str] = Query(None, description="ETF代码, 逗号分隔")):
    """获取 ETF 实时行情"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
    data = data_service.get_etf_realtime_quotes(codes=code_list)
    return {"code": 0, "data": data, "count": len(data)}


@router.get("/kline")
async def get_kline(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="K线周期: daily/weekly/monthly/60min"),
    start_date: Optional[str] = Query(None, description="起始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="截止日期 YYYYMMDD"),
    adjust: str = Query("qfq", description="复权类型: qfq/hfq/空字符串"),
):
    """获取历史 K 线数据"""
    if period in ("60", "60min"):
        data = data_service.get_kline_60min(code=code, adjust=adjust)
    else:
        data = data_service.get_kline(
            code=code, period=period, start_date=start_date, end_date=end_date, adjust=adjust
        )
    return {"code": 0, "data": data, "count": len(data)}


@router.get("/index/{code}")
async def get_index_daily(code: str = "sh000300"):
    """获取指数日线（如沪深300 sh000300）"""
    import akshare as ak
    try:
        df = ak.stock_zh_index_daily(symbol=code)
        if df is None or df.empty:
            return {"code": 0, "data": [], "count": 0}
        data = [
            {"date": str(row["date"]), "close": float(row["close"])}
            for _, row in df.iterrows()
        ]
        return {"code": 0, "data": data, "count": len(data)}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"获取指数数据失败: {e}")

