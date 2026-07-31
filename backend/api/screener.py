from fastapi import APIRouter, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database import get_db
from backend.models.models import Watchlist
from backend.data_sources.factory import get_data_source
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


def _in_range(val, lo, hi) -> bool:
    if val is None:
        return False
    if lo is not None and val < lo:
        return False
    if hi is not None and val > hi:
        return False
    return True


@router.get("/condition")
def condition_screen_stocks(
    pe_min: float | None = Query(None),
    pe_max: float | None = Query(None),
    pb_min: float | None = Query(None),
    pb_max: float | None = Query(None),
    market_cap_min: float | None = Query(None, description="总市值下限（亿元）"),
    market_cap_max: float | None = Query(None, description="总市值上限（亿元）"),
    change_pct_min: float | None = Query(None),
    change_pct_max: float | None = Query(None),
    turnover_min: float | None = Query(None),
    turnover_max: float | None = Query(None),
    volume_ratio_min: float | None = Query(None),
    volume_ratio_max: float | None = Query(None),
    amplitude_min: float | None = Query(None),
    amplitude_max: float | None = Query(None),
    amount_min: float | None = Query(None, description="成交额下限（亿元）"),
    amount_max: float | None = Query(None, description="成交额上限（亿元）"),
    discount_rate_min: float | None = Query(None, description="ETF 折溢价率下限"),
    discount_rate_max: float | None = Query(None, description="ETF 折溢价率上限"),
    size_min: float | None = Query(None, description="ETF 规模下限（亿份）"),
    size_max: float | None = Query(None, description="ETF 规模上限（亿份）"),
    sort_by: str = Query("amount"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    scope: str = Query("all", description="all=全市场 / watchlist=仅自选股 / all_etf=全市场ETF"),
    group_id: int | None = Query(None),
    tag: str | None = Query(None),
):
    security_type = "etf" if scope == "all_etf" else "stock"
    codes: list[str] | None = None
    if scope == "watchlist":
        db: Session = next(get_db())
        try:
            stmt = select(Watchlist)
            if group_id is not None:
                stmt = stmt.where(Watchlist.group_id == group_id)
            rows = db.execute(stmt).scalars().all()
            tag_norm = tag.strip() if tag else None
            if tag_norm and tag_norm in SYSTEM_TAGS:
                rows = [r for r in rows if tag_norm in _parse_tags(r.tags)]
            codes = [r.code for r in rows]
            if not codes:
                return {"results": [], "total": 0, "page": page, "page_size": page_size}
        finally:
            db.close()

    ds = get_data_source()
    raw = ds.screen_stocks(
        sort_by=sort_by,
        sort_order=sort_order,
        page=1,
        page_size=5000,
        codes=codes,
        security_type=security_type,
    )
    items = raw.get("results", [])

    has_filter = any(v is not None for v in [
        pe_min, pe_max, pb_min, pb_max, market_cap_min, market_cap_max,
        change_pct_min, change_pct_max, turnover_min, turnover_max,
        volume_ratio_min, volume_ratio_max, amplitude_min, amplitude_max,
        amount_min, amount_max, discount_rate_min, discount_rate_max,
        size_min, size_max,
    ])

    if has_filter:
        filtered = []
        cap_lo = market_cap_min * 1e8 if market_cap_min is not None else None
        cap_hi = market_cap_max * 1e8 if market_cap_max is not None else None
        amt_lo = amount_min * 1e8 if amount_min is not None else None
        amt_hi = amount_max * 1e8 if amount_max is not None else None
        for item in items:
            if pe_min is not None or pe_max is not None:
                if not _in_range(item.get("pe"), pe_min, pe_max):
                    continue
            if pb_min is not None or pb_max is not None:
                if not _in_range(item.get("pb"), pb_min, pb_max):
                    continue
            if cap_lo is not None or cap_hi is not None:
                if not _in_range(item.get("total_market_cap"), cap_lo, cap_hi):
                    continue
            if change_pct_min is not None or change_pct_max is not None:
                if not _in_range(item.get("change_pct"), change_pct_min, change_pct_max):
                    continue
            if turnover_min is not None or turnover_max is not None:
                if not _in_range(item.get("turnover"), turnover_min, turnover_max):
                    continue
            if volume_ratio_min is not None or volume_ratio_max is not None:
                if not _in_range(item.get("volume_ratio"), volume_ratio_min, volume_ratio_max):
                    continue
            if amplitude_min is not None or amplitude_max is not None:
                if not _in_range(item.get("amplitude"), amplitude_min, amplitude_max):
                    continue
            if amt_lo is not None or amt_hi is not None:
                if not _in_range(item.get("amount"), amt_lo, amt_hi):
                    continue
            if discount_rate_min is not None or discount_rate_max is not None:
                if not _in_range(item.get("discount_rate"), discount_rate_min, discount_rate_max):
                    continue
            if size_min is not None or size_max is not None:
                size_yi = item.get("total_market_cap")
                if size_yi is not None:
                    size_yi = size_yi / 1e8
                if not _in_range(size_yi, size_min, size_max):
                    continue
            filtered.append(item)
        items = filtered

    sort_key = sort_by if (items and sort_by in items[0]) else "amount"
    reverse = sort_order == "desc"
    items.sort(key=lambda x: (x.get(sort_key) is None, x.get(sort_key) or 0), reverse=reverse)

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    return {
        "results": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
