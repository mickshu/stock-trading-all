import pandas as pd
import yfinance as yf
from stockstats import wrap
from typing import Annotated, Optional
import os
import logging
from .config import get_config

logger = logging.getLogger(__name__)


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
        data_dir: Annotated[
            str,
            "directory where the stock data is stored.",
        ],
        online: Annotated[
            bool,
            "whether to use online tools to fetch data or offline tools. If True, will use online tools.",
        ] = False,
        data_source: Annotated[
            Optional[str],
            "which data source to use: 'yfinance', 'akshare', or 'tushare'",
        ] = None,
    ):
        df = None
        data = None

        # Resolve data source
        if data_source is None:
            config = get_config()
            data_source = config.get("data_source", "yfinance")

        if not online:
            try:
                data = pd.read_csv(
                    os.path.join(
                        data_dir,
                        f"{symbol}-YFin-data-2015-01-01-2025-03-25.csv",
                    )
                )
                df = wrap(data)
            except FileNotFoundError:
                raise Exception("Stockstats fail: Yahoo Finance data not fetched yet!")
        else:
            # Get today's date as YYYY-mm-dd to add to cache
            today_date = pd.Timestamp.today()
            curr_date_dt = pd.to_datetime(curr_date)

            end_date = today_date
            start_date = today_date - pd.DateOffset(years=15)
            start_date_str = start_date.strftime("%Y-%m-%d")
            end_date_str = end_date.strftime("%Y-%m-%d")

            # Get config and ensure cache directory exists
            config = get_config()
            os.makedirs(config["data_cache_dir"], exist_ok=True)

            # Cache key includes data source to avoid mixing formats
            data_file = os.path.join(
                config["data_cache_dir"],
                f"{symbol}-{data_source}-data-{start_date_str}-{end_date_str}.csv",
            )

            if os.path.exists(data_file):
                logger.info(f"Reading cached stock data from {data_file}")
                data = pd.read_csv(data_file)
                if "Date" in data.columns:
                    data["Date"] = pd.to_datetime(data["Date"])
            else:
                # Fetch from the configured source
                if data_source == "akshare":
                    from .akshare_utils import AkshareUtils

                    data = AkshareUtils.get_stock_price(
                        symbol, start_date_str, end_date_str
                    )
                    # akshare already returns Date as string, convert for stockstats
                    data["Date"] = pd.to_datetime(data["Date"])
                elif data_source == "tushare":
                    from .tushare_utils import TushareUtils

                    data = TushareUtils.get_stock_price(
                        symbol, start_date_str, end_date_str
                    )
                    data["Date"] = pd.to_datetime(data["Date"])
                else:
                    # Default: yfinance
                    raw = yf.download(
                        symbol,
                        start=start_date_str,
                        end=end_date_str,
                        multi_level_index=False,
                        progress=False,
                        auto_adjust=True,
                    )
                    data = raw.reset_index()
                    if "Date" in data.columns:
                        data["Date"] = pd.to_datetime(data["Date"])
                    elif "index" in data.columns:
                        data = data.rename(columns={"index": "Date"})

                data.to_csv(data_file, index=False)
                logger.info(f"Cached stock data to {data_file}")

            df = wrap(data)
            df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
            curr_date_str = curr_date_dt.strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
