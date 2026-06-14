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


@router.get("/financial-history")
def get_financial_history(
    code: str = Query(..., description="Stock code, e.g. 000001"),
    years: int = Query(5, ge=1, le=20, description="Number of years"),
):
    import akshare as ak
    import math

    def _safe(v) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except (TypeError, ValueError):
            return None

    try:
        df = ak.stock_financial_abstract(symbol=code)
    except Exception:
        raise HTTPException(status_code=503, detail="获取财务数据失败")
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="未找到财务数据")

    date_cols = [c for c in df.columns if c not in ("选项", "指标")]
    annual_cols = sorted([c for c in date_cols if c.endswith("1231")], reverse=True)[:years]
    if not annual_cols:
        raise HTTPException(status_code=404, detail="无年报数据")

    year_labels = [c[:4] for c in annual_cols]

    indicator_map: dict[str, dict] = {}
    for _, row in df.iterrows():
        indicator_map[row["指标"]] = row

    def extract(name: str) -> list[float | None]:
        row = indicator_map.get(name)
        if row is None:
            return [None] * len(annual_cols)
        return [_safe(row.get(c)) for c in annual_cols]

    yi = 1e8

    revenue_raw = extract("营业总收入")
    net_profit_raw = extract("归母净利润")

    indicators = [
        {
            "name": "营业收入",
            "unit": "亿元",
            "values": [round(v / yi, 2) if v is not None else None for v in revenue_raw],
        },
        {
            "name": "营收同比",
            "unit": "%",
            "values": [round(v, 2) if v is not None else None for v in extract("营业总收入增长率")],
        },
        {
            "name": "归母净利润",
            "unit": "亿元",
            "values": [round(v / yi, 2) if v is not None else None for v in net_profit_raw],
        },
        {
            "name": "净利润同比",
            "unit": "%",
            "values": [round(v, 2) if v is not None else None for v in extract("归属母公司净利润增长率")],
        },
        {
            "name": "自由现金流/股",
            "unit": "元",
            "values": [round(v, 2) if v is not None else None for v in extract("每股企业自由现金流量")],
        },
        {
            "name": "ROE",
            "unit": "%",
            "values": [round(v, 2) if v is not None else None for v in extract("净资产收益率(ROE)")],
        },
    ]

    dividend_per_share: list[float | None] = [None] * len(annual_cols)
    try:
        div_df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        if div_df is not None and not div_df.empty and "派息" in div_df.columns:
            for i, col in enumerate(annual_cols):
                year = col[:4]
                year_rows = div_df[div_df["公告日期"].astype(str).str.startswith(year)]
                if not year_rows.empty:
                    total = 0.0
                    for _, r in year_rows.iterrows():
                        v = _safe(r["派息"])
                        if v is not None:
                            total += v
                    dividend_per_share[i] = round(total / 10, 4) if total > 0 else 0.0
    except Exception:
        pass

    indicators.append({"name": "分红/股", "unit": "元", "values": dividend_per_share})
    indicators.append({"name": "股息率", "unit": "%", "values": [None] * len(annual_cols)})
    indicators.append({"name": "市盈率(PE)", "unit": "", "values": [None] * len(annual_cols)})

    indicators.append({
        "name": "权益乘数",
        "unit": "",
        "values": [round(v, 2) if v is not None else None for v in extract("权益乘数")],
    })

    equity_raw = extract("股东权益合计(净资产)")
    bvps_raw = extract("每股净资产")
    total_shares: list[float | None] = []
    for eq, bv in zip(equity_raw, bvps_raw):
        if eq is not None and bv is not None and bv > 0:
            total_shares.append(round(eq / bv / yi, 2))
        else:
            total_shares.append(None)

    indicators.append({"name": "总股本", "unit": "亿股", "values": total_shares})

    return {"code": code, "years": year_labels, "indicators": indicators}
