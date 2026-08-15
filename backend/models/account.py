"""模拟交易模型：账户、持仓、成交记录、资产快照"""

from datetime import datetime, date

from sqlalchemy import String, Integer, Float, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, comment="用户ID")
    name: Mapped[str] = mapped_column(String(50), nullable=False, default="默认账户", comment="账户名称")
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=100000, comment="初始资金")
    available_cash: Mapped[float] = mapped_column(Float, nullable=False, default=100000, comment="可用资金")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


class Position(Base):
    __tablename__ = "position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"), nullable=False, comment="账户ID")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="股票代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="股票名称")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="持仓数量")
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="持仓成本")
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="使用的策略名称")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class Transaction(Base):
    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"), nullable=False, comment="账户ID")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="股票代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="股票名称")
    direction: Mapped[str] = mapped_column(String(4), nullable=False, comment="buy / sell")
    price: Mapped[float] = mapped_column(Float, nullable=False, comment="成交价格")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="成交数量")
    amount: Mapped[float] = mapped_column(Float, nullable=False, comment="成交金额")
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="手续费")
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="使用的策略名称")
    traded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="成交时间")


class AssetSnapshot(Base):
    __tablename__ = "asset_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"), nullable=False, comment="账户ID")
    total_asset: Mapped[float] = mapped_column(Float, nullable=False, comment="总资产")
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
