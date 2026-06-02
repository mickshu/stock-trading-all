"""自选股相关重要资讯路由。

GET  /api/v1/news/watchlist?time_range=today&limit=50
  可选 codes 查询参数（逗号分隔）覆盖默认「整库自选股」。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.models import Watchlist
from backend.services.news_aggregator import fetch_news_for_watchlist

router = APIRouter(prefix="/api/v1/news", tags=["news"])

ALLOWED_RANGES = {"today", "week", "all"}


def _resolve_codes(db: Session, codes_param: str | None) -> dict[str, str]:
    """codes 参数优先，否则取整库自选股。"""
    rows = db.execute(select(Watchlist)).scalars().all()
    full_map = {w.code: w.name or "" for w in rows if w.code}
    if not codes_param:
        return full_map
    wanted = {c.strip() for c in codes_param.split(",") if c.strip()}
    if not wanted:
        return full_map
    return {c: full_map.get(c, "") for c in wanted if c}


@router.get("/watchlist")
def list_watchlist_news(
    time_range: str = Query("today", description="today | week | all"),
    codes: str | None = Query(None, description="逗号分隔股票代码，缺省 = 全部自选股"),
    limit: int = Query(50, ge=1, le=200),
):
    if time_range not in ALLOWED_RANGES:
        time_range = "today"

    db: Session = next(get_db())
    try:
        code_to_name = _resolve_codes(db, codes)
    finally:
        db.close()

    items = fetch_news_for_watchlist(code_to_name, time_range=time_range, limit=limit)
    return {
        "time_range": time_range,
        "codes": list(code_to_name.keys()),
        "count": len(items),
        "items": items,
    }
