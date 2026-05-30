from datetime import date, datetime, timedelta
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from backend.database import get_db
from backend.models.models import KlineCache
from backend.data_sources.factory import get_data_source

router = APIRouter(prefix="/api/v1/market", tags=["market"])

CACHE_TTL = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=1),
    "monthly": timedelta(days=1),
    "60min": timedelta(minutes=5),
    "30min": timedelta(minutes=5),
    "15min": timedelta(minutes=5),
}


def _is_cache_fresh(period: str, fetched_at: datetime) -> bool:
    ttl = CACHE_TTL.get(period, timedelta(days=1))
    return datetime.utcnow() - fetched_at < ttl


@router.get("/kline")
def get_kline(
    code: str = Query(..., description="Stock code, e.g. 000001"),
    period: str = Query("daily", description="daily/weekly/monthly/60min/30min/15min"),
    start: str | None = Query(None, description="Start date YYYY-MM-DD"),
    end: str | None = Query(None, description="End date YYYY-MM-DD"),
    force_refresh: bool = Query(False, description="Force refresh from data source"),
):
    if start is None:
        start = (date.today() - timedelta(days=365)).isoformat()
    if end is None:
        end = date.today().isoformat()

    db: Session = next(get_db())
    try:
        if not force_refresh:
            stmt = select(KlineCache.fetched_at).where(
                and_(KlineCache.code == code, KlineCache.period == period)
            ).order_by(KlineCache.fetched_at.desc()).limit(1)
            last_fetch = db.execute(stmt).scalar()
            if last_fetch and _is_cache_fresh(period, last_fetch):
                stmt = select(KlineCache).where(
                    and_(KlineCache.code == code, KlineCache.period == period,
                         KlineCache.trade_date >= start, KlineCache.trade_date <= end)
                ).order_by(KlineCache.trade_date.asc())
                rows = db.execute(stmt).scalars().all()
                if rows:
                    data = [{"date": str(r.trade_date), "open": r.open, "high": r.high,
                             "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
                    return {"code": code, "period": period, "stale": False, "data": data}

        ds = get_data_source()
        df = ds.get_kline(code, period, start, end)
        if df.empty:
            raise HTTPException(status_code=503, detail=f"Data source unavailable — could not fetch K-line for {code}")

        for _, row in df.iterrows():
            existing = db.execute(
                select(KlineCache).where(
                    and_(KlineCache.code == code, KlineCache.period == period,
                         KlineCache.trade_date == row["date"])
                )
            ).scalar()
            if existing is None:
                db.add(KlineCache(
                    code=code, period=period, trade_date=row["date"],
                    open=row["open"], high=row["high"], low=row["low"],
                    close=row["close"], volume=row["volume"],
                ))
        db.commit()

        data = df.to_dict(orient="records")
        for d in data:
            d["date"] = str(d["date"])
        return {"code": code, "period": period, "stale": False, "data": data}
    finally:
        db.close()


@router.get("/indices")
def get_indices():
    ds = get_data_source()
    return ds.get_index_data()


@router.get("/quote")
def get_quote(code: str = Query(..., description="Stock code, e.g. 000001")):
    ds = get_data_source()
    return ds.get_realtime_quote(code)


@router.get("/quotes")
def get_quotes(codes: str = Query(..., description="逗号分隔股票代码，最多 80 个")):
    items = [c.strip() for c in (codes or "").split(",") if c.strip()]
    if not items:
        return {"quotes": []}
    if len(items) > 80:
        raise HTTPException(status_code=400, detail="batch size too large (max 80)")
    ds = get_data_source()
    return {"quotes": ds.get_quotes_batch(items)}


@router.get("/fundamentals")
def get_fundamentals(code: str = Query(..., description="Stock code, e.g. 000001")):
    ds = get_data_source()
    return ds.get_fundamentals(code)
