"""应用配置"""

from pydantic_settings import BaseSettings


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
