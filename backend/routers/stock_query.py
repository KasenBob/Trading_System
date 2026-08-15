"""股票查询 API"""

import time
from datetime import datetime

from fastapi import APIRouter, Query, HTTPException

from services.akshare_service import data_service

router = APIRouter(prefix="/api/stock", tags=["股票查询"])

# 财务指标内存缓存（code -> (过期时间戳, 数据列表)），财务数据基本不变
_financial_cache: dict = {}


@router.get("/search")
async def search_stocks(keyword: str = Query(..., min_length=1, description="搜索关键词")):
    """股票搜索（代码/名称/拼音）"""
    if not keyword.strip():
        return {"code": 0, "data": [], "count": 0}
    try:
        data = data_service.search_stocks(keyword.strip())
        return {"code": 0, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")


@router.get("/minute/{code}")
async def get_minute_data(code: str):
    """当日分时数据"""
    try:
        data = data_service.get_minute_data(code)
        return {"code": 0, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分时数据失败: {e}")


@router.get("/fundflow/{code}")
async def get_fund_flow(code: str, days: int = 60):
    """资金流向"""
    try:
        data = data_service.get_fund_flow(code, days=days)
        return {"code": 0, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取资金流向失败: {e}")


@router.get("/detail/{code}")
async def get_stock_detail(code: str):
    """个股详情 + 实时行情"""
    try:
        data = data_service.get_stock_detail(code)
        return {"code": 0, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {e}")


@router.get("/financial/{code}")
async def get_stock_financial(code: str):
    """个股财务指标（新浪财务接口，按报告期，带缓存）"""
    cached = _financial_cache.get(code)
    if cached and time.time() < cached[0]:
        return {"code": 0, "data": cached[1], "count": len(cached[1])}
    try:
        import akshare as ak
        start_year = str(datetime.now().year - 2)
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
        if df is None or df.empty:
            return {"code": 0, "data": []}

        # 动态匹配列名（避免中文编码问题）
        def _find_col(keywords):
            for c in df.columns:
                if all(k in c for k in keywords):
                    return c
            return None

        # 列名 → 优先关键词匹配，失败用列索引兜底
        col_map = {
            "date": 0,
            "eps": _find_col(["每股收益"]) or df.columns[2],
            "bps": _find_col(["每股净资产"]) or df.columns[6],
            "roe": _find_col(["净资产收益率", "加权"]) or df.columns[29],
            "profit_growth": _find_col(["净利润", "增长率"]) or df.columns[32],
            "revenue_growth": _find_col(["收入", "增长率"]) or df.columns[31],
            "debt_ratio": _find_col(["资产负债率"]) or df.columns[61],
            "total_asset": _find_col(["总资产"]) or df.columns[62],
        }

        def _to_float(v):
            try:
                if v is None or str(v) in ("nan", "None", ""):
                    return None
                return float(v)
            except Exception:
                return None

        records = []
        for _, row in df.iterrows():
            date_val = row.get("日期")
            item = {
                "date": str(date_val) if date_val is not None else "",
                "eps": _to_float(row.get(col_map["eps"])),
                "bps": _to_float(row.get(col_map["bps"])),
                "roe": _to_float(row.get(col_map["roe"])),
                "profit_growth": _to_float(row.get(col_map["profit_growth"])),
                "revenue_growth": _to_float(row.get(col_map["revenue_growth"])),
                "debt_ratio": _to_float(row.get(col_map["debt_ratio"])),
                "total_asset": _to_float(row.get(col_map["total_asset"])),
            }
            records.append(item)

        # 反转为最新在前
        records.reverse()
        _financial_cache[code] = (time.time() + 86400, records)
        return {"code": 0, "data": records, "count": len(records)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取财务数据失败: {e}")


