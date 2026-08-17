"""SQLite 数据库连接管理"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """获取数据库会话（FastAPI 依赖注入）"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def _ensure_column(conn, table: str, column: str, ddl_type: str) -> None:
    """轻量迁移：如果表中缺少某列则 ALTER TABLE 补充（兼容旧库）"""
    from sqlalchemy import text

    rows = await conn.execute(text(f'PRAGMA table_info("{table}")'))
    existing = [r[1] for r in rows]
    if column not in existing:
        await conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl_type}'))


async def init_db():
    """初始化数据库表"""
    from sqlalchemy import text
    from models import user, token, watchlist, account, strategy, autotrade  # noqa: F401 确保模型注册

    async with engine.begin() as conn:
        # 旧版 auto_trade_item 用 amount 列(NOT NULL)，模型已改为 quantity；旧结构需重建
        rows = await conn.execute(text('PRAGMA table_info("auto_trade_item")'))
        if any(r[1] == "amount" for r in rows):
            await conn.execute(text('DROP TABLE "auto_trade_item"'))
        await conn.run_sync(Base.metadata.create_all)
        # 补充历史版本缺失的列（策略标记）
        await _ensure_column(conn, "position", "strategy_name", "VARCHAR(100)")
        await _ensure_column(conn, "transaction", "strategy_name", "VARCHAR(100)")
        await _ensure_column(conn, "auto_trade_item", "quantity", "INTEGER DEFAULT 100")
        await _ensure_column(conn, "auto_trade_log", "reason", "TEXT")
