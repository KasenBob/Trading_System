"""自动交易服务 — 信号计算、程序化下单、每日调仓、定时调度"""

import asyncio
import json
from datetime import date, datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session
from models.account import Account, Position, Transaction, AssetSnapshot
from models.autotrade import AutoTradeItem, AutoTradeLog
from services.akshare_service import data_service
from services.backtest_engine import BacktestEngine, analyze_market_regime


# ── 行情 / 工具 ──────────────────────────────

def _get_quote(code: str) -> dict:
    try:
        quotes = data_service.get_realtime_quotes(codes=[code])
        return quotes[0] if quotes else {}
    except Exception:
        return {}


def _norm_date(s) -> str:
    return str(s or "").replace("/", "-").replace(".", "-")[:10]


def _limit_pct(code: str) -> float:
    return 0.2 if code.startswith(("3", "68")) else 0.1


_trade_calendar_cache: dict = {"day": None, "dates": None}


def is_trading_day(d: date) -> bool:
    """交易日判断：周末必非交易日；法定节假日用 akshare 交易日历兜底（按日缓存，避免盘中频繁请求）"""
    if d.weekday() >= 5:
        return False
    global _trade_calendar_cache
    day_key = d.strftime("%Y-%m-%d")
    if _trade_calendar_cache["day"] != day_key:
        dates = None
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            if df is not None and "trade_date" in df.columns:
                dates = set(str(x)[:10] for x in df["trade_date"].tolist())
        except Exception:
            pass
        _trade_calendar_cache["day"] = day_key
        _trade_calendar_cache["dates"] = dates
    dates = _trade_calendar_cache["dates"]
    if dates is None:
        return True  # 日历获取失败时降级：仅周末判断
    return day_key in dates


# ── 信号计算 ──────────────────────────────

def compute_latest_signal(code: str, strategy_type: str, params: dict, base_price: float = None) -> int:
    """历史日线 + 今日实时价拼最新K线 → 取最后一根信号（1买/-1卖/0持有）"""
    quote = _get_quote(code)
    price = quote.get("price")

    # 网格策略：以基准价（买入价）判断，而非整段历史
    if strategy_type == "grid" and base_price:
        if not price:
            return 0
        grid_pct = params.get("grid_pct", 5)
        if price <= base_price * (1 - grid_pct / 100):
            return 1
        if price >= base_price * (1 + grid_pct / 100):
            return -1
        return 0

    try:
        klines = data_service.get_kline(code=code, period="daily")
    except Exception:
        return 0
    if not klines:
        return 0

    today = date.today().strftime("%Y-%m-%d")
    if _norm_date(klines[-1].get("date")) != today:
        if not price:
            return 0
        klines = klines + [{
            "date": today,
            "open": quote.get("open") or price,
            "close": price,
            "high": quote.get("high") or price,
            "low": quote.get("low") or price,
            "volume": quote.get("volume") or 0,
        }]

    try:
        engine = BacktestEngine(klines)
        sig = engine.generate_signals(strategy_type, params)
        return int(sig.iloc[-1])
    except Exception:
        return 0


# ── 账户 / 日志 / 快照 ──────────────────────────────

async def _get_account(db: AsyncSession, user_id: int) -> Account:
    result = await db.execute(select(Account).where(Account.user_id == user_id).limit(1))
    account = result.scalar_one_or_none()
    if not account:
        account = Account(user_id=user_id, name="默认账户", initial_capital=100000, available_cash=100000)
        db.add(account)
        await db.flush()
    return account


async def _add_log(db, user_id, code, name, strategy, trigger, action,
                   signal=None, price=None, quantity=None, result=None):
    db.add(AutoTradeLog(user_id=user_id, code=code, name=name, strategy=strategy,
                        trigger=trigger, signal=signal, action=action, price=price,
                        quantity=quantity, result=(result or "")[:255]))


async def _write_snapshot(db: AsyncSession, account: Account):
    today = date.today()
    pos_result = await db.execute(
        select(Position).where(Position.account_id == account.id, Position.quantity > 0))
    positions = pos_result.scalars().all()
    quotes_map = {}
    if positions:
        try:
            quotes = data_service.get_realtime_quotes(codes=[p.code for p in positions])
            quotes_map = {q["code"]: q for q in quotes}
        except Exception:
            pass
    mv = sum((quotes_map.get(p.code, {}).get("price") or 0) * p.quantity for p in positions)
    db.add(AssetSnapshot(account_id=account.id, total_asset=account.available_cash + mv,
                          snapshot_date=today))


