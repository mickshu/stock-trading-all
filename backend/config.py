from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    database_url: str = f"sqlite:///{Path(__file__).parent.parent / 'data' / 'stocktool.db'}"
    active_data_source: str = "akshare"
    tushare_token: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 容忍 .env 中 tradingagents 等其它模块的字段


settings = Settings()
