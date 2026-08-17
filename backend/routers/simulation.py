"""模拟交易 API（按用户隔离）"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, desc, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models.account import Account, Position, Transaction, AssetSnapshot
from models.user import User
from services.auth import get_current_user
from services.akshare_service import data_service
from config import settings, cn_time_str

router = APIRouter(prefix="/api/trade", tags=["模拟交易"])


class OrderRequest(BaseModel):
    code: str
    name: str
    direction: str  # buy / sell
    price: Optional[float] = None  # None = 市价
    quantity: int
    strategy: Optional[str] = None  # 使用的策略名称（标记用）


class ResetRequest(BaseModel):
    initial_capital: Optional[float] = None  # None = 保持当前初始资金


async def _get_or_create_account(db: AsyncSession, user_id: int) -> Account:
    """获取或创建当前用户的账户"""
    result = await db.execute(
        select(Account).where(Account.user_id == user_id).limit(1)
    )
    account = result.scalar_one_or_none()
    if not account:
        account = Account(user_id=user_id, name="默认账户", initial_capital=100000, available_cash=100000)
        db.add(account)
        await db.flush()
    return account


# ── 账户 ──────────────────────────────

@router.get("/account")
async def get_account(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _get_or_create_account(db, user.id)
    return {
        "code": 0, "data": {
            "id": account.id, "name": account.name,
            "initial_capital": account.initial_capital,
            "available_cash": account.available_cash,
        }}


@router.post("/account/reset")
async def reset_account(body: ResetRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _get_or_create_account(db, user.id)
    if body.initial_capital and body.initial_capital > 0:
        account.initial_capital = body.initial_capital
    account.available_cash = account.initial_capital
    await db.execute(delete(Position).where(Position.account_id == account.id))
    await db.execute(delete(Transaction).where(Transaction.account_id == account.id))
    await db.execute(delete(AssetSnapshot).where(AssetSnapshot.account_id == account.id))
    await db.flush()
    return {"code": 0, "message": f"账户已重置，初始资金 ¥{account.initial_capital:,.0f}"}


# ── 下单 ──────────────────────────────

@router.post("/order")
async def place_order(order: OrderRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _get_or_create_account(db, user.id)

    quotes = data_service.get_realtime_quotes(codes=[order.code])
    if not quotes:
        raise HTTPException(status_code=400, detail="无法获取行情")
    quote = quotes[0]
    price = order.price if order.price else quote.get("price")
    if not price or price <= 0:
        raise HTTPException(status_code=400, detail="无效价格")

    # 涨跌停校验
    pre_close = quote.get("pre_close")
    if pre_close and pre_close > 0:
        limit_pct = 0.2 if order.code.startswith(("3", "68")) else 0.1
        limit_up = pre_close * (1 + limit_pct)
        limit_down = pre_close * (1 - limit_pct)
        if price > limit_up or price < limit_down:
            raise HTTPException(status_code=400, detail=f"超出涨跌停范围 ({limit_down:.2f}~{limit_up:.2f})")

    amount = price * order.quantity
    fee = max(amount * settings.COMMISSION_RATE, settings.MIN_COMMISSION)

    if order.direction == "buy":
        total = amount + fee
        if account.available_cash < total:
            raise HTTPException(status_code=400, detail=f"可用资金不足 (需 {total:.2f})")
        account.available_cash -= total
        pos_result = await db.execute(
            select(Position).where(Position.account_id == account.id, Position.code == order.code))
        pos = pos_result.scalar_one_or_none()
        if pos:
            total_cost = pos.avg_cost * pos.quantity + amount
            pos.quantity += order.quantity
            pos.avg_cost = total_cost / pos.quantity
            if order.strategy:
                pos.strategy_name = order.strategy
        else:
            pos = Position(account_id=account.id, code=order.code, name=order.name,
                           quantity=order.quantity, avg_cost=price,
                           strategy_name=order.strategy or None)
            db.add(pos)
    else:
        pos_result = await db.execute(
            select(Position).where(Position.account_id == account.id, Position.code == order.code))
        pos = pos_result.scalar_one_or_none()
        if not pos or pos.quantity < order.quantity:
            raise HTTPException(status_code=400, detail="持仓不足")

        # T+1 规则：当日买入的数量需次日才能卖出（之前持仓可正常卖出）
        today_str = date.today().isoformat()
        today_buy_qty = await db.execute(
            select(func.coalesce(func.sum(Transaction.quantity), 0))
            .where(
                Transaction.account_id == account.id,
                Transaction.code == order.code,
                Transaction.direction == "buy",
                func.date(Transaction.traded_at, "localtime") == today_str,
            )
        )
        today_buy_qty = today_buy_qty.scalar() or 0
        sellable = pos.quantity - today_buy_qty
        if order.quantity > sellable:
            raise HTTPException(
                status_code=400,
                detail=f"T+1 规则：当日买入 {today_buy_qty} 股需次日才能卖出，今日最多可卖 {sellable} 股",
            )

        stamp_tax = amount * settings.STAMP_TAX
        total_fee = fee + stamp_tax
        account.available_cash += amount - total_fee
        pos.quantity -= order.quantity
        if pos.quantity == 0:
            await db.delete(pos)

    txn = Transaction(account_id=account.id, code=order.code, name=order.name,
                      direction=order.direction, price=price, quantity=order.quantity,
                      amount=amount, fee=fee, strategy_name=order.strategy or None)
    db.add(txn)

    # 快照
    pos_list = await _get_positions_value(db, account.id)
    mv = sum(p["market_value"] for p in pos_list)
    db.add(AssetSnapshot(account_id=account.id, total_asset=account.available_cash + mv,
                          snapshot_date=date.today()))
    await db.flush()
    return {"code": 0, "data": {"price": price, "amount": amount, "fee": fee},
            "message": f"{'买入' if order.direction == 'buy' else '卖出'}成功"}

# ── 持仓辅助 ──────────────────────────

async def _get_positions_value(db: AsyncSession, account_id: int) -> list[dict]:
    result = await db.execute(select(Position).where(Position.account_id == account_id, Position.quantity > 0))
    positions = result.scalars().all()
    if not positions: return []
    codes = [p.code for p in positions]
    quotes_map = {}
    try:
        quotes = data_service.get_realtime_quotes(codes=codes)
        quotes_map = {q["code"]: q for q in quotes}
    except Exception: pass
    return [{
        "id": p.id, "code": p.code, "name": p.name,
        "quantity": p.quantity, "avg_cost": p.avg_cost,
        "strategy_name": p.strategy_name,
        "price": quotes_map.get(p.code, {}).get("price"),
        "market_value": (quotes_map.get(p.code, {}).get("price") or 0) * p.quantity,
        "pnl": ((quotes_map.get(p.code, {}).get("price") or 0) - p.avg_cost) * p.quantity,
        "pnl_pct": ((quotes_map.get(p.code, {}).get("price") or 0) / p.avg_cost - 1) * 100 if p.avg_cost else 0,
    } for p in positions]


@router.get("/positions")
async def get_positions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _get_or_create_account(db, user.id)
    positions = await _get_positions_value(db, account.id)
    market_value = sum(p["market_value"] for p in positions)
    total_asset = account.available_cash + market_value
    total_pnl = total_asset - account.initial_capital
    return {"code": 0, "data": {
        "available_cash": account.available_cash, "market_value": market_value,
        "total_asset": total_asset, "initial_capital": account.initial_capital,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl / account.initial_capital * 100 if account.initial_capital else 0,
        "positions": positions,
    }}


@router.get("/transactions")
async def get_transactions(limit: int = 50, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _get_or_create_account(db, user.id)
    txn_result = await db.execute(
        select(Transaction).where(Transaction.account_id == account.id)
        .order_by(desc(Transaction.traded_at)).limit(limit))
    txns = txn_result.scalars().all()
    return {"code": 0, "data": [{
        "id": t.id, "code": t.code, "name": t.name, "direction": t.direction,
        "price": t.price, "quantity": t.quantity, "amount": t.amount,
        "fee": t.fee, "strategy_name": t.strategy_name, "traded_at": cn_time_str(t.traded_at),
    } for t in txns], "count": len(txns)}


@router.get("/snapshots")
async def get_snapshots(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _get_or_create_account(db, user.id)
    snap_result = await db.execute(
        select(AssetSnapshot).where(AssetSnapshot.account_id == account.id)
        .order_by(AssetSnapshot.snapshot_date))
    snaps = snap_result.scalars().all()
    return {"code": 0, "data": [
        {"date": str(s.snapshot_date), "total_asset": s.total_asset} for s in snaps
    ], "count": len(snaps)}


@router.get("/stats")
async def get_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """收益统计 + 日盈亏日历数据（每日快照聚合）"""
    account = await _get_or_create_account(db, user.id)

    # 确保今天有快照（用当前总资产），让日历/收益反映最新状态
    today = date.today()
    today_cnt = await db.execute(
        select(func.count()).select_from(AssetSnapshot)
        .where(AssetSnapshot.account_id == account.id, AssetSnapshot.snapshot_date == today))
    if (today_cnt.scalar() or 0) == 0:
        pos_list = await _get_positions_value(db, account.id)
        mv = sum(p["market_value"] for p in pos_list)
        db.add(AssetSnapshot(account_id=account.id,
                             total_asset=account.available_cash + mv,
                             snapshot_date=today))
        await db.commit()

    # 按天聚合：同一天多次下单取最后一条快照
    snap_result = await db.execute(
        select(AssetSnapshot).where(AssetSnapshot.account_id == account.id)
        .order_by(AssetSnapshot.snapshot_date, AssetSnapshot.id))
    snaps = snap_result.scalars().all()
    by_day: dict[date, float] = {}
    for s in snaps:
        by_day[s.snapshot_date] = s.total_asset
    days = sorted(by_day.keys())
    assets = [by_day[d] for d in days]

    n = len(days)
    init_cap = account.initial_capital or 1.0

    # 每日盈亏 + 收益率（相对前一日）
    calendar_data: list[dict] = []
    rets: list[float] = []
    for i in range(1, n):
        prev, cur = assets[i - 1], assets[i]
        pnl = cur - prev
        r = (cur / prev - 1) if prev else 0.0
        rets.append(r)
        calendar_data.append({
            "date": days[i].isoformat(),
            "pnl": round(pnl, 2),
            "pct": round(r * 100, 4),
        })

    total_asset_now = assets[-1] if n else init_cap
    total_return = (total_asset_now / init_cap - 1) * 100
    span_days = max((days[-1] - days[0]).days, 1) if n >= 2 else 1
    annual_return = ((1 + total_return / 100) ** (365 / span_days) - 1) * 100 if n >= 2 else 0.0

    daily_return = rets[-1] * 100 if rets else 0.0

    def _period_return(start: date) -> float:
        idx = next((i for i, d in enumerate(days) if d >= start), None)
        if idx is None or idx >= n - 1:
            return 0.0
        return (assets[-1] / assets[idx] - 1) * 100

    weekly_return = _period_return(today - timedelta(days=today.weekday()))
    monthly_return = _period_return(today.replace(day=1))

    # 最大回撤
    peak = assets[0] if n else 0.0
    max_dd = 0.0
    for a in assets:
        if a > peak:
            peak = a
        dd = (a / peak - 1) if peak else 0.0
        max_dd = min(max_dd, dd)
    max_drawdown = max_dd * 100

    # 夏普比率（年化，无风险利率 2%）
    sharpe = 0.0
    if len(rets) > 1:
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        std = var ** 0.5
        ann_vol = std * (252 ** 0.5)
        ann_ret = annual_return / 100
        sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0.0

    # 胜率（盈利天数占比）
    win_days = sum(1 for r in rets if r > 0)
    win_rate = (win_days / len(rets) * 100) if rets else 0.0

    return {"code": 0, "data": {
        "stats": {
            "total_return": round(total_return, 2),
            "annual_return": round(annual_return, 2),
            "daily_return": round(daily_return, 4),
            "weekly_return": round(weekly_return, 4),
            "monthly_return": round(monthly_return, 4),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2),
            "win_rate": round(win_rate, 1),
        },
        "calendar": calendar_data,
        "days": n,
    }}

