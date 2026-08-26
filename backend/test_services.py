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
    assert any("golden_cross" in t for t in types) or any("death_cross" in t for t in types)
    for s in signals:
        assert "date" in s and "indicator" in s and "description" in s


from backend.services.livermore import compute_livermore, validate_params


def _livermore_df(n: int = 100) -> pd.DataFrame:
    """震荡上行合成日 K：收盘价在 10~13.8 循环，便于精确钉死关键点。"""
    closes = [10.0 + (i % 20) * 0.2 for i in range(n)]
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
        "open": closes,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def test_livermore_pivot_and_box():
    df = _livermore_df(100)
    df.iloc[-61, df.columns.get_loc("high")] = 20.0   # 前 60 日窗口内最高
    df.iloc[-21, df.columns.get_loc("high")] = 15.0   # 前 20 日箱体上沿
    result = compute_livermore(df)
    assert result["pivot"] == 20.0
    assert result["box_top"] == 15.0
    assert result["stop_loss"] == 19.0
    assert result["state"] == "watching"
    assert result["stop_breached"] is True   # 现价 13.8 ≤ 止损 19.0


def test_livermore_states():
    df = _livermore_df(80)
    df.iloc[-61, df.columns.get_loc("high")] = 15.0   # 主关键点 15，止损 14.25
    df.iloc[-21, df.columns.get_loc("high")] = 14.5   # 平台位 14.5（窗口自然最高 14.3 < 14.5）
    base = df.copy()
    b = base.copy()
    b.iloc[-1, b.columns.get_loc("close")] = 15.5
    assert compute_livermore(b)["state"] == "confirmed"
    assert compute_livermore(base, current_price=15.5)["state"] == "intraday"
    assert compute_livermore(base, current_price=14.7)["state"] == "approaching"
    assert compute_livermore(base, current_price=13.0)["state"] == "watching"
    assert compute_livermore(base, current_price=14.0)["stop_breached"] is True
    assert compute_livermore(base, current_price=15.5)["stop_breached"] is False


def test_livermore_ladder():
    df = _livermore_df(100)
    df.iloc[-61, df.columns.get_loc("high")] = 20.0
    result = compute_livermore(df)
    ladder = result["ladder"]
    assert [lv["cum_pct"] for lv in ladder] == [30.0, 50.0, 70.0, 90.0]
    assert ladder[0]["label"] == "首仓"
    assert ladder[0]["price"] == 20.0
    assert ladder[1]["price"] == round(20.0 * 1.03, 2)


def test_livermore_holding_advice():
    df = _livermore_df(100)
    df.iloc[-61, df.columns.get_loc("high")] = 20.0
    result = compute_livermore(
        df,
        holding={"cost": 13.0, "shares": 1000, "planned_capital": 50000},
        current_price=19.4,
    )
    assert result["holding"]["invested"] == 13000.0
    assert result["holding"]["position_pct"] == 26.0
    assert result["ladder"][0]["amount"] == 15000.0
    assert result["stop_breached"] is False
    assert "首仓" in result["advice"]


def test_livermore_param_validation():
    df = _livermore_df(60)
    try:
        compute_livermore(df, {"box_n": 100, "high_n": 60})
    except ValueError:
        return
    raise AssertionError("expected ValueError when box_n >= high_n")


def test_livermore_insufficient_data():
    for bad in (pd.DataFrame(), _livermore_df(1)):
        try:
            compute_livermore(bad)
        except ValueError:
            continue
        raise AssertionError("expected ValueError for <2 rows")


def test_livermore_param_bounds():
    df = _livermore_df(60)
    for bad in ({"high_n": 300}, {"stop_pct": 50}, {"levels": 0}, {"box_n": 0}):
        try:
            compute_livermore(df, bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")
