"""AI 分析报告 ORM。

每条记录对应一次 AI 分析的元数据，markdown 正文落在 data/reports/<filename>。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)

from backend.database import Base


class AIReport(Base):
    __tablename__ = "ai_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # single | multi | sector | market | pick
    scope = Column(String(16), nullable=False, index=True)
    # JSON：single=[{code,name}]，sector=[{sector}]，market=[{index,name}]…
    targets = Column(JSON, nullable=False)
    dimensions = Column(JSON, nullable=False, default=list)
    agent = Column(String(32), nullable=False)
    prompt = Column(Text)
    filename = Column(String(255), nullable=False, unique=True)
    output_chars = Column(Integer, default=0)
    duration = Column(Float, default=0.0)
    exit_code = Column(Integer)
    ok = Column(Boolean, default=False)
    starred = Column(Boolean, default=False, index=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
