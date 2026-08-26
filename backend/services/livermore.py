"""利弗莫尔买入法策略计算（纯函数，不依赖数据库）。

口径（与设计文档一致）：
- 主关键点 = 近 high_n 个交易日（不含最后一日）最高价
- 平台位 = 近 box_n 个交易日（不含最后一日）箱体上沿
- 突破判定（四级状态）：收盘价 > 主关键点 → 突破确认；现价盘中 > 主关键点 → 盘中突破；
  现价站上平台位 → 接近关键点；其余 → 观望
- 止损位 = 主关键点 × (1 - stop_pct/100)；现价 ≤ 止损位 → stop_breached=True（跌破止损警告）
- 金字塔加仓：首仓 first_pct%，之后每涨 add_step_pct% 加 add_pct%，最多 levels 级，
  累计不超过 90%（留 10% 机动）
"""
from __future__ import annotations

from typing import Any

import pandas as pd

DEFAULT_PARAMS: dict[str, float] = {
    "high_n": 60,
    "box_n": 20,
    "stop_pct": 5.0,
    "first_pct": 30.0,
    "add_step_pct": 3.0,
    "add_pct": 20.0,
    "levels": 3,
}

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "high_n": (20, 250),
    "box_n": (5, 120),
    "stop_pct": (1.0, 20.0),
    "first_pct": (5.0, 100.0),
    "add_step_pct": (0.5, 20.0),
    "add_pct": (5.0, 50.0),
    "levels": (1, 5),
}

MAX_CUM_PCT = 90.0

STATE_LABELS: dict[str, str] = {
    "confirmed": "突破确认 · 买入",
    "intraday": "盘中突破",
    "approaching": "接近关键点",
    "watching": "观望",
}


def validate_params(params: dict[str, Any] | None) -> dict[str, float]:
    """校验并合并默认参数；非法时抛 ValueError。"""
    merged = dict(DEFAULT_PARAMS)
    for k, v in (params or {}).items():
        if v is None or v == "":
            continue
        merged[k] = float(v)
    if merged["box_n"] >= merged["high_n"]:
        raise ValueError("box_n 必须小于 high_n")
    for k, (lo, hi) in PARAM_BOUNDS.items():
        if not (lo <= merged[k] <= hi):
            raise ValueError(f"{k} 必须在 {lo}~{hi} 之间")
    for k in ("high_n", "box_n", "levels"):
        merged[k] = int(merged[k])
    return merged


def _round(v: float | None) -> float | None:
    return round(v, 2) if v is not None and pd.notna(v) else None


def _build_advice(
    state: str,
    cur: float,
    ladder: list[dict[str, Any]],
    position_pct: float | None,
    p: dict[str, float],
    stop_breached: bool,
) -> str:
    """按状态与仓位生成一句话操作建议。"""
    if not ladder:
        return "参数下加仓档位为空，请调整参数。"
    if stop_breached:
        return "现价已跌破止损位，按利弗莫尔法则应离场观望，等待价格重新突破关键点再入场。"
    entry = ladder[0]["price"]
    if position_pct is None:
        if state == "confirmed":
            return (f"收盘已突破关键点 {entry}，触发买入：建议以首仓 {int(p['first_pct'])}% "
                    f"计划资金建仓，止损设于关键点下方 {p['stop_pct']}%。")
        if state == "intraday":
            return f"盘中突破关键点 {entry}，等待收盘确认；确认后以首仓 {int(p['first_pct'])}% 建仓。"
        return f"尚未触发：等待价格突破关键点 {entry} 后买入，突破前保持观望。"
    if position_pct < ladder[0]["add_pct"]:
        if state in ("confirmed", "intraday"):
            return (f"当前仓位 {position_pct:.1f}% 低于首仓，突破关键点后可将仓位"
                    f"提升至首仓 {int(p['first_pct'])}%。")
        return f"当前仓位 {position_pct:.1f}%，等待突破关键点后按首仓 {int(p['first_pct'])}% 建仓。"
    for lv in ladder[1:]:
        if cur >= lv["price"] and position_pct < lv["cum_pct"]:
            return (f"价格已达第{lv['level']}级加仓位 {lv['price']}，可将仓位从 "
                    f"{position_pct:.1f}% 加至 {lv['cum_pct']:.1f}%。")
    for lv in ladder[1:]:
        if position_pct < lv["cum_pct"]:
            gap = (lv["price"] - cur) / cur * 100
            return (f"距下一加仓位 {lv['price']} 还差 {gap:.2f}%（现价 {cur:.2f}），"
                    f"到位后加至 {lv['cum_pct']:.1f}%。")
    return "已接近满仓，持有让利润奔跑；若跌破止损位则离场。"


def compute_livermore(
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
    holding: dict[str, Any] | None = None,
    current_price: float | None = None,
) -> dict[str, Any]:
    """计算利弗莫尔买入法策略结果。

    df 为日 K（date/open/high/low/close/volume），最后一根视为最新交易日；
    current_price 为实时价，缺省用最新收盘价。holding 可含 cost/shares/planned_capital。
    """
    p = validate_params(params)
    holding = holding or {}

    if df is None or len(df) < 2:
        raise ValueError("K线数据不足，无法计算关键点")

    hist = df.iloc[:-1]
    pivot = float(hist.tail(int(p["high_n"]))["high"].max())
    box_top = float(hist.tail(int(p["box_n"]))["high"].max())
    stop_loss = pivot * (1 - p["stop_pct"] / 100)

    last = df.iloc[-1]
    last_close = float(last["close"])
    last_date = str(last["date"])
    cur = float(current_price) if current_price is not None else last_close

    if last_close > pivot:
        state = "confirmed"
    elif cur > pivot:
        state = "intraday"
    elif cur > box_top:
        state = "approaching"
    else:
        state = "watching"
    stop_breached = cur <= stop_loss

    distance_pct = (cur - pivot) / pivot * 100 if pivot > 0 else None

    ladder: list[dict[str, Any]] = []
    cum = 0.0
    for i in range(int(p["levels"]) + 1):
        add = p["first_pct"] if i == 0 else p["add_pct"]
        if cum + add > MAX_CUM_PCT:
            break
        cum += add
        price = pivot * (1 + p["add_step_pct"] / 100) ** i if i > 0 else pivot
        ladder.append({
            "level": i,
            "cum_pct": round(cum, 1),
            "add_pct": round(add, 1),
            "price": _round(price),
            "label": "首仓" if i == 0 else f"第{i}级加仓",
        })

    cost = holding.get("cost")
    shares = holding.get("shares")
    planned = holding.get("planned_capital")
    invested = cost * shares if cost is not None and shares is not None else None
    position_pct = (invested / planned * 100) if invested is not None and planned else None

    advice = _build_advice(state, cur, ladder, position_pct, p, stop_breached)
    for lv in ladder:
        lv["amount"] = _round(planned * lv["add_pct"] / 100) if planned else None

    return {
        "params": p,
        "last_date": last_date,
        "last_close": _round(last_close),
        "current_price": _round(cur),
        "pivot": _round(pivot),
        "box_top": _round(box_top),
        "stop_loss": _round(stop_loss),
        "state": state,
        "state_label": STATE_LABELS[state],
        "stop_breached": stop_breached,
        "distance_pct": _round(distance_pct),
        "ladder": ladder,
        "holding": {
            "cost": cost,
            "shares": shares,
            "planned_capital": planned,
            "invested": _round(invested),
            "position_pct": _round(position_pct),
        },
        "advice": advice,
    }
