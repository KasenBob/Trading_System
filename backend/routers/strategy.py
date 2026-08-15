"""策略 + 回测 API"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models.strategy import Strategy, Backtest, BacktestTrade
from models.user import User
from services.auth import get_current_user
from services.akshare_service import data_service
from services.backtest_engine import BacktestEngine, check_pullback_signal
from services.multifactor import multifactor_select, multifactor_select_full, _calc_momentum_20d
from services.ai_analysis import analyze_stocks

router = APIRouter(prefix="/api/strategy", tags=["策略"])


# ── 预设策略模板 ──────────────────────

PRESETS = [
    {"name": "双均线交叉", "type": "ma_cross", "params": {"fast": 5, "slow": 20}},
    {"name": "MACD金叉死叉", "type": "macd", "params": {"fast": 12, "slow": 26, "signal_period": 9, "ma_filter": 60}},
    {"name": "布林带突破", "type": "bollinger", "params": {"period": 20, "std": 2.0}},
    {"name": "RSI超买超卖", "type": "rsi", "params": {"period": 14, "oversold": 30, "overbought": 70}},
    {"name": "KDJ随机指标", "type": "kdj", "params": {"n": 9, "k_period": 3, "d_period": 3}},
    {"name": "单边上升策略", "type": "uptrend", "params": {"fast": 5, "trail_pct": 8}},
    {"name": "震荡盘整策略", "type": "oscillation", "params": {
        "boll_period": 10, "boll_std": 2.0, "rsi_period": 14,
        "rsi_oversold": 30, "rsi_overbought": 70, "kdj_n": 9,
        "kdj_k": 3, "kdj_d": 3, "j_oversold": 0, "j_overbought": 100}},
    {"name": "上升回调策略", "type": "pullback", "params": {
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "boll_period": 20, "boll_std": 2.0, "kdj_n": 9,
        "kdj_k": 3, "kdj_d": 3, "rsi_period": 14,
        "rsi_low": 40, "rsi_high": 50, "stop_loss_ratio": 0.98, "trail_pct": 8}},
]


class StrategyCreate(BaseModel):
    name: str
    type: str
    params: dict = {}


class BacktestRequest(BaseModel):
    code: str
    start_date: str  # YYYYMMDD
    end_date: str
    initial_capital: float = 100000
    combine: str = "separate"  # separate=各自回测 / filter=多层过滤 / and=共振 / vote=投票


class MultifactorRequest(BaseModel):
    codes: list[str] = []          # 候选股票，为空则用自选股
    weights: dict = {}             # {"ep":0.35,"roe":0.3,"momentum":0.1,"market_cap":0.25}
    top_n: int = 10


@router.get("/presets")
async def get_presets():
    return {"code": 0, "data": PRESETS}


@router.get("/pullback/signal/{code}")
async def pullback_signal(code: str):
    """上升回调策略实时买入信号（日线 + 真实 60 分钟 K 线）"""
    from datetime import datetime, timedelta
    try:
        start = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")
        daily = data_service.get_kline(code=code, period="daily", start_date=start)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"日线数据获取失败: {e}")
    try:
        min60 = data_service.get_kline_60min(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"60分钟数据获取失败: {e}")
    result = check_pullback_signal(daily, min60)
    return {"code": 0, "data": result}


@router.get("")
async def list_strategies(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Strategy).where(Strategy.user_id == user.id).order_by(Strategy.created_at)
    )
    items = result.scalars().all()
    return {"code": 0, "data": [
        {"id": s.id, "name": s.name, "type": s.type, "params": s.params, "enabled": s.enabled} for s in items
    ]}


@router.post("")
async def create_strategy(body: StrategyCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    import json
    s = Strategy(user_id=user.id, name=body.name, type=body.type, params=json.dumps(body.params, ensure_ascii=False), enabled=True)
    db.add(s); await db.flush()
    return {"code": 0, "data": {"id": s.id}, "message": "已创建"}


@router.delete("/{sid}")
async def delete_strategy(sid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Strategy).where(Strategy.id == sid, Strategy.user_id == user.id))
    await db.flush()
    return {"code": 0, "message": "已删除"}


@router.put("/{sid}")
async def update_strategy(sid: int, body: StrategyCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """更新策略（名称/参数）"""
    import json
    s_result = await db.execute(select(Strategy).where(Strategy.id == sid, Strategy.user_id == user.id))
    s = s_result.scalar_one_or_none()
    if not s: raise HTTPException(status_code=404, detail="未找到")
    s.name = body.name
    s.type = body.type
    s.params = json.dumps(body.params, ensure_ascii=False)
    await db.flush()
    return {"code": 0, "message": "已更新"}


@router.put("/{sid}/toggle")
async def toggle_strategy(sid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s_result = await db.execute(select(Strategy).where(Strategy.id == sid, Strategy.user_id == user.id))
    s = s_result.scalar_one_or_none()
    if not s: raise HTTPException(status_code=404, detail="未找到")
    s.enabled = not s.enabled
    await db.flush()
    return {"code": 0, "data": {"enabled": s.enabled}, "message": "已切换"}


@router.post("/backtest")
async def run_backtest(body: BacktestRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """运行回测"""
    # 获取K线
    kline = data_service.get_kline(code=body.code, start_date=body.start_date, end_date=body.end_date)
    if not kline:
        raise HTTPException(status_code=400, detail="无K线数据")

    # 获取当前用户所有启用策略
    result = await db.execute(select(Strategy).where(Strategy.user_id == user.id, Strategy.enabled == True))
    strategies = result.scalars().all()
    if not strategies:
        raise HTTPException(status_code=400, detail="请先创建并启用策略")

    engine = BacktestEngine(kline, body.initial_capital)
    results = []

    import json
    parsed = []
    for st in strategies:
        params = json.loads(st.params) if isinstance(st.params, str) else st.params
        parsed.append((st, params))

    if body.combine != "separate" and len(parsed) > 1:
        # 组合回测：多层过滤 / 共振 / 投票
        signals = []
        for st, params in parsed:
            signals.append(engine.generate_signals(st.type, params))
        combined = BacktestEngine.combine_signals(signals, body.combine)
        bt_result = engine.run(combined)
        bt_result["strategy_name"] = f"组合策略({body.combine})"
        bt_result["strategy_type"] = f"combine_{body.combine}"
        results.append(bt_result)
    else:
        # 各自回测
        for st, params in parsed:
            try:
                signal = engine.generate_signals(st.type, params)
                bt_result = engine.run(signal)
                bt_result["strategy_name"] = st.name
                bt_result["strategy_type"] = st.type
                results.append(bt_result)
            except Exception as e:
                results.append({"strategy_name": st.name, "error": str(e)})

    # 存库
    from datetime import datetime as _dt
    bt = Backtest(
        strategy_id=strategies[0].id, code=body.code,
        start_date=_dt.strptime(body.start_date, "%Y%m%d").date(),
        end_date=_dt.strptime(body.end_date, "%Y%m%d").date(),
        initial_capital=body.initial_capital, status="completed",
        result=str(results))
    db.add(bt); await db.flush()

    return {"code": 0, "data": results}


@router.post("/multifactor")
async def run_multifactor(body: MultifactorRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """多因子选股"""
    from models.watchlist import Watchlist

    # 候选股票：优先用请求里的 codes，否则用当前用户自选股
    codes = body.codes
    if not codes:
        wl_result = await db.execute(select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.type == "stock"))
        codes = [w.code for w in wl_result.scalars().all()]
    if not codes:
        raise HTTPException(status_code=400, detail="请先在自选股页添加股票，或传入 codes")

    # 默认权重
    weights = body.weights or {"ep": 0.35, "roe": 0.3, "momentum": 0.1, "market_cap": 0.25}

    try:
        result = multifactor_select(codes=codes, weights=weights, top_n=body.top_n)
        return {"code": 0, "data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"多因子选股失败: {e}")

# ═══════════ 全市场多因子选股（异步任务 + 进度） ═══════════

import threading
import uuid

_tasks: dict = {}


@router.post("/multifactor/full/start")
async def start_full_multifactor(body: MultifactorRequest):
    """启动全市场多因子选股（异步），返回任务ID"""
    task_id = str(uuid.uuid4())
    weights = body.weights or {"ep": 0.35, "roe": 0.3, "momentum": 0.1, "market_cap": 0.25}
    _tasks[task_id] = {"progress": 0, "status": "running", "result": [], "error": ""}

    def _run():
        def _progress(p):
            t = _tasks.get(task_id)
            if t:
                t["progress"] = p
        try:
            result, use_precise = multifactor_select_full(weights=weights, top_n=body.top_n, progress_callback=_progress)
            _tasks[task_id] = {"progress": 100, "status": "done", "result": result, "use_precise_finance": use_precise, "error": ""}
        except Exception as e:
            _tasks[task_id] = {"progress": 100, "status": "error", "result": [], "use_precise_finance": False, "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return {"code": 0, "task_id": task_id}


@router.get("/multifactor/full/progress/{task_id}")
async def get_full_progress(task_id: str):
    """查询全市场选股进度"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 0, "progress": task["progress"], "status": task["status"]}


