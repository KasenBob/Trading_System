"""策略模型：策略、回测记录、回测交易明细"""

from datetime import datetime, date

from sqlalchemy import String, Integer, Float, Date, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Strategy(Base):
    __tablename__ = "strategy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, comment="用户ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="策略名称")
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="策略类型")
    params: Mapped[str] = mapped_column(Text, nullable=False, default="{}", comment="策略参数JSON")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


class Backtest(Base):
    __tablename__ = "backtest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategy.id"), nullable=False, comment="策略ID")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="回测标的")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="回测起始日")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="回测结束日")
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=100000, comment="初始资金")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", comment="pending / running / completed / failed")
    result: Mapped[str] = mapped_column(Text, nullable=True, comment="回测结果JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


class BacktestTrade(Base):
    __tablename__ = "backtest_trade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_id: Mapped[int] = mapped_column(Integer, ForeignKey("backtest.id"), nullable=False, comment="回测ID")
    date: Mapped[date] = mapped_column(Date, nullable=False, comment="交易日期")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="标的代码")
    direction: Mapped[str] = mapped_column(String(4), nullable=False, comment="buy / sell")
    price: Mapped[float] = mapped_column(Float, nullable=False, comment="交易价格")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="交易数量")
    reason: Mapped[str] = mapped_column(String(255), nullable=True, comment="交易原因")
