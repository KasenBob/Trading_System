"""认证 token 模型（持久化到数据库，服务器重启不失效）"""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AuthToken(Base):
    __tablename__ = "auth_token"

    token: Mapped[str] = mapped_column(String(64), primary_key=True, comment="token")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, comment="用户ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="过期时间")
