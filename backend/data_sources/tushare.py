import logging
import time
import pandas as pd
from backend.data_sources.base import BaseDataSource, PERIOD_MAP
from backend.data_sources.pinyin_search import rank_stock_matches
from backend.config import settings

logger = logging.getLogger(__name__)


class TushareDataSource(BaseDataSource):
    name = "tushare"

    _STOCK_INDEX_CACHE: dict = {"ts": 0.0, "rows": []}
    _STOCK_INDEX_TTL = 24 * 3600.0

    def __init__(self):
        self._pro = None

    @property
    def pro(self):
        if self._pro is None:
            import tushare as ts
            ts.set_token(settings.tushare_token)
            self._pro = ts.pro_api()
        return self._pro

    def _stock_name_index(self) -> list[tuple[str, str]]:
        now = time.monotonic()
        cache = self._STOCK_INDEX_CACHE
        if cache["rows"] and now - cache["ts"] < self._STOCK_INDEX_TTL:
            return cache["rows"]
        try:
            df = self.pro.stock_basic(
                exchange="", list_status="L", fields="ts_code,symbol,name"
            )
        except Exception:
            logger.exception("tushare stock_basic failed")
            return cache["rows"]
        if df is None or df.empty:
            return cache["rows"]
        rows: list[tuple[str, str]] = []
        for _, row in df.iterrows():
            symbol = row.get("symbol") if "symbol" in df.columns else None
            ts_code = row.get("ts_code") if "ts_code" in df.columns else None
            code = str(symbol if symbol else str(ts_code or "").split(".")[0]).zfill(6)
            name = str(row.get("name") or "")
            if code:
                rows.append((code, name))
        cache["ts"] = now
        cache["rows"] = rows
        return rows

    def search_stocks(self, keyword: str) -> list[dict]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        try:
            rows = self._stock_name_index()
            if not rows:
                return []
            matched = rank_stock_matches(rows, kw, limit=20)
            return [{"code": code, "name": name, "market": "A"} for code, name in matched]
        except Exception:
            logger.exception("tushare search_stocks failed for keyword=%r", kw)
            return []

    def get_kline(self, code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            ts_code = f"{code}.{'SH' if code.startswith('6') else 'SZ'}"
            freq_map = {"daily": "D", "weekly": "W", "monthly": "M"}
            freq = freq_map.get(period, "D")
            df = self.pro.daily(ts_code=ts_code, start_date=start_date.replace("-", ""),
                                end_date=end_date.replace("-", ""))
            if df is None or df.empty:
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            df = df.rename(columns={
                "trade_date": "date", "open": "open", "high": "high",
                "low": "low", "close": "close", "vol": "volume"
            })
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[["date", "open", "high", "low", "close", "volume"]]
        except Exception:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def get_realtime_quote(self, code: str) -> dict:
        return {"code": code, "name": "", "price": 0, "change_pct": 0}

    def get_index_data(self) -> list[dict]:
        return []
