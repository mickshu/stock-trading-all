"""
Central data source dispatcher with fallback and timeout support.

Usage:
    manager = DataSourceManager.get_instance()
    df = manager.get_stock_price("600000", "2024-01-01", "2024-12-31")
"""

import logging
from typing import Any, Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from .config import get_config

logger = logging.getLogger(__name__)

# Per-source timeout in seconds
SOURCE_TIMEOUT = 20


class DataSourceManager:
    """
    Central dispatcher for multi-source data fetching with fallback.

    Primary source from config["data_source"], then fallback chain from
    config["data_source_fallback"]. Each source has a timeout; failures
    are logged and the next source is tried.
    """

    _instance: Optional["DataSourceManager"] = None

    def __init__(self):
        self.config = get_config()
        self.primary = self.config.get("data_source", "akshare")
        self.fallbacks = self.config.get("data_source_fallback", ["yfinance"])

    @classmethod
    def get_instance(cls) -> "DataSourceManager":
        """Return singleton instance, re-reading config on first access."""
        cls._instance = cls()
        return cls._instance

    def _execute_source(
        self, source_name: str, method: Callable, *args, **kwargs
    ) -> Any:
        """Execute a method against a named source. Raises on failure."""
        if source_name == "akshare":
            from .akshare_utils import AkshareUtils

            return method(AkshareUtils, *args, **kwargs)
        elif source_name == "tushare":
            from .tushare_utils import TushareUtils

            return method(TushareUtils, *args, **kwargs)
        elif source_name == "yfinance":
            from .yfin_utils import YFinanceUtils

            return method(YFinanceUtils, *args, **kwargs)
        else:
            raise ValueError(f"Unknown data source: '{source_name}'")

    def _try_source(
        self, source_name: str, method: Callable, *args, **kwargs
    ) -> tuple:
        """
        Try a source with timeout. Returns (result, error).
        result is None on failure, error is None on success.
        """
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self._execute_source, source_name, method, *args, **kwargs
                )
                result = future.result(timeout=SOURCE_TIMEOUT)
                return (result, None)
        except FuturesTimeoutError:
            return (None, TimeoutError(f"'{source_name}' timed out after {SOURCE_TIMEOUT}s"))
        except Exception as e:
            return (None, e)

    def fetch_with_fallback(self, method: Callable, *args, **kwargs) -> Any:
        """
        Try primary source first, then each fallback in order.
        Raises RuntimeError if ALL sources fail.

        `method` is a callable: lambda utils: utils.some_method(...)
        """
        ordered_sources = [self.primary] + [
            s for s in self.fallbacks if s != self.primary
        ]
        errors: List[tuple] = []

        for source in ordered_sources:
            logger.info(f"Trying data source: '{source}'")
            result, error = self._try_source(source, method, *args, **kwargs)
            if error is None:
                logger.info(f"Successfully fetched data from '{source}'")
                return result
            logger.warning(f"Data source '{source}' failed: {error}")
            errors.append((source, str(error)))

        raise RuntimeError(f"All data sources exhausted. Errors: {errors}")

    # ---- Convenience methods ----

    def get_stock_price(
        self, symbol: str, start_date: str, end_date: str, adjust: str = "qfq"
    ):
        """Get standardized OHLCV DataFrame with fallback across all sources."""
        return self.fetch_with_fallback(
            lambda utils, sym=symbol, s=start_date, e=end_date, adj=adjust: (
                utils.get_stock_price(sym, s, e, adj)
                if hasattr(utils, "get_stock_price")
                and "adjust" in utils.get_stock_price.__code__.co_varnames
                else utils.get_stock_price(sym, s, e)
            )
        )

    def get_financial_indicators(self, symbol: str):
        """Get financial indicators DataFrame with fallback."""
        return self.fetch_with_fallback(
            lambda utils, sym=symbol: utils.get_financial_indicators(sym)
        )

    def get_stock_news(self, symbol: str, limit: int = 30):
        """Get stock news DataFrame with fallback."""
        return self.fetch_with_fallback(
            lambda utils, sym=symbol, lim=limit: (
                utils.get_stock_news(sym, lim)
                if hasattr(utils, "get_stock_news")
                else pd.DataFrame()
            )
        )

    def get_stock_info(self, symbol: str):
        """Get basic stock info dict with fallback."""
        return self.fetch_with_fallback(
            lambda utils, sym=symbol: utils.get_stock_info(sym)
        )


# Late import for fallback on get_stock_news
import pandas as pd  # noqa: E402
