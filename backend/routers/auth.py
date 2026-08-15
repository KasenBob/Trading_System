"""用户认证 API"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models.user import User
from services.auth import (
    hash_password,
    verify_password,
    create_token,
    revoke_token,
    extract_token,
    get_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["用户认证"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/register")
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册"""
    username = body.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少2个字符")
    if len(body.password) < 4:
        raise HTTPException(status_code=400, detail="密码至少4个字符")

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    salt, password_hash = hash_password(body.password)
    user = User(username=username, password_hash=password_hash, salt=salt)
    db.add(user)
    await db.flush()

    token = await create_token(user.id, db)
    return {"code": 0, "token": token, "user": {"id": user.id, "username": user.username}}


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录"""
    result = await db.execute(select(User).where(User.username == body.username.strip()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.salt, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = await create_token(user.id, db)
    return {"code": 0, "token": token, "user": {"id": user.id, "username": user.username}}


@router.post("/logout")
async def logout(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """注销：删除服务端持久化的 token"""
    token = extract_token(authorization)
    if token:
        await revoke_token(token, db)
    return {"code": 0, "message": "已注销"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改密码"""
    if not verify_password(body.old_password, user.salt, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="新密码至少4个字符")

    salt, password_hash = hash_password(body.new_password)
    user.salt = salt
    user.password_hash = password_hash
    await db.flush()
    return {"code": 0, "message": "密码修改成功"}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return {"code": 0, "user": {"id": user.id, "username": user.username}}