# ── 程序化下单（复用与手动下单一致的规则） ──────────────────────────────

async def execute_buy(db: AsyncSession, account: Account, code: str, name: str,
                      price, quantity: int, strategy_name: str,
                      max_quantity: int = None) -> dict:
    """按指定价格与股数买入；max_quantity 用于限制买入后总持仓不超过该股数"""
    if not price or price <= 0:
        return {"action": "skip", "result": "无法获取行情"}
    quote = _get_quote(code)
    pre_close = quote.get("pre_close")
    if pre_close and pre_close > 0 and price >= pre_close * (1 + _limit_pct(code)):
        return {"action": "skip", "result": "涨停无法买入"}

    qty = int(quantity)
    if qty < 100 or qty % 100 != 0:
        return {"action": "skip", "result": "股数需为100的整数倍"}

    pos_result = await db.execute(select(Position).where(
        Position.account_id == account.id, Position.code == code))
    pos = pos_result.scalar_one_or_none()

    # 总持仓上限：买入后总股数不超过配置的买入股数
    if max_quantity is not None:
        current = pos.quantity if pos else 0
        allowed = int(max_quantity) - current
        if allowed <= 0:
            return {"action": "skip", "result": f"已达买入股数上限 {int(max_quantity)} 股"}
        qty = min(qty, allowed)
        qty = (qty // 100) * 100
        if qty < 100:
            return {"action": "skip", "result": f"已达买入股数上限 {int(max_quantity)} 股"}

    amt = price * qty
    fee = max(amt * settings.COMMISSION_RATE, settings.MIN_COMMISSION)
    total = amt + fee
    if account.available_cash < total:
        return {"action": "skip", "result": f"可用资金不足(需¥{total:,.2f})"}

    account.available_cash -= total
    if pos:
        total_cost = pos.avg_cost * pos.quantity + amt
        pos.quantity += qty
        pos.avg_cost = total_cost / pos.quantity
        pos.strategy_name = strategy_name
    else:
        db.add(Position(account_id=account.id, code=code, name=name,
                        quantity=qty, avg_cost=price, strategy_name=strategy_name))
    db.add(Transaction(account_id=account.id, code=code, name=name,
                       direction="buy", price=price, quantity=qty, amount=amt,
                       fee=fee, strategy_name=strategy_name))
    await _write_snapshot(db, account)
    await db.flush()
    return {"action": "buy", "price": price, "quantity": qty, "amount": amt, "fee": fee, "result": "买入成功"}


async def execute_sell_all(db: AsyncSession, account: Account, code: str, name: str,
                           price, strategy_name: str) -> dict:
    """卖出全部可卖持仓（遵守 T+1）"""
    pos_result = await db.execute(select(Position).where(
        Position.account_id == account.id, Position.code == code))
    pos = pos_result.scalar_one_or_none()
    if not pos or pos.quantity <= 0:
        return {"action": "skip", "result": "无持仓"}
    if not price or price <= 0:
        return {"action": "skip", "result": "无法获取行情"}

    quote = _get_quote(code)
    pre_close = quote.get("pre_close")
    if pre_close and pre_close > 0 and price <= pre_close * (1 - _limit_pct(code)):
        return {"action": "skip", "result": "跌停无法卖出"}

    # T+1：当日买入数量次日才能卖
    today_str = date.today().isoformat()
    today_buy_qty = await db.execute(
        select(func.coalesce(func.sum(Transaction.quantity), 0)).where(
            Transaction.account_id == account.id,
            Transaction.code == code,
            Transaction.direction == "buy",
            func.date(Transaction.traded_at, "localtime") == today_str))
    today_buy_qty = today_buy_qty.scalar() or 0
    sellable = pos.quantity - today_buy_qty
    if sellable <= 0:
        return {"action": "skip", "result": f"T+1规则：当日买入 {today_buy_qty} 股需次日卖出"}
    qty = sellable

    amt = price * qty
    fee = max(amt * settings.COMMISSION_RATE, settings.MIN_COMMISSION)
    stamp_tax = amt * settings.STAMP_TAX
    total_fee = fee + stamp_tax
    account.available_cash += amt - total_fee
    pos.quantity -= qty
    if pos.quantity == 0:
        await db.delete(pos)
    db.add(Transaction(account_id=account.id, code=code, name=name,
                       direction="sell", price=price, quantity=qty, amount=amt,
                       fee=total_fee, strategy_name=strategy_name))
    await _write_snapshot(db, account)
    await db.flush()
    return {"action": "sell", "price": price, "quantity": qty, "amount": amt, "fee": total_fee, "result": "卖出成功"}


# ── 每日调仓 ──────────────────────────────

async def _process_daily_item(db: AsyncSession, item: AutoTradeItem) -> dict:
    account = await _get_account(db, item.user_id)
    quote = _get_quote(item.code)
    price = quote.get("price")
    pos_result = await db.execute(select(Position).where(
        Position.account_id == account.id, Position.code == item.code))
    pos = pos_result.scalar_one_or_none()

    base_price = pos.avg_cost if (pos and pos.quantity > 0) else item.entry_price
    params = json.loads(item.strategy_params or "{}")
    sig = compute_latest_signal(item.code, item.strategy_type, params, base_price)

    if sig == -1 and pos and pos.quantity > 0:
        r = await execute_sell_all(db, account, item.code, item.name, price, item.strategy_name)
    elif sig == 1 and (not pos or pos.quantity <= 0):
        r = await execute_buy(db, account, item.code, item.name, price, item.quantity, item.strategy_name, max_quantity=item.quantity)
        if r["action"] == "buy":
            item.started_at = datetime.now()   # 刷新策略启动时间点
            item.entry_price = r["price"]
    else:
        r = {"action": "skip", "result": "无操作"}

    # 仅在实际成交（买入/卖出）时记录日志，避免盘中每分钟产生大量“无操作”记录
    if r["action"] in ("buy", "sell"):
        await _add_log(db, item.user_id, item.code, item.name, item.strategy_name,
                       "daily", r["action"], sig, price, r.get("quantity"), r["result"])
    return {"code": item.code, "signal": sig, **r}


async def run_daily_autotrade() -> list[dict]:
    """遍历所有用户的启用清单，执行每日调仓"""
    results = []
    async with async_session() as db:
        try:
            result = await db.execute(
                select(AutoTradeItem).where(AutoTradeItem.enabled.is_(True)).order_by(AutoTradeItem.id))
            items = result.scalars().all()
            for item in items:
                try:
                    results.append(await _process_daily_item(db, item))
                except Exception as e:
                    results.append({"code": item.code, "action": "error", "result": str(e)})
            await db.commit()
        except Exception:
            await db.rollback()
    return results


# ── 收盘后行情判断与策略切换 ──────────────────────────────

# 行情 regime_key → 内置预设策略（type/name/params，与 strategy.py 的 PRESETS 保持一致）
REGIME_STRATEGY_MAP: dict = {
    "uptrend": {
        "name": "单边上升策略", "type": "uptrend",
        "params": {"fast": 5, "trail_pct": 8},
    },
    "pullback": {
        "name": "上升回调策略", "type": "pullback",
        "params": {
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "boll_period": 20, "boll_std": 2.0, "kdj_n": 9,
            "kdj_k": 3, "kdj_d": 3, "rsi_period": 14,
            "rsi_low": 35, "rsi_high": 50, "j_turn": 40,
            "mb_low": 0.95, "mb_high": 1.10, "deviation_max": 0.20,
            "position_max": 0.85, "ma60_up_min": 10,
            "loss_stop_pct": 3, "early_days": 5, "hold_days": 15, "trail_pct": 8,
        },
    },
    "downtrend": {
        "name": "单边下跌策略", "type": "downtrend",
        "params": {
            "rsi_period": 14, "rsi_oversold": 20,
            "rsi_target": 50, "new_low_window": 20, "position_size": 0.30,
        },
    },
    "range": {
        "name": "震荡盘整策略", "type": "oscillation",
        "params": {
            "boll_period": 10, "boll_std": 2.0, "rsi_period": 14,
            "rsi_oversold": 30, "rsi_overbought": 70, "kdj_n": 9,
            "kdj_k": 3, "kdj_d": 3, "j_oversold": 0, "j_overbought": 100,
        },
    },
}


def _get_regime(code: str) -> dict:
    """获取个股当前行情阶段（复用个股分析的 analyze_market_regime，拼入今日收盘价）"""
    try:
        klines = data_service.get_kline(code=code, period="daily")
    except Exception:
        return {"regime": "分析失败", "regime_key": "error"}
    if not klines:
        return {"regime": "数据不足", "regime_key": "insufficient"}

    # 拼今日实时价作为最新一根 K 线（收盘后即近似当日收盘价）
    quote = _get_quote(code)
    price = quote.get("price")
    today = date.today().strftime("%Y-%m-%d")
    if price and _norm_date(klines[-1].get("date")) != today:
        klines = klines + [{
            "date": today,
            "open": quote.get("open") or price,
            "close": price,
            "high": quote.get("high") or price,
            "low": quote.get("low") or price,
            "volume": quote.get("volume") or 0,
        }]
    try:
        return analyze_market_regime(klines)
    except Exception:
        return {"regime": "分析失败", "regime_key": "error"}


async def _process_regime_item(db: AsyncSession, item: AutoTradeItem) -> dict:
    """判断单个标的行情，若映射到的策略与当前不同则切换"""
    regime = _get_regime(item.code)
    regime_key = regime.get("regime_key")
    preset = REGIME_STRATEGY_MAP.get(regime_key)
    if not preset:
        # 数据不足 / 分析失败 / 未知行情：保持原策略不变
        return {"code": item.code, "action": "skip",
                "result": f"行情判断失败({regime.get('regime')})，保持原策略"}

    if item.strategy_type == preset["type"]:
        return {"code": item.code, "action": "skip",
                "result": f"行情未变({regime.get('regime')})，保持 {item.strategy_name}"}

    old_name = item.strategy_name
    item.strategy_name = preset["name"]
    item.strategy_type = preset["type"]
    item.strategy_params = json.dumps(preset["params"], ensure_ascii=False)
    item.strategy_id = None  # 自动切换为内置预设，解除与原用户策略的绑定
    await _add_log(db, item.user_id, item.code, item.name, preset["name"],
                   "regime", "switch", None, None, None,
                   f"行情切换：{regime.get('regime')}，策略 {old_name} → {preset['name']}")
    return {"code": item.code, "action": "switch",
            "result": f"{old_name} → {preset['name']}"}


async def run_daily_regime_switch() -> list[dict]:
    """收盘后：遍历所有启用清单，判断行情并按需切换策略"""
    results = []
    async with async_session() as db:
        try:
            result = await db.execute(
                select(AutoTradeItem).where(AutoTradeItem.enabled.is_(True)).order_by(AutoTradeItem.id))
            items = result.scalars().all()
            for item in items:
                try:
                    results.append(await _process_regime_item(db, item))
                except Exception as e:
                    results.append({"code": item.code, "action": "error", "result": str(e)})
            await db.commit()
        except Exception:
            await db.rollback()
    return results


# ── 定时调度（开盘时间每分钟判断一次） ──────────────────────────────

_last_run_minute: str | None = None  # 形如 "2026-08-16 09:31"，避免同一分钟重复触发
_last_regime_date: str | None = None  # 已执行收盘后行情切换的日期，避免当日重复


def _is_market_time(now: datetime) -> bool:
    """A股连续竞价交易时段：9:30–11:30、13:00–15:00"""
    minutes = now.hour * 60 + now.minute
    return (570 <= minutes <= 690) or (780 <= minutes <= 900)


def _is_after_close(now: datetime) -> bool:
    """是否已过当日收盘（15:00 及以后）"""
    return now.hour * 60 + now.minute >= 900


async def scheduler_loop():
    """后台循环：盘中交易时段每分钟调仓一次；收盘后每日判断行情并切换策略"""
    global _last_run_minute, _last_regime_date
    while True:
        await asyncio.sleep(20)
        now = datetime.now()
        if not is_trading_day(now.date()):
            continue

        # 1) 盘中：交易时段内每分钟调仓一次
        if _is_market_time(now):
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            if _last_run_minute != minute_key:
                _last_run_minute = minute_key
                try:
                    await run_daily_autotrade()
                except Exception:
                    pass

        # 2) 收盘后：每个交易日判断一次行情并按需切换策略
        if _is_after_close(now):
            today = now.date().isoformat()
            if _last_regime_date != today:
                _last_regime_date = today
                try:
                    await run_daily_regime_switch()
                except Exception:
                    pass


