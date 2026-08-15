"""自动交易模型：股票清单、执行日志"""

from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AutoTradeItem(Base):
    __tablename__ = "auto_trade_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, comment="用户ID")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="股票代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="股票名称")
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategy.id"), nullable=True, comment="绑定的策略ID")
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="策略名称快照")
    strategy_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="策略类型快照")
    strategy_params: Mapped[str] = mapped_column(Text, nullable=False, default="{}", comment="策略参数JSON快照")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=100, comment="买入股数")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="策略启动时间=买入时刻")
    entry_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="买入成交价")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="单只开关")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


class AutoTradeLog(Base):
    __tablename__ = "auto_trade_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, comment="用户ID")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="股票代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="股票名称")
    strategy: Mapped[str] = mapped_column(String(100), nullable=True, comment="策略名称")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, comment="manual_add/manual_remove/daily/reset")
    signal: Mapped[int] = mapped_column(Integer, nullable=True, comment="信号值 1/-1/0")
    action: Mapped[str] = mapped_column(String(10), nullable=False, comment="buy/sell/skip")
    price: Mapped[float] = mapped_column(Float, nullable=True, comment="成交价")
    quantity: Mapped[int] = mapped_column(Integer, nullable=True, comment="成交数量")
    result: Mapped[str] = mapped_column(String(255), nullable=True, comment="结果/原因")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="时间")
