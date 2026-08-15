"""用户模型"""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="密码哈希")
    salt: Mapped[str] = mapped_column(String(64), nullable=False, comment="盐")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="注册时间")
