"""自选股 API（按用户隔离）"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models.watchlist import Watchlist
from models.user import User
from services.auth import get_current_user

router = APIRouter(prefix="/api/watchlist", tags=["自选股"])


class WatchlistAdd(BaseModel):
    code: str
    name: str
    type: str = "stock"  # stock / etf
    group: str = "默认"


class WatchlistBatchAdd(BaseModel):
    items: list[WatchlistAdd]


class ReorderItem(BaseModel):
    id: int
    sort_order: int


@router.get("")
async def list_watchlist(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """获取自选股列表（按 sort_order 排序）"""
    result = await db.execute(
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.sort_order, Watchlist.created_at)
    )
    items = result.scalars().all()
    return {
        "code": 0,
        "data": [
            {
                "id": it.id,
                "code": it.code,
                "name": it.name,
                "type": it.type,
                "group": it.group,
                "sort_order": it.sort_order,
                "created_at": str(it.created_at) if it.created_at else None,
            }
            for it in items
        ],
        "count": len(items),
    }


@router.post("")
async def add_watchlist(item: WatchlistAdd, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """添加单只自选股"""
    existing = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.code == item.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"{item.code} 已在自选中")

    max_order = await db.execute(
        select(func.max(Watchlist.sort_order)).where(Watchlist.user_id == user.id)
    )
    max_val = max_order.scalar() or 0

    wl = Watchlist(
        user_id=user.id, code=item.code, name=item.name,
        type=item.type, group=item.group, sort_order=max_val + 1,
    )
    db.add(wl)
    await db.flush()
    return {"code": 0, "data": {"id": wl.id}, "message": "已添加"}


@router.post("/batch")
async def batch_add(body: WatchlistBatchAdd, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """批量添加"""
    added = 0
    for item in body.items:
        existing = await db.execute(
            select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.code == item.code)
        )
        if existing.scalar_one_or_none():
            continue
        max_order = await db.execute(
            select(func.max(Watchlist.sort_order)).where(Watchlist.user_id == user.id)
        )
        max_val = max_order.scalar() or 0
        wl = Watchlist(
            user_id=user.id, code=item.code, name=item.name, type=item.type,
            group=item.group, sort_order=max_val + 1,
        )
        db.add(wl)
        added += 1
    await db.flush()
    return {"code": 0, "message": f"已添加 {added} 只"}


@router.delete("/{wl_id}")
async def remove_watchlist(wl_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """删除自选股"""
    result = await db.execute(
        delete(Watchlist).where(Watchlist.id == wl_id, Watchlist.user_id == user.id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="未找到")
    return {"code": 0, "message": "已删除"}


@router.put("/reorder")
async def reorder(body: list[ReorderItem], user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """拖拽排序"""
    for item in body:
        await db.execute(
            update(Watchlist)
            .where(Watchlist.id == item.id, Watchlist.user_id == user.id)
            .values(sort_order=item.sort_order)
        )
    await db.flush()
    return {"code": 0, "message": "已更新排序"}


@router.put("/{wl_id}/group")
async def set_group(wl_id: int, group: str = "默认", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """修改分组"""
    result = await db.execute(
        update(Watchlist)
        .where(Watchlist.id == wl_id, Watchlist.user_id == user.id)
        .values(group=group)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="未找到")
    await db.flush()
    return {"code": 0, "message": "已更新分组"}

