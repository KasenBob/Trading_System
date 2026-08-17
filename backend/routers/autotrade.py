"""自动交易 API"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models.account import Account, Position, Transaction, AssetSnapshot
from models.autotrade import AutoTradeItem, AutoTradeLog
from models.strategy import Strategy
from models.user import User
from services.auth import get_current_user
from services import autotrade_service as ats

router = APIRouter(prefix="/api/auto-trade", tags=["自动交易"])


class AddItemRequest(BaseModel):
    code: str
    name: str
    strategy_id: int
    price: float
    quantity: int


class UpdateItemRequest(BaseModel):
    quantity: int | None = None
    strategy_id: int | None = None
    enabled: bool | None = None


class ResetRequest(BaseModel):
    initial_capital: float | None = None


def _item_dict(i: AutoTradeItem) -> dict:
    return {
        "id": i.id, "code": i.code, "name": i.name,
        "strategy_id": i.strategy_id, "strategy_name": i.strategy_name,
        "quantity": i.quantity, "started_at": str(i.started_at), "entry_price": i.entry_price,
        "enabled": i.enabled,
    }


async def _get_item(db, user_id, iid) -> AutoTradeItem:
    result = await db.execute(select(AutoTradeItem).where(
        AutoTradeItem.id == iid, AutoTradeItem.user_id == user_id))
    return result.scalar_one_or_none()


@router.get("")
async def list_items(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AutoTradeItem).where(
        AutoTradeItem.user_id == user.id).order_by(AutoTradeItem.id))
    items = result.scalars().all()

    # 当前持仓股数：从持仓表实时映射，保证买入/卖出后“股数”及时更新
    account = (await db.execute(select(Account).where(
        Account.user_id == user.id).limit(1))).scalar_one_or_none()
    pos_map: dict[str, int] = {}
    if account:
        positions = (await db.execute(select(Position).where(
            Position.account_id == account.id))).scalars().all()
        pos_map = {p.code: p.quantity for p in positions}

    data = []
    for i in items:
        d = _item_dict(i)
        d["position_quantity"] = pos_map.get(i.code, 0)
        data.append(d)
    return {"code": 0, "data": data}


@router.post("/item")
async def add_item(body: AddItemRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.price <= 0:
        raise HTTPException(status_code=400, detail="买入价格必须大于0")
    if body.quantity < 100 or body.quantity % 100 != 0:
        raise HTTPException(status_code=400, detail="股数必须为100的整数倍")
    st = (await db.execute(select(Strategy).where(
        Strategy.id == body.strategy_id, Strategy.user_id == user.id))).scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=400, detail="策略不存在")
    dup = (await db.execute(select(AutoTradeItem).where(
        AutoTradeItem.user_id == user.id, AutoTradeItem.code == body.code))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=400, detail="该股票已在自动交易清单中")

    account = await ats._get_account(db, user.id)
    r = await ats.execute_buy(db, account, body.code, body.name, body.price, body.quantity, st.name, max_quantity=body.quantity)
    if r["action"] != "buy":
        raise HTTPException(status_code=400, detail=r["result"])

    item = AutoTradeItem(user_id=user.id, code=body.code, name=body.name,
                         strategy_id=st.id, strategy_name=st.name, strategy_type=st.type,
                         strategy_params=st.params, quantity=body.quantity, entry_price=body.price)
    db.add(item)
    await db.flush()
    await ats._add_log(db, user.id, body.code, body.name, st.name, "manual_add",
                       "buy", None, body.price, r["quantity"], r["result"])
    await db.flush()
    return {"code": 0, "data": _item_dict(item), "message": f"已买入 {body.name}"}


@router.delete("/item/{iid}")
async def remove_item(iid: int, price: float, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await _get_item(db, user.id, iid)
    if not item:
        raise HTTPException(status_code=404, detail="清单项不存在")
    if price <= 0:
        raise HTTPException(status_code=400, detail="卖出价格必须大于0")
    account = await ats._get_account(db, user.id)
    r = await ats.execute_sell_all(db, account, item.code, item.name, price, item.strategy_name)
    await ats._add_log(db, user.id, item.code, item.name, item.strategy_name, "manual_remove",
                       r["action"], None, price, r.get("quantity"), r["result"])
    pos = (await db.execute(select(Position).where(
        Position.account_id == account.id, Position.code == item.code))).scalar_one_or_none()
    if not pos or pos.quantity <= 0:
        await db.delete(item)
        await db.flush()
        return {"code": 0, "message": "已卖出并移除"}
    await db.flush()
    return {"code": 0, "message": f"已卖出可卖部分，剩余 {pos.quantity} 股受T+1限制，次日可再删除"}


@router.put("/item/{iid}")
async def update_item(iid: int, body: UpdateItemRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await _get_item(db, user.id, iid)
    if not item:
        raise HTTPException(status_code=404, detail="清单项不存在")
    if body.enabled is not None:
        item.enabled = body.enabled
    if body.quantity is not None:
        if body.quantity < 100 or body.quantity % 100 != 0:
            raise HTTPException(status_code=400, detail="股数必须为100的整数倍")
        item.quantity = body.quantity
    if body.strategy_id is not None:
        st = (await db.execute(select(Strategy).where(
            Strategy.id == body.strategy_id, Strategy.user_id == user.id))).scalar_one_or_none()
        if not st:
            raise HTTPException(status_code=400, detail="策略不存在")
        item.strategy_id = st.id
        item.strategy_name = st.name
        item.strategy_type = st.type
        item.strategy_params = st.params
    await db.flush()
    return {"code": 0, "data": _item_dict(item), "message": "已更新"}


@router.post("/run")
async def manual_run(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AutoTradeItem).where(
        AutoTradeItem.user_id == user.id, AutoTradeItem.enabled.is_(True)).order_by(AutoTradeItem.id))
    items = result.scalars().all()
    results = []
    for item in items:
        try:
            results.append(await ats._process_daily_item(db, item))
        except Exception as e:
            results.append({"code": item.code, "action": "error", "result": str(e)})
    await db.flush()
    return {"code": 0, "data": results, "count": len(results)}


@router.post("/reset")
async def reset(body: ResetRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await ats._get_account(db, user.id)
    if body.initial_capital and body.initial_capital > 0:
        account.initial_capital = body.initial_capital
    account.available_cash = account.initial_capital
    await db.execute(delete(Position).where(Position.account_id == account.id))
    await db.execute(delete(Transaction).where(Transaction.account_id == account.id))
    await db.execute(delete(AssetSnapshot).where(AssetSnapshot.account_id == account.id))
    await db.execute(delete(AutoTradeItem).where(AutoTradeItem.user_id == user.id))
    await db.flush()
    return {"code": 0, "message": f"已重置，初始资金 ¥{account.initial_capital:,.0f}"}


@router.get("/logs")
async def list_logs(limit: int = 100, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AutoTradeLog).where(
        AutoTradeLog.user_id == user.id).order_by(AutoTradeLog.id.desc()).limit(limit))
    logs = result.scalars().all()
    return {"code": 0, "data": [{
        "id": l.id, "code": l.code, "name": l.name, "strategy": l.strategy,
        "trigger": l.trigger, "signal": l.signal, "action": l.action,
        "price": l.price, "quantity": l.quantity, "result": l.result,
        "created_at": str(l.created_at),
    } for l in logs], "count": len(logs)}


@router.delete("/logs")
async def clear_logs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """清空当前用户的自动交易执行日志"""
    await db.execute(delete(AutoTradeLog).where(AutoTradeLog.user_id == user.id))
    await db.flush()
    return {"code": 0, "message": "日志已清除"}

