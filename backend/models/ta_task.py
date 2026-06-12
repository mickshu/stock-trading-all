"""TradingAgents 异步分析任务 ORM。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from backend.database import Base


def _utcnow() -> datetime:
    """返回 naive UTC datetime，替代已弃用的 datetime.utcnow()。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TATask(Base):
    __tablename__ = "ta_tasks"

    id = Column(String(36), primary_key=True)  # uuid4
    ticker = Column(String(16), nullable=False, index=True)
    stock_name = Column(String(120), default="")
    trade_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    depth = Column(Integer, nullable=False, default=1)
    online_tools = Column(Boolean, nullable=False, default=True)
    # 单任务级覆盖：填了就用，空字符串=沿用全局 AI 配置。
    provider_override = Column(String(32), default="")
    model_override = Column(String(64), default="")
    # "trading" (多智能体) | "cli" (本地 CLI subprocess)
    analysis_tool = Column(String(16), nullable=False, default="trading")

    # pending | running | success | failed
    status = Column(String(16), nullable=False, default="pending", index=True)
    decision = Column(String(16), default="")  # BUY/SELL/HOLD
    decision_raw = Column(Text, default="")
    report_filename = Column(String(255), default="")  # 相对 data/reports/ 的文件名
    report_md = Column(Text, default="")  # 也存一份方便前端直接展示
    error = Column(Text, default="")

    created_at = Column(DateTime, default=_utcnow, index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_sec = Column(Float)
