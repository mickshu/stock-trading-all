"""
Akshare data provider wrapping 新浪财经 (Sina Finance), 东方财富 (Eastmoney), etc.
All methods return standardized DataFrames/dicts matching yfinance column format.

Primary backend: 新浪财经 (Sina Finance) — more reliable for price data
Fallback backend: 东方财富 (Eastmoney) — richer but may have connectivity issues
"""

import pandas as pd
import os
import time
import logging
from typing import Optional, Dict, Tuple

from .config import get_config

logger = logging.getLogger(__name__)


class AkshareUtils:
    """Data provider wrapping akshare (新浪财经 primary, 东方财富 fallback)."""

    # ---- Symbol normalization ----

    @staticmethod
    def _normalize_symbol(symbol: str) -> Tuple[str, str]:
        """
        Normalize ticker for akshare. Returns (normalized_symbol, market).
        market is "CN" or "US".
        """
        symbol = symbol.upper().strip()
        # US tickers — akshare doesn't support these
        if symbol.isalpha() and len(symbol) <= 5:
            return (symbol, "US")
        # Strip exchange suffixes
        for suffix in [".SH", ".SS", ".SZ", ".BJ"]:
            if symbol.endswith(suffix):
                return (symbol.replace(suffix, ""), "CN")
        # Pure 6-digit code → Chinese stock
        if symbol.isdigit() and len(symbol) == 6:
            return (symbol, "CN")
        return (symbol, "unknown")

    @staticmethod
    def _to_sina_prefix(symbol: str) -> str:
        """Convert 6-digit code to Sina prefix: 600xxx→sh600xxx, 000xxx→sz000xxx"""
        symbol = symbol.strip()
        if symbol.startswith(("6", "68")):
            return f"sh{symbol}"
        else:
            return f"sz{symbol}"

    # ---- Stock Price Data ----

    @staticmethod
    def get_stock_price_sina(
        symbol: str, start_date: str, end_date: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        Get daily K-line from 新浪财经 via akshare (primary backend).
        """
        import akshare as ak

        norm_symbol, _ = AkshareUtils._normalize_symbol(symbol)
        sina_sym = AkshareUtils._to_sina_prefix(norm_symbol)

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        df = ak.stock_zh_a_daily(
            symbol=sina_sym,
            start_date=start,
            end_date=end,
            adjust=adjust,
        )

        if df is None or df.empty:
            raise ValueError(f"No data from Sina for '{sina_sym}'")

        # Standardize column names
        column_mapping = {
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "amount": "Turnover",
            "outstanding_share": "OutstandingShare",
            "turnover": "TurnoverRate",
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

        # Ensure core columns exist
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = 0.0

        return df[["Date", "Open", "High", "Low", "Close", "Volume"]]

    @staticmethod
    def get_stock_price_eastmoney(
        symbol: str, start_date: str, end_date: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        Get daily K-line from 东方财富 via akshare (fallback backend).
        """
        import akshare as ak

        norm_symbol, market = AkshareUtils._normalize_symbol(symbol)
        if market == "US":
            raise ValueError(f"akshare does not support US ticker '{symbol}'")

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        df = ak.stock_zh_a_hist(
            symbol=norm_symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust=adjust,
        )

        if df is None or df.empty:
            raise ValueError(f"No data from Eastmoney for '{norm_symbol}'")

        column_mapping = {
            "日期": "Date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
            "成交额": "Turnover",
            "振幅": "Amplitude",
            "涨跌幅": "ChangePct",
            "涨跌额": "Change",
            "换手率": "TurnoverRate",
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = 0.0

        return df[["Date", "Open", "High", "Low", "Close", "Volume"]]

    @staticmethod
    def get_stock_price(
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        Get daily K-line data. Tries 新浪财经 first, falls back to 东方财富.

        Returns standardized DataFrame: Date, Open, High, Low, Close, Volume
        """
        norm_symbol, market = AkshareUtils._normalize_symbol(symbol)
        if market == "US":
            raise ValueError(
                f"akshare does not support US ticker '{symbol}'. "
                f"Use yfinance data source instead."
            )

        # Try Sina first (more reliable connectivity)
        try:
            logger.info(f"Fetching stock price for {symbol} from Sina Finance")
            return AkshareUtils.get_stock_price_sina(symbol, start_date, end_date, adjust)
        except Exception as e:
            logger.warning(f"Sina Finance failed for {symbol}: {e}, trying Eastmoney")

        # Fallback to Eastmoney
        try:
            logger.info(f"Fetching stock price for {symbol} from Eastmoney")
            return AkshareUtils.get_stock_price_eastmoney(symbol, start_date, end_date, adjust)
        except Exception as e:
            raise ValueError(
                f"All akshare backends failed for '{symbol}': {e}"
            )

    # ---- Financial Indicators ----

    @staticmethod
    def get_financial_indicators(symbol: str) -> pd.DataFrame:
        """
        Get financial analysis indicators.
        Tries 东方财富 first (richer data), falls back to Sina-based indicators.
        """
        import akshare as ak

        norm_symbol, market = AkshareUtils._normalize_symbol(symbol)
        if market == "US":
            raise ValueError(f"akshare financials not available for US ticker '{symbol}'")

        # Try Eastmoney (more comprehensive financial data)
        try:
            df = ak.stock_financial_analysis_indicator(symbol=norm_symbol)
            if df is not None and not df.empty:
                column_mapping = {
                    "日期": "Date",
                    "市盈率": "PE",
                    "市净率": "PB",
                    "每股收益": "EPS",
                    "净资产收益率": "ROE",
                    "营业总收入同比增长率": "RevenueYoY",
                    "归属母公司净利润同比增长率": "ProfitYoY",
                    "营业总收入": "TotalRevenue",
                    "归属母公司净利润": "NetProfit",
                    "销售毛利率": "GrossMargin",
                    "每股净资产": "BPS",
                    "总资产净利率": "ROA",
                    "流动比率": "CurrentRatio",
                    "速动比率": "QuickRatio",
                }
                df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
                return df
        except Exception as e:
            logger.warning(f"Eastmoney financials failed for {symbol}: {e}")

        # Fallback: use Sina individual stock info for basic indicators
        try:
            sina_sym = AkshareUtils._to_sina_prefix(norm_symbol)
            info = ak.stock_individual_info_em(symbol=norm_symbol)
            if info is not None and not info.empty:
                # Convert to single-row DataFrame
                result = pd.DataFrame([{
                    "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    "PE": info.loc[info["item"] == "市盈率-动态", "value"].values[0]
                    if "市盈率-动态" in info["item"].values else None,
                }])
                return result
        except Exception as e:
            logger.warning(f"Sina individual info failed for {symbol}: {e}")

        raise ValueError(f"All financial data backends failed for '{symbol}'")

    # ---- Stock News ----

    @staticmethod
    def get_stock_news(symbol: str, limit: int = 30) -> pd.DataFrame:
        """
        Get stock-specific news. Tries 东方财富 first, then falls back.
        Returns DataFrame with columns: title, datetime, source, content
        """
        import akshare as ak

        norm_symbol, market = AkshareUtils._normalize_symbol(symbol)
        if market == "US":
            raise ValueError(f"akshare news not available for US ticker '{symbol}'")

        # Try Eastmoney news
        try:
            df = ak.stock_news_em(symbol=norm_symbol)
            if df is not None and not df.empty:
                column_mapping = {
                    "新闻标题": "title",
                    "发布时间": "datetime",
                    "文章来源": "source",
                    "新闻内容": "content",
                }
                df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
                if len(df) > limit:
                    df = df.head(limit)
                return df
        except Exception as e:
            logger.warning(f"Eastmoney news failed for {symbol}: {e}")

        return pd.DataFrame()

    # ---- Stock Info ----

    @staticmethod
    def get_stock_info(symbol: str) -> Dict:
        """
        Get basic stock information (name, code) from akshare.
        """
        import akshare as ak

        norm_symbol, _ = AkshareUtils._normalize_symbol(symbol)

        # Fallback: use Sina-based individual info via akshare
        try:
            info = ak.stock_individual_info_em(symbol=norm_symbol)
            if info is not None and not info.empty:
                # Column names vary by akshare version
                if "item" in info.columns:
                    name_row = info[info["item"] == "股票简称"]
                    name = str(name_row["value"].values[0]) if not name_row.empty else f"Stock {norm_symbol}"
                elif "股票简称" in str(info.columns):
                    # Alternative column layout
                    name = str(info.iloc[0, 0]) if len(info) > 0 else f"Stock {norm_symbol}"
                else:
                    name = f"Stock {norm_symbol}"
                return {"code": norm_symbol, "name": name}
        except Exception as e:
            logger.warning(f"Stock info fallback failed for {symbol}: {e}")

        return {"code": norm_symbol, "name": f"Stock {norm_symbol}"}

    # ---- Market Overview ----

    @staticmethod
    def get_market_overview() -> pd.DataFrame:
        """
        Get Chinese A-share market overview: major index performance.
        Tries Eastmoney first, falls back to Sina.
        """
        import akshare as ak

        # Try Eastmoney
        try:
            df = ak.stock_zh_index_spot_em()
            if df is not None and not df.empty:
                major_indices = [
                    "上证指数", "深证成指", "创业板指", "科创50",
                    "沪深300", "上证50", "中证500", "中证1000",
                ]
                df = df[df["名称"].isin(major_indices)]
                result = df[["名称", "最新价", "涨跌额", "涨跌幅", "成交量", "成交额"]].copy()
                result.columns = ["name", "price", "change", "change_pct", "volume", "turnover"]
                return result
        except Exception as e:
            logger.warning(f"Eastmoney market overview failed: {e}")

        # Fallback: try Sina index data
        try:
            # Fetch major indices individually from Sina
            index_map = {
                "sh000001": "上证指数",
                "sz399001": "深证成指",
                "sz399006": "创业板指",
                "sh000688": "科创50",
                "sh000300": "沪深300",
                "sh000016": "上证50",
                "sh000905": "中证500",
                "sh000852": "中证1000",
            }
            rows = []
            for code, name in index_map.items():
                try:
                    df_idx = ak.stock_zh_a_daily(symbol=code, adjust="")
                    if df_idx is not None and not df_idx.empty:
                        latest = df_idx.iloc[-1]
                        rows.append({
                            "name": name,
                            "price": latest.get("close", ""),
                            "change": "",
                            "change_pct": "",
                            "volume": latest.get("volume", ""),
                            "turnover": "",
                        })
                except Exception:
                    continue
            if rows:
                return pd.DataFrame(rows)
        except Exception as e:
            logger.warning(f"Sina market overview failed: {e}")

        return pd.DataFrame()

    # ---- Cache Helper ----

    @staticmethod
    def _get_cached_or_fetch(
        symbol: str,
        start_date: str,
        end_date: str,
        fetch_fn,
        cache_prefix: str = "akshare-data",
    ) -> pd.DataFrame:
        """Read from cache if available, otherwise fetch and cache."""
        config = get_config()
        os.makedirs(config["data_cache_dir"], exist_ok=True)
        cache_file = os.path.join(
            config["data_cache_dir"],
            f"{symbol}-{cache_prefix}-{start_date}-{end_date}.csv",
        )
        if os.path.exists(cache_file):
            logger.info(f"Reading cached data from {cache_file}")
            df = pd.read_csv(cache_file)
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
            return df

        time.sleep(0.5)
        df = fetch_fn()
        df.to_csv(cache_file, index=False)
        logger.info(f"Cached data to {cache_file}")
        return df
