from datetime import date, datetime, timedelta
import logging
import math
import time
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
import pandas as pd

from backend.database import get_db
from backend.models.models import KlineCache, Watchlist
from backend.data_sources.factory import get_data_source
from backend.services.indicator import compute_indicators, list_indicators
from backend.services.signal import SignalEngine, get_signal_catalog
from backend.services.livermore import DEFAULT_PARAMS, compute_livermore, validate_params

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


def _default_lookback_days(period: str) -> int:
    # 保证周/月线也有足够样本计算 MA60、MACD(慢线 26)
    return {
        "daily": 365,
        "weekly": 5 * 365,
        "monthly": 10 * 365,
        "60min": 90,
        "30min": 60,
        "15min": 45,
    }.get(period, 365)


def _load_kline_df(db: Session, code: str, period: str, start: str, end: str) -> pd.DataFrame:
    stmt = select(KlineCache).where(
        and_(KlineCache.code == code, KlineCache.period == period,
             KlineCache.trade_date >= start, KlineCache.trade_date <= end)
    ).order_by(KlineCache.trade_date.asc())
    rows = db.execute(stmt).scalars().all()

    if not rows:
        ds = get_data_source()
        df = ds.get_kline(code, period, start, end)
        if df.empty:
            raise HTTPException(status_code=503, detail=f"Data source unavailable — could not fetch data for {code}")
        for _, row in df.iterrows():
            db.add(KlineCache(
                code=code, period=period, trade_date=row["date"],
                open=row["open"], high=row["high"], low=row["low"],
                close=row["close"], volume=row["volume"],
            ))
        db.commit()
        rows = db.execute(stmt).scalars().all()

    data = [{"date": str(r.trade_date), "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
    df = pd.DataFrame(data)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {code}")
    return df


def _sanitize_records(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in list(r.items()):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None
            elif isinstance(v, date):
                r[k] = str(v)
    return records


def _refresh_daily_kline_if_stale(db: Session, code: str, start: str, end: str) -> None:
    """日 K 超过 8 小时未更新则从数据源补齐新交易日（利弗莫尔策略对最新一日敏感）。

    收盘后（UTC≥07:00，即北京时间 15:00 后）若当日 K 仍为盘中快照
    （fetched_at 早于当日 UTC 07:00），强制刷新获取最终收盘 bar，
    避免用盘中快照误判「收盘突破确认」。
    """
    stmt = select(KlineCache.trade_date, KlineCache.fetched_at).where(
        and_(KlineCache.code == code, KlineCache.period == "daily")
    ).order_by(KlineCache.trade_date.desc()).limit(1)
    row = db.execute(stmt).first()
    if row is not None:
        trade_date, last_fetch = row
        now = datetime.utcnow()
        fresh = last_fetch is not None and now - last_fetch < timedelta(hours=8)
        partial_today = (
            str(trade_date) == date.today().isoformat()
            and now.hour >= 7
            and last_fetch is not None
            and last_fetch.date() == now.date()
            and last_fetch.hour < 7
        )
        if fresh and not partial_today:
            return
    ds = get_data_source()
    try:
        df = ds.get_kline(code, "daily", start, end)
    except Exception:
        logger.exception("refresh daily kline failed for %s", code)
        return
    if df.empty:
        return
    for _, row in df.iterrows():
        existing = db.execute(
            select(KlineCache).where(
                and_(KlineCache.code == code, KlineCache.period == "daily",
                     KlineCache.trade_date == row["date"])
            )
        ).scalar()
        if existing is None:
            db.add(KlineCache(
                code=code, period="daily", trade_date=row["date"],
                open=row["open"], high=row["high"], low=row["low"],
                close=row["close"], volume=row["volume"],
            ))
        else:
            existing.open = row["open"]
            existing.high = row["high"]
            existing.low = row["low"]
            existing.close = row["close"]
            existing.volume = row["volume"]
            existing.fetched_at = datetime.utcnow()
    db.commit()


@router.get("/indicators")
def get_indicators(
    code: str = Query(...),
    period: str = Query("daily"),
    indicators: str = Query("MACD,MA,KDJ,RSI"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    force_refresh: bool = Query(False),
):
    if start is None:
        start = (date.today() - timedelta(days=_default_lookback_days(period))).isoformat()
    if end is None:
        end = date.today().isoformat()

    indicator_list = [x.strip() for x in indicators.split(",") if x.strip()]
    available = list_indicators()
    for ind in indicator_list:
        if ind not in available:
            raise HTTPException(status_code=400, detail=f"Unknown indicator: {ind}")

    db: Session = next(get_db())
    try:
        if force_refresh:
            ds = get_data_source()
            df = ds.get_kline(code, period, start, end)
            if df.empty:
                raise HTTPException(status_code=503, detail=f"Data source unavailable — could not fetch data for {code}")
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

        df = _load_kline_df(db, code, period, start, end)
        df = compute_indicators(df, indicator_list)
        signals = SignalEngine().detect(df)
        return {
            "code": code,
            "period": period,
            "kline": _sanitize_records(df),
            "signals": signals,
        }
    finally:
        db.close()


@router.get("/signals")
def get_signals(
    code: str = Query(...),
    period: str = Query("daily"),
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    if start is None:
        start = (date.today() - timedelta(days=_default_lookback_days(period))).isoformat()
    if end is None:
        end = date.today().isoformat()

    db: Session = next(get_db())
    try:
        df = _load_kline_df(db, code, period, start, end)
        df = compute_indicators(df, ["MACD", "MA", "KDJ", "RSI"])
        signals = SignalEngine().detect(df)
        return {"code": code, "period": period, "signals": signals}
    finally:
        db.close()


@router.get("/available-indicators")
def get_available():
    return {"indicators": list_indicators()}


@router.get("/signal-catalog")
def get_catalog():
    """返回支持的信号类型字典：名称、分类、多空方向、解释、误导说明。"""
    return {"signals": get_signal_catalog()}


_LIVERMORE_CACHE: dict[tuple, tuple[float, dict]] = {}
_LIVERMORE_CACHE_TTL = 300  # 秒


@router.get("/livermore")
def get_livermore(
    code: str = Query(...),
    high_n: int = Query(int(DEFAULT_PARAMS["high_n"])),
    box_n: int = Query(int(DEFAULT_PARAMS["box_n"])),
    stop_pct: float = Query(DEFAULT_PARAMS["stop_pct"]),
    first_pct: float = Query(DEFAULT_PARAMS["first_pct"]),
    add_step_pct: float = Query(DEFAULT_PARAMS["add_step_pct"]),
    add_pct: float = Query(DEFAULT_PARAMS["add_pct"]),
    levels: int = Query(int(DEFAULT_PARAMS["levels"])),
):
    """利弗莫尔买入法策略：关键点/突破状态/止损位/金字塔加仓建议。"""
    raw_params = {
        "high_n": high_n, "box_n": box_n, "stop_pct": stop_pct,
        "first_pct": first_pct, "add_step_pct": add_step_pct,
        "add_pct": add_pct, "levels": levels,
    }
    try:
        params = validate_params(raw_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db: Session = next(get_db())
    try:
        stock = db.execute(
            select(Watchlist).where(and_(Watchlist.code == code, Watchlist.market == "A"))
        ).scalars().first()
        holding = {
            "cost": stock.cost if stock else None,
            "shares": stock.shares if stock else None,
            "planned_capital": stock.planned_capital if stock else None,
        }
        cache_key = (
            code, params["high_n"], params["box_n"], params["stop_pct"],
            params["first_pct"], params["add_step_pct"], params["add_pct"], params["levels"],
            holding["cost"], holding["shares"], holding["planned_capital"],
        )
        hit = _LIVERMORE_CACHE.get(cache_key)
        if hit is not None and time.time() - hit[0] < _LIVERMORE_CACHE_TTL:
            return hit[1]

        start = (date.today() - timedelta(days=400)).isoformat()
        end = date.today().isoformat()
        _refresh_daily_kline_if_stale(db, code, start, end)
        df = _load_kline_df(db, code, "daily", start, end)
        # 北京时间 15:00 收盘（UTC 07:00）前，当日 K 为未完成快照，
        # 剔除以免其盘中 close 被误判为「收盘突破确认」；现价判断由实时行情承担
        last_row = df.iloc[-1]
        if str(last_row["date"]) == date.today().isoformat() and datetime.utcnow().hour < 7:
            df = df.iloc[:-1]
        if len(df) < 30:
            raise HTTPException(status_code=422, detail="K线数据不足（少于 30 个交易日），无法计算关键点")

        current_price = None
        try:
            quote = get_data_source().get_realtime_quote(code)
            if isinstance(quote, dict) and quote.get("price"):
                current_price = float(quote["price"])
        except Exception:
            logger.exception("quote fetch failed for %s", code)

        result = compute_livermore(df, params, holding, current_price)
        result["code"] = code
        result["name"] = (stock.name if stock else "") or ""
        result["kline"] = _sanitize_records(df.tail(90))
        if len(_LIVERMORE_CACHE) > 1024:
            _LIVERMORE_CACHE.clear()
        _LIVERMORE_CACHE[cache_key] = (time.time(), result)
        return result
    finally:
        db.close()
