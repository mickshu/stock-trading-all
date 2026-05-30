"""
Tushare data provider for Chinese A-share stocks.
Requires TUSHARE_TOKEN environment variable or config key.
"""

import pandas as pd
import os
import logging
from typing import Optional

from .config import get_config

logger = logging.getLogger(__name__)


class TushareUtils:
    """
    Data provider wrapping tushare for Chinese stock data.
    Note: Requires a tushare Pro token (free registration at https://tushare.pro).
    Set via environment variable TUSHARE_TOKEN or config key 'tushare_token'.
    """

    @staticmethod
    def _get_pro():
        """Get authenticated tushare pro API instance."""
        import tushare as ts

        config = get_config()
        token = os.getenv("TUSHARE_TOKEN", config.get("tushare_token", ""))
        if not token:
            raise RuntimeError(
                "Tushare token not configured. "
                "Set TUSHARE_TOKEN environment variable or 'tushare_token' in config."
            )
        ts.set_token(token)
        return ts.pro_api()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Normalize ticker for tushare format: '600000.SH', '000001.SZ'
        """
        symbol = symbol.upper().strip()
        # Already has suffix
        if any(symbol.endswith(s) for s in [".SH", ".SZ", ".BJ"]):
            return symbol
        # Add SH suffix for 600xxx, 601xxx, 603xxx, 605xxx, 688xxx
        if symbol.isdigit() and len(symbol) == 6:
            if symbol.startswith(("6", "68")):
                return f"{symbol}.SH"
            else:
                return f"{symbol}.SZ"
        return symbol

    @staticmethod
    def get_stock_price(
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Get daily K-line data via tushare.

        Args:
            symbol: stock code (e.g. '600000' or '600000.SH')
            start_date: YYYY-MM-DD or YYYYMMDD
            end_date: YYYY-MM-DD or YYYYMMDD

        Returns standardized DataFrame: Date, Open, High, Low, Close, Volume
        """
        pro = TushareUtils._get_pro()
        ts_code = TushareUtils._normalize_symbol(symbol)

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)

        if df is None or df.empty:
            raise ValueError(
                f"No tushare data for '{ts_code}' between {start_date} and {end_date}"
            )

        df = df.rename(
            columns={
                "trade_date": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "vol": "Volume",
                "amount": "Turnover",
                "pct_chg": "ChangePct",
            }
        )
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

        # Ensure core columns exist
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = 0.0

        return df[["Date", "Open", "High", "Low", "Close", "Volume"]]

    @staticmethod
    def get_financial_indicators(symbol: str) -> pd.DataFrame:
        """
        Get key financial indicators via tushare (income statement basics).
        Returns DataFrame with revenue, profit, growth rates.
        """
        pro = TushareUtils._get_pro()
        ts_code = TushareUtils._normalize_symbol(symbol)

        df = pro.income_vip(ts_code=ts_code, fields=",".join([
            "ts_code", "end_date", "total_revenue", "revenue",
            "n_income", "n_income_attr_p",
            "revenue_yoy", "n_income_yoy",
            "grossprofit_margin", "netprofit_margin",
        ]))

        if df is None or df.empty:
            raise ValueError(f"No financial data from tushare for '{ts_code}'")

        df = df.rename(
            columns={
                "end_date": "Date",
                "total_revenue": "TotalRevenue",
                "n_income": "NetProfit",
                "n_income_attr_p": "NetProfitAttrP",
                "revenue_yoy": "RevenueYoY",
                "n_income_yoy": "ProfitYoY",
                "grossprofit_margin": "GrossMargin",
                "netprofit_margin": "NetMargin",
            }
        )
        return df
