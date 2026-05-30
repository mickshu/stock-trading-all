"""Screener engine: scans multiple stocks for technical signals.

Compresses a batch screening workflow into one callable function:
1. For each stock, fetch K-line data (cache -> data source fallback)
2. Compute all 4 indicators (MACD, MA, KDJ, RSI)
3. Run SignalEngine().detect() to extract signals
4. Filter signals to recent_days from the latest date in data
5. Optionally further filter by signal_types / signal_categories / signal_levels
6. Return sorted results with per-stock matching signal counts
"""

import math
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.data_sources.factory import get_data_source
from backend.models.models import KlineCache
from backend.services.indicator import compute_indicators
from backend.services.signal import SignalEngine


def _sanitize_records(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in list(r.items()):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None
            elif isinstance(v, date):
                r[k] = str(v)
    return records


def _load_kline_df(
    db: Session, code: str, period: str, start: str, end: str
) -> pd.DataFrame:
    """Load K-line data for a single stock from cache, falling back to data source.

    Mirrors the exact pattern in backend/api/analysis.py:_load_kline_df.
    Returns an empty DataFrame on failure (caller handles it).
    """
    stmt = (
        select(KlineCache)
        .where(
            and_(
                KlineCache.code == code,
                KlineCache.period == period,
                KlineCache.trade_date >= start,
                KlineCache.trade_date <= end,
            )
        )
        .order_by(KlineCache.trade_date.asc())
    )
    rows = db.execute(stmt).scalars().all()

    if not rows:
        ds = get_data_source()
        df = ds.get_kline(code, period, start, end)
        if df.empty:
            return df  # caller handles empty
        for _, row in df.iterrows():
            db.add(
                KlineCache(
                    code=code,
                    period=period,
                    trade_date=row["date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                )
            )
        db.commit()
        rows = db.execute(stmt).scalars().all()

    data = [
        {
            "date": str(r.trade_date),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }
        for r in rows
    ]
    return pd.DataFrame(data)


def run_screener(
    db: Session,
    stocks: list[dict],
    period: str = "daily",
    lookback_days: int = 120,
    recent_days: int = 3,
    signal_types: list[str] | None = None,
    signal_categories: list[str] | None = None,
    signal_levels: list[str] | None = None,
) -> dict:
    """Screen multiple stocks for recent technical signals.

    Args:
        db: SQLAlchemy ORM session.
        stocks: List of dicts, each at minimum with a ``code`` key.
                Optional keys: ``name``, ``market``.
        period: K-line period (``daily``, ``weekly``, ``monthly``, ``60min``, etc.).
        lookback_days: Number of calendar days to fetch data for.
        recent_days: Only signals within this many days of the latest data date
                     are counted as matching.
        signal_types: If set, keep only signals whose ``type`` is in this list.
        signal_categories: If set, keep only signals whose ``category`` is in this list.
        signal_levels: If set, keep only signals whose ``level`` is in this list.

    Returns:
        dict with keys:
            - results (list[dict]): per-stock results sorted by matching_signals desc.
            - total_stocks_screened (int)
            - total_matches (int): number of stocks with at least 1 matching signal.
    """
    results: list[dict] = []

    if not stocks:
        return {"results": results, "total_stocks_screened": 0, "total_matches": 0}

    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    engine = SignalEngine()

    for stock in stocks:
        code = stock.get("code")
        if not code:
            continue

        name = stock.get("name", "")
        market = stock.get("market", "")

        try:
            df = _load_kline_df(db, code, period, start_date, end_date)

            if df.empty:
                continue

            # Compute indicators and detect signals
            df = compute_indicators(df, ["MACD", "MA", "KDJ", "RSI"])
            all_signals = engine.detect(df)

            if not all_signals:
                # Still include the stock even with zero signals,
                # but matching will be empty.
                latest_date = str(df["date"].iloc[-1]) if "date" in df.columns else ""
                latest_close = (
                    float(df["close"].iloc[-1])
                    if "close" in df.columns
                    and pd.notna(df["close"].iloc[-1])
                    else None
                )
                results.append(
                    {
                        "code": code,
                        "name": name,
                        "market": market,
                        "latest_date": latest_date,
                        "latest_close": latest_close,
                        "matching_signals": [],
                        "total_signals": 0,
                    }
                )
                continue

            # Determine the latest date present in data
            latest_date = str(df["date"].iloc[-1]) if "date" in df.columns else ""
            latest_close = (
                float(df["close"].iloc[-1])
                if "close" in df.columns and pd.notna(df["close"].iloc[-1])
                else None
            )

            # Filter signals to only those within recent_days of latest_date
            if latest_date:
                latest_dt = pd.Timestamp(latest_date).to_pydatetime().date()
                cutoff = latest_dt - timedelta(days=recent_days)

                def _within_recent(sig: dict) -> bool:
                    sig_dt = pd.Timestamp(sig["date"]).to_pydatetime().date()
                    return sig_dt >= cutoff

                recent_signals = [s for s in all_signals if _within_recent(s)]
            else:
                recent_signals = all_signals

            # Apply optional filters
            matching = recent_signals
            if signal_types is not None:
                matching = [s for s in matching if s["type"] in signal_types]
            if signal_categories is not None:
                matching = [s for s in matching if s["category"] in signal_categories]
            if signal_levels is not None:
                matching = [s for s in matching if s["level"] in signal_levels]

            results.append(
                {
                    "code": code,
                    "name": name,
                    "market": market,
                    "latest_date": latest_date,
                    "latest_close": latest_close,
                    "matching_signals": matching,
                    "total_signals": len(all_signals),
                }
            )

        except Exception:
            # Gracefully skip any stock that fails during processing
            continue

    # Sort by number of matching signals descending
    results.sort(key=lambda r: len(r["matching_signals"]), reverse=True)

    total_matches = sum(1 for r in results if len(r["matching_signals"]) > 0)

    return {
        "results": results,
        "total_stocks_screened": len(results),
        "total_matches": total_matches,
    }
