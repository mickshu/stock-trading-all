import pandas as pd

from backend.services.indicator import compute_indicators, list_indicators
from backend.services.signal import SignalEngine, detect_cross


def _synthetic_df(n: int = 150) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
        "open": [10.0 + i * 0.05 for i in range(n)],
        "high": [10.5 + i * 0.05 for i in range(n)],
        "low": [9.5 + i * 0.05 for i in range(n)],
        "close": [10.2 + i * 0.05 for i in range(n)],
        "volume": [1_000_000.0] * n,
    })


def test_all_indicators_compute():
    df = _synthetic_df(120)
    result = compute_indicators(df, list_indicators())
    for col in ["MACD_DIF", "MACD_DEA", "MACD_HIST",
                "MA5", "MA10", "MA20", "MA60",
                "KDJ_K", "KDJ_D", "KDJ_J",
                "RSI6", "RSI12", "RSI24"]:
        assert col in result.columns, f"missing {col}"


def test_unknown_indicator_raises():
    df = _synthetic_df(30)
    try:
        compute_indicators(df, ["NOPE"])
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown indicator")


def test_detect_cross_basic():
    df = pd.DataFrame({
        "a": [1, 2, 3, 4, 3, 2, 1],
        "b": [2, 2, 2, 2, 2, 2, 2],
    })
    crosses = detect_cross(df, "a", "b")
    assert (crosses == 1).any()
    assert (crosses == -1).any()


def test_signal_detection_returns_signals():
    n = 200
    closes = [10.0 + ((i % 30) - 15) * 0.5 for i in range(n)]
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
        "open": closes,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * n,
    })
    df = compute_indicators(df, list_indicators())
    signals = SignalEngine().detect(df)
    assert len(signals) > 0
    types = {s["type"] for s in signals}
    assert "golden_cross" in types or "death_cross" in types
    for s in signals:
        assert "date" in s and "indicator" in s and "description" in s
