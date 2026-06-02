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


def init_db():
    from backend.models.models import Watchlist, WatchlistGroup, KlineCache, SignalLog  # noqa: F401
    from backend.models.ai_report import AIReport  # noqa: F401
    from backend.models.ta_task import TATask  # noqa: F401
    from backend.models.news_cache import NewsCache  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