@router.get("/multifactor/full/result/{task_id}")
async def get_full_result(task_id: str):
    """查询全市场选股结果"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] == "error":
        return {"code": 0, "status": "error", "data": [], "use_precise_finance": False, "error": task["error"]}
    return {"code": 0, "status": task["status"], "data": task["result"], "use_precise_finance": task.get("use_precise_finance", False)}


class AIAnalysisRequest(BaseModel):
    stocks: list[dict] = []


@router.post("/ai-analysis")
async def ai_analysis(body: AIAnalysisRequest, user: User = Depends(get_current_user)):
    """对多因子选股结果做 AI 分析（DeepSeek）"""
    if not body.stocks:
        raise HTTPException(status_code=400, detail="请先选股")
    try:
        text = await asyncio.to_thread(analyze_stocks, body.stocks)
        return {"code": 0, "data": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 分析失败: {e}")


class AnalyzeBatchRequest(BaseModel):
    stocks: list[dict] = []  # [{code, name, type}]


@router.post("/analyze-batch")
async def analyze_batch(body: AnalyzeBatchRequest, user: User = Depends(get_current_user)):
    """获取一组股票的展示字段（代码/名称/类型/行业/PE/PB/EP/ROE/动量/市值），供个股分析板块使用"""
    stocks = [s for s in (body.stocks or []) if s.get("code")]
    if not stocks:
        raise HTTPException(status_code=400, detail="请先添加股票")

    # 去重（保持顺序）
    seen: set[str] = set()
    uniq: list[dict] = []
    for s in stocks:
        if s["code"] not in seen:
            seen.add(s["code"])
            uniq.append(s)
    stocks = uniq
    codes = [s["code"] for s in stocks]

    valuations = data_service.get_market_valuation(codes=codes)
    val_map = {v["code"]: v for v in valuations}

    industry_map: dict[str, str] = {}
    try:
        industry_map = data_service.get_stock_industry(codes)
    except Exception:
        pass

    # 并发计算20日动量
    with ThreadPoolExecutor(max_workers=min(len(codes), 20)) as ex:
        momentums = list(ex.map(_calc_momentum_20d, codes))

    result = []
    for i, s in enumerate(stocks):
        code = s["code"]
        v = val_map.get(code) or {}
        pe = v.get("pe")
        pb = v.get("pb")
        mkt = v.get("total_market_cap")
        ep = 1.0 / pe if pe and pe > 0 else None
        roe = (pb / pe * 100) if pe and pb and pe > 0 and pb > 0 else None
        result.append({
            "code": code,
            "name": s.get("name") or v.get("name") or code,
            "type": s.get("type") or "stock",
            "industry": industry_map.get(code, ""),
            "pe": pe,
            "pb": pb,
            "ep": round(ep, 4) if ep is not None else None,
            "roe": round(roe, 2) if roe is not None else None,
            "momentum": momentums[i],
            "market_cap": round(mkt / 1e8, 2) if mkt else None,
        })
    return {"code": 0, "data": result, "count": len(result)}


class MarketRegimeRequest(BaseModel):
    codes: list[str] = []


@router.post("/market-regime")
async def market_regime(body: MarketRegimeRequest, user: User = Depends(get_current_user)):
    """分析个股当前行情阶段（单边上升/震荡盘整/单边下跌/上升回调，技术面非AI）"""
    from services.backtest_engine import analyze_market_regime

    result = []
    for code in body.codes:
        try:
            klines = data_service.get_kline(code=code, period="daily")
            name = code
            try:
                quotes = data_service.get_realtime_quotes(codes=[code])
                if quotes:
                    name = quotes[0].get("name") or code
            except Exception:
                pass
            analysis = analyze_market_regime(klines)
            result.append({"code": code, "name": name, **analysis})
        except Exception as e:
            result.append({"code": code, "name": code, "regime": "分析失败", "regime_key": "error",
                           "explanation": f"分析失败: {e}", "indicators": {}, "signals": []})
    return {"code": 0, "data": result, "count": len(result)}
