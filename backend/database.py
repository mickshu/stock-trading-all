from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.config import settings

engine = create_engine(settings.database_url, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_sqlite():
    """对既有 SQLite 库做轻量 schema 升级，避免新增列导致旧库不可用。"""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(watchlist)")).fetchall()
        col_names = {row[1] for row in cols}
        if cols and "group_id" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN group_id INTEGER"))
        if cols and "tags" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN tags VARCHAR(120) DEFAULT ''"))
        if cols and "target_price" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN target_price FLOAT"))
        if cols and "alert_diff_pct" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN alert_diff_pct FLOAT"))
        if cols and "security_type" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN security_type VARCHAR(10) DEFAULT 'stock'"))
        opp = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_opportunity'"
        )).fetchone()
        if not opp:
            conn.execute(text(
                "CREATE TABLE daily_opportunity (trade_date DATE PRIMARY KEY, payload TEXT NOT NULL, created_at DATETIME)"
            ))
        ta_cols = conn.execute(text("PRAGMA table_info(ta_tasks)")).fetchall()
        ta_col_names = {row[1] for row in ta_cols}
        if ta_cols and "provider_override" not in ta_col_names:
            conn.execute(text("ALTER TABLE ta_tasks ADD COLUMN provider_override VARCHAR(32) DEFAULT ''"))
        if ta_cols and "model_override" not in ta_col_names:
            conn.execute(text("ALTER TABLE ta_tasks ADD COLUMN model_override VARCHAR(64) DEFAULT ''"))
        if ta_cols and "analysis_tool" not in ta_col_names:
            conn.execute(text("ALTER TABLE ta_tasks ADD COLUMN analysis_tool VARCHAR(16) DEFAULT 'trading'"))


def init_db():
    from backend.models.models import Watchlist, WatchlistGroup, KlineCache, SignalLog  # noqa: F401
    from backend.models.ai_report import AIReport  # noqa: F401
    from backend.models.ta_task import TATask  # noqa: F401
    from backend.models.news_cache import NewsCache  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
