from abc import ABC, abstractmethod
import pandas as pd
import ta


class BaseIndicator(ABC):
    name: str = ""
    required_columns: list[str] = ["close"]

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        ...


class MacdIndicator(BaseIndicator):
    name = "MACD"
    required_columns = ["close"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        macd_line = ta.trend.macd(df["close"], window_slow=26, window_fast=12)
        signal_line = ta.trend.macd_signal(df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["MACD_DIF"] = macd_line
        df["MACD_DEA"] = signal_line
        df["MACD_HIST"] = macd_line - signal_line
        return df


class MaIndicator(BaseIndicator):
    name = "MA"
    required_columns = ["close"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["MA5"] = ta.trend.sma_indicator(df["close"], window=5)
        df["MA10"] = ta.trend.sma_indicator(df["close"], window=10)
        df["MA20"] = ta.trend.sma_indicator(df["close"], window=20)
        df["MA60"] = ta.trend.sma_indicator(df["close"], window=60)
        return df


class KdjIndicator(BaseIndicator):
    name = "KDJ"
    required_columns = ["high", "low", "close"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["KDJ_K"] = ta.momentum.stoch(df["high"], df["low"], df["close"], window=9, smooth_window=3)
        df["KDJ_D"] = ta.momentum.stoch_signal(df["high"], df["low"], df["close"], window=9, smooth_window=3)
        df["KDJ_J"] = 3 * df["KDJ_K"] - 2 * df["KDJ_D"]
        return df


class RsiIndicator(BaseIndicator):
    name = "RSI"
    required_columns = ["close"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["RSI6"] = ta.momentum.rsi(df["close"], window=6)
        df["RSI12"] = ta.momentum.rsi(df["close"], window=12)
        df["RSI24"] = ta.momentum.rsi(df["close"], window=24)
        return df


INDICATOR_REGISTRY: dict[str, BaseIndicator] = {
    "MACD": MacdIndicator(),
    "MA": MaIndicator(),
    "KDJ": KdjIndicator(),
    "RSI": RsiIndicator(),
}


def compute_indicators(df: pd.DataFrame, indicator_names: list[str]) -> pd.DataFrame:
    result = df.copy()
    for name in indicator_names:
        if name not in INDICATOR_REGISTRY:
            raise ValueError(f"Unknown indicator: {name}. Available: {list(INDICATOR_REGISTRY.keys())}")
        result = INDICATOR_REGISTRY[name].compute(result)
    return result


def list_indicators() -> list[str]:
    return list(INDICATOR_REGISTRY.keys())
