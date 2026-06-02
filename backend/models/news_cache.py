"""自选股资讯聚合结果的本地 SQLite 持久化缓存。

stale-while-revalidate：handler 立即返回 cached 数据 + stale 标记，
后台异步刷新；前端拿到 stale=true 时显示「更新中」并在数秒后轮询。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.database import Base


class NewsCache(Base):
    __tablename__ = "news_cache"

    # scope_key = f"{sorted_codes}|{time_range}|{sorted_sources}"，
    # 与 services.news_aggregator 内部 cache_key 保持一致。
    scope_key = Column(String(500), primary_key=True)
    payload_json = Column(Text, nullable=False)
    items_count = Column(Integer, default=0)
    refreshed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
