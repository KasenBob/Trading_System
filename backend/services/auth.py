"""认证服务：密码哈希 + token 管理 + 当前用户依赖"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Header
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.token import AuthToken

# token 有效期（天）
TOKEN_EXPIRE_DAYS = 30


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """哈希密码，返回 (salt, password_hash)"""
    if salt is None:
        salt = secrets.token_hex(32)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    ).hex()
    return salt, digest


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    """验证密码"""
    _, computed = hash_password(password, salt)
    return secrets.compare_digest(computed, password_hash)


def extract_token(authorization: Optional[str]) -> Optional[str]:
    """从 Authorization 头提取 token"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.replace("Bearer ", "").strip()
    return token or None


async def create_token(user_id: int, db: AsyncSession) -> str:
    """生成 token 并持久化到数据库（服务器重启后仍有效）"""
    token = uuid.uuid4().hex
    db.add(AuthToken(
        token=token,
        user_id=user_id,
        expires_at=datetime.now() + timedelta(days=TOKEN_EXPIRE_DAYS),
    ))
    await db.flush()
    return token


async def revoke_token(token: str, db: AsyncSession) -> None:
    """注销 token（从数据库删除）"""
    await db.execute(delete(AuthToken).where(AuthToken.token == token))


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Authorization: Bearer <token> 解析当前用户"""
    token = extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    result = await db.execute(select(AuthToken).where(AuthToken.token == token))
    token_row = result.scalar_one_or_none()
    if token_row is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if token_row.expires_at < datetime.now():
        await db.execute(delete(AuthToken).where(AuthToken.token == token))
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    user = await db.get(User, token_row.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
