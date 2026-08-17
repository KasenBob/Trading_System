"""应用配置"""

from datetime import datetime, timezone, timedelta

from pydantic_settings import BaseSettings


CN_TZ = timezone(timedelta(hours=8))  # 北京时间 Asia/Shanghai（无夏令时，固定 UTC+8）


def utc_now() -> datetime:
    """返回 naive 的 UTC 当前时间（与 SQLite CURRENT_TIMESTAMP 一致）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cn_time_str(dt) -> str:
    """把按 UTC 存储的 naive datetime 转成北京时间字符串，供前端展示"""
    if not dt:
        return ""
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./trading.db"

    # 服务
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = True

    # 交易规则
    STAMP_TAX: float = 0.001          # 印花税（卖出单向）
    COMMISSION_RATE: float = 0.00025  # 佣金 万2.5
    TRANSFER_FEE: float = 0.00001     # 过户费 万0.1
    MIN_COMMISSION: float = 5.0       # 最低佣金

    # 数据源
    MARKET_DATA_SOURCE: str = "akshare"

    # DeepSeek AI
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
