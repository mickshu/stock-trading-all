from fastapi import APIRouter, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database import get_db
from backend.models.models import Watchlist
from backend.services.screener import run_screener
from backend.api.stocks import SYSTEM_TAGS, _parse_tags

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


@router.get("")
def screen_stocks(
    signal_types: str | None = Query(None),
    signal_categories: str | None = Query(None),
    signal_levels: str | None = Query(None),
    period: str = Query("daily"),
    days: int = Query(120),
    recent_days: int = Query(3),
    codes: str | None = Query(None),
    group_id: int | None = Query(None, description="按分组筛选自选股；与 codes 同时传时以 codes 为准"),
    ungrouped: bool = Query(False, description="只扫描未分组的自选股"),
    tag: str | None = Query(None, description="按系统标签筛选自选股，如 holding / watching"),
):
    signal_types_list = [x.strip() for x in signal_types.split(",") if x.strip()] if signal_types else None
    signal_categories_list = [x.strip() for x in signal_categories.split(",") if x.strip()] if signal_categories else None
    signal_levels_list = [x.strip() for x in signal_levels.split(",") if x.strip()] if signal_levels else None

    db: Session = next(get_db())
    try:
        if codes:
            stocks = []
            for c in [x.strip() for x in codes.split(",") if x.strip()]:
                row = db.execute(
                    select(Watchlist).where(Watchlist.code == c, Watchlist.market == "A")
                ).scalar()
                if row:
                    stocks.append({"code": row.code, "name": row.name, "market": row.market})
                else:
                    stocks.append({"code": c, "name": c, "market": "A"})
        else:
            stmt = select(Watchlist)
            if ungrouped:
                stmt = stmt.where(Watchlist.group_id.is_(None))
            elif group_id is not None:
                stmt = stmt.where(Watchlist.group_id == group_id)
            rows = db.execute(stmt).scalars().all()
            tag_norm = tag.strip() if tag else None
            if tag_norm:
                if tag_norm not in SYSTEM_TAGS:
                    rows = []
                else:
                    rows = [r for r in rows if tag_norm in _parse_tags(r.tags)]
            stocks = [{"code": r.code, "name": r.name, "market": r.market} for r in rows]

        result = run_screener(
            db,
            stocks,
            period,
            days,
            recent_days,
            signal_types_list,
            signal_categories_list,
            signal_levels_list,
        )
        return result
    finally:
        db.close()
