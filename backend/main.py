"""FastAPI 应用入口"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
from routers import market_data, stock_query, watchlist, simulation, strategy, auth, autotrade


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化数据库 + 启动自动交易调度"""
    await init_db()
    from services import autotrade_service
    scheduler_task = asyncio.create_task(autotrade_service.scheduler_loop())
    yield
    scheduler_task.cancel()


app = FastAPI(
    title="A股交易系统",
    description="本地量化交易系统 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(market_data.router)
app.include_router(stock_query.router)
app.include_router(auth.router)
app.include_router(watchlist.router)
app.include_router(simulation.router)
app.include_router(strategy.router)
app.include_router(autotrade.router)


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}
