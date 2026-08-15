"""自选股模型"""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, comment="用户ID")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="股票/ETF代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="名称")
    type: Mapped[str] = mapped_column(String(10), nullable=False, default="stock", comment="stock / etf")
    group: Mapped[str] = mapped_column(String(50), nullable=False, default="默认", comment="分组名称")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序序号")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="添加时间")
