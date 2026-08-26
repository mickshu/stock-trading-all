# 利弗莫尔买入法策略 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在自选股「持仓」列表每行加「利弗莫尔」按钮，点击弹出 Modal 浮层展示自动计算的利弗莫尔买入法分析（关键点/突破状态/止损位/金字塔加仓），支持录入持仓成本与参数调整。

**Architecture:** 后端新增纯函数服务 `backend/services/livermore.py`（关键点/突破/止损/加仓档位计算），`analysis.py` 路由加 `GET /api/v1/analysis/livermore`（300s 内存缓存 + 日 K 8 小时过期刷新）；前端新增 `LivermoreModal.tsx` 组件（复用 KlineChart 标注关键点/止损线），`Watchlist.tsx` 持仓 tab 下每行加按钮。持仓字段（cost/shares/planned_capital）存 `Watchlist` 表。

**Tech Stack:** FastAPI + SQLAlchemy(SQLite) + pandas；React 19 + AntD 5 + ECharts；测试 pytest（`backend/test_services.py`）。

**约定：**
- 测试命令：`cd /home/admin/stock-trading-all && .venv/bin/python -m pytest backend/test_services.py -v`（venv 内 pytest 缺失时：`.venv/bin/python -m uv pip install pytest --index-url https://pypi.tuna.tsinghua.edu.cn/simple`）
- 前端验证：`cd /home/admin/stock-trading-all/frontend && npm run lint`
- 每个 Task 完成即 commit，commit 消息用各 Task 指定内容

---

### Task 1: livermore 纯函数服务（TDD）

**Files:**
- Create: `backend/services/livermore.py`
- Modify: `backend/test_services.py`（文件末尾追加测试）

- [ ] **Step 1: 写失败测试** — 在 `backend/test_services.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/admin/stock-trading-all && .venv/bin/python -m pytest backend/test_services.py -v -k livermore`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.services.livermore'` 或 collect error

- [ ] **Step 3: 创建服务实现** — `backend/services/livermore.py` 完整内容：

```python
"""利弗莫尔买入法策略计算（纯函数，不依赖数据库）。

口径（与设计文档一致）：
- 主关键点 = 近 high_n 个交易日（不含最后一日）最高价
- 平台位 = 近 box_n 个交易日（不含最后一日）箱体上沿
- 突破判定（四级状态）：收盘价 > 主关键点 → 突破确认；现价盘中 > 主关键点 → 盘中突破；
  现价站上平台位 → 接近关键点；其余 → 观望
- 现价 ≤ 止损位 → stop_breached=True（跌破止损警告，附加于四级状态之上）
- 止损位 = 主关键点 × (1 - stop_pct/100)
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/admin/stock-trading-all && .venv/bin/python -m pytest backend/test_services.py -v -k livermore`
Expected: 5 passed

- [ ] **Step 4.5: 修复既有坏导入 `detect_cross`（全量测试 collect 依赖它）** — `backend/test_services.py` 第 4 行导入了 `signal.py` 中不存在的 `detect_cross`，导致整个测试文件无法 collect（既有缺陷）。在 `backend/services/signal.py` 的 `_cross_down` 函数之后追加：

```python
def detect_cross(df: pd.DataFrame, col_a: str, col_b: str) -> pd.Series:
    """返回 1（a 上穿 b）/-1（a 下穿 b）/0 的信号序列。"""
    diff = df[col_a] - df[col_b]
    prev = diff.shift(1)
    cross = pd.Series(0, index=df.index, dtype=int)
    up = diff > 0
    down = diff < 0
    cross[up] = (prev[up] <= 0).astype(int)
    cross[down] = -(prev[down] >= 0).astype(int)
    return cross
```

Run: `cd /home/admin/stock-trading-all && .venv/bin/python -m pytest backend/test_services.py -v`
Expected: 全部 passed（含旧测试 `test_detect_cross_basic` 与 5 个 `test_livermore_*`）

- [ ] **Step 5: 提交**

```bash
cd /home/admin/stock-trading-all
git add backend/services/livermore.py backend/test_services.py backend/services/signal.py
git commit -m "feat: 利弗莫尔买入法纯函数服务（关键点/突破状态/止损/金字塔加仓）+ 修复 detect_cross 缺失"
```

---

### Task 2: Watchlist 模型字段 + SQLite 迁移 + stocks API

**Files:**
- Modify: `backend/models/models.py`（Watchlist 类，`target_price = Column(Float, nullable=True)` 之后）
- Modify: `backend/database.py`（`_migrate_sqlite` 内）
- Modify: `backend/api/stocks.py`

- [ ] **Step 1: 模型加 3 列** — `backend/models/models.py` 的 `Watchlist` 类中，在 `target_price = Column(Float, nullable=True)` 行之后插入：

```python
    cost = Column(Float, nullable=True)
    shares = Column(Float, nullable=True)
    planned_capital = Column(Float, nullable=True)
```

- [ ] **Step 2: SQLite 迁移** — `backend/database.py` 的 `_migrate_sqlite()` 中，在 `"alert_diff_pct"` 迁移块之后插入：

```python
        if cols and "cost" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN cost FLOAT"))
        if cols and "shares" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN shares FLOAT"))
        if cols and "planned_capital" not in col_names:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN planned_capital FLOAT"))
```

- [ ] **Step 3: stocks API 返回与更新** — `backend/api/stocks.py` 两处修改：

`_stock_dict`（在 `"alert_diff_pct": r.alert_diff_pct,` 之后加）：

```python
        "cost": getattr(r, "cost", None),
        "shares": getattr(r, "shares", None),
        "planned_capital": getattr(r, "planned_capital", None),
```

`update_stock`（在 `alert_diff_pct` 校验块之后、`db.commit()` 之前加）：

```python
        for field in ("cost", "shares", "planned_capital"):
            if field in payload:
                v = payload[field]
                if v is None or v == "":
                    setattr(stock, field, None)
                else:
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"{field} 必须为数字")
                    if fv < 0:
                        raise HTTPException(status_code=400, detail=f"{field} 不能为负")
                    setattr(stock, field, fv)
```

- [ ] **Step 4: 验证迁移生效**

Run: `cd /home/admin/stock-trading-all && .venv/bin/python -c "from backend.database import init_db; init_db(); print('ok')" && .venv/bin/python -c "import sqlite3; c = sqlite3.connect('data/stocktool.db'); print([r[1] for r in c.execute('PRAGMA table_info(watchlist)').fetchall()])"`
Expected: 输出包含 `cost`、`shares`、`planned_capital`

- [ ] **Step 5: 提交**

```bash
cd /home/admin/stock-trading-all
git add backend/models/models.py backend/database.py backend/api/stocks.py
git commit -m "feat: Watchlist 增加持仓字段 cost/shares/planned_capital + 迁移 + PATCH 支持"
```

---

### Task 3: /api/v1/analysis/livermore 端点

**Files:**
- Modify: `backend/api/analysis.py`

- [ ] **Step 1: imports 修改** — 顶部第 1 行改为：

```python
from datetime import date, datetime, timedelta
import logging
import math
import time
```

第 9 行 `from backend.models.models import KlineCache` 改为：

```python
from backend.models.models import KlineCache, Watchlist
```

`get_signal_catalog` 导入行之后加：

```python
from backend.services.livermore import DEFAULT_PARAMS, compute_livermore, validate_params

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: 新增日 K 过期刷新 helper** — 在 `_sanitize_records` 函数之后追加：

```python
def _refresh_daily_kline_if_stale(db: Session, code: str, start: str, end: str) -> None:
    """日 K 超过 8 小时未更新则从数据源补齐新交易日（利弗莫尔策略对最新一日敏感）。"""
    stmt = select(KlineCache.fetched_at).where(
        and_(KlineCache.code == code, KlineCache.period == "daily")
    ).order_by(KlineCache.fetched_at.desc()).limit(1)
    last_fetch = db.execute(stmt).scalar()
    if last_fetch is not None and datetime.utcnow() - last_fetch < timedelta(hours=8):
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
```

- [ ] **Step 3: 新增端点** — 在文件末尾 `get_catalog` 之后追加：

```python
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
```

- [ ] **Step 4: 本地起临时后端验证**（避开已在跑的 8000 端口，用 8001）：

```bash
cd /home/admin/stock-trading-all
CODE=$(.venv/bin/python -c "import sqlite3; c=sqlite3.connect('data/stocktool.db'); print(c.execute(\"select code from watchlist order by id limit 1\").fetchone()[0])")
nohup .venv/bin/python -m uvicorn backend.main:app --port 8001 > /tmp/livermore_test.log 2>&1 &
sleep 6
curl -s "http://localhost:8001/api/v1/analysis/livermore?code=$CODE" | .venv/bin/python -m json.tool | head -30
```

Expected: JSON 含 `pivot`、`box_top`、`stop_loss`、`state`、`ladder`、`advice`、`kline` 字段；`state` 为 5 种枚举之一。再验证参数校验：

```bash
curl -s "http://localhost:8001/api/v1/analysis/livermore?code=$CODE&box_n=999" 
```

Expected: 422 detail "box_n 必须在 5.0~120.0 之间"。验证后停掉临时服务：`pkill -f "uvicorn backend.main:app --port 8001"`（若杀不掉用 `ss -tlnp | grep 8001` 找 pid 后 `kill -9`）。

- [ ] **Step 5: 提交**

```bash
cd /home/admin/stock-trading-all
git add backend/api/analysis.py
git commit -m "feat: 新增 /api/v1/analysis/livermore 端点（含内存缓存与日K过期刷新）"
```

---

### Task 4: 前端类型 + API 客户端

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/analysis.ts`
- Modify: `frontend/src/api/stocks.ts`

- [ ] **Step 1: 类型** — `types/index.ts` 的 `StockInfo` 接口内（`alert_diff_pct?: number | null;` 之后）加：

```ts
  cost?: number | null;
  shares?: number | null;
  planned_capital?: number | null;
```

文件末尾追加：

```ts
export interface LivermoreLadderLevel {
  level: number;
  cum_pct: number;
  add_pct: number;
  price: number | null;
  label: string;
  amount: number | null;
}

export interface LivermoreResponse {
  code: string;
  name: string;
  params: {
    high_n: number;
    box_n: number;
    stop_pct: number;
    first_pct: number;
    add_step_pct: number;
    add_pct: number;
    levels: number;
  };
  last_date: string;
  last_close: number | null;
  current_price: number | null;
  pivot: number | null;
  box_top: number | null;
  stop_loss: number | null;
  state: 'confirmed' | 'intraday' | 'approaching' | 'watching';
  state_label: string;
  stop_breached: boolean;
  distance_pct: number | null;
  ladder: LivermoreLadderLevel[];
  holding: {
    cost: number | null;
    shares: number | null;
    planned_capital: number | null;
    invested: number | null;
    position_pct: number | null;
  };
  advice: string;
  kline: (KlineData & Partial<IndicatorData>)[];
}
```

- [ ] **Step 2: analysis API** — `api/analysis.ts` 追加：

```ts
import type { AnalysisResponse, LivermoreResponse } from '../types';

export interface LivermoreQuery {
  high_n?: number;
  box_n?: number;
  stop_pct?: number;
  first_pct?: number;
  add_step_pct?: number;
  add_pct?: number;
  levels?: number;
}

export async function fetchLivermore(
  code: string,
  params: LivermoreQuery = {},
): Promise<LivermoreResponse> {
  const { data } = await api.get<LivermoreResponse>('/analysis/livermore', {
    params: { code, ...params },
  });
  return data;
}
```

（import 行改为同时引入两个类型。）

- [ ] **Step 3: stocks API** — `api/stocks.ts` 的 `setStockTargets` 之后追加：

```ts
export async function setStockHolding(
  stockId: number,
  payload: { cost?: number | null; shares?: number | null; planned_capital?: number | null },
): Promise<StockInfo> {
  const { data } = await api.patch<StockInfo>(`/stocks/${stockId}`, payload);
  return data;
}
```

- [ ] **Step 4: 验证 lint**

Run: `cd /home/admin/stock-trading-all/frontend && npm run lint`
Expected: 无 error（若有与本任务无关的既有 warning 忽略，但新增代码不得引入 error）

- [ ] **Step 5: 提交**

```bash
cd /home/admin/stock-trading-all
git add frontend/src/types/index.ts frontend/src/api/analysis.ts frontend/src/api/stocks.ts
git commit -m "feat(frontend): 利弗莫尔类型定义与 API 客户端（fetchLivermore / setStockHolding）"
```

---

### Task 5: KlineChart 支持 markLines（关键点/止损线）

**Files:**
- Modify: `frontend/src/components/KlineChart.tsx`

- [ ] **Step 1: Props 扩展** — `interface Props` 内（`highlightPosition?: number | null;` 之后）加：

```ts
  markLines?: { price: number | null; name: string; color?: string }[];
```

函数签名解构处（`highlightPosition = null,` 之后）加：

```ts
  markLines = [],
```

- [ ] **Step 2: 蜡烛图 series 加 markLine** — 将现有的 `const series: Record<string, unknown>[] = [ { type: 'candlestick', ... }, ];`（约 142-156 行）替换为：

```ts
    const candlestick: Record<string, unknown> = {
      type: 'candlestick',
      name: 'K线',
      data: ohlc,
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: '#ef5350',
        color0: '#26a69a',
        borderColor: '#ef5350',
        borderColor0: '#26a69a',
      },
    };
    const validMarkLines = markLines.filter((m) => m.price != null && m.price > 0);
    if (validMarkLines.length > 0) {
      candlestick.markLine = {
        symbol: 'none',
        silent: true,
        label: { position: 'insideEndTop', formatter: '{b}', fontSize: 10, color: '#666' },
        lineStyle: { type: 'dashed', width: 1 },
        data: validMarkLines.map((m) => ({
          yAxis: m.price,
          name: m.name,
          lineStyle: m.color ? { color: m.color } : undefined,
        })),
      };
    }
    const series: Record<string, unknown>[] = [candlestick];
```

- [ ] **Step 3: effect 依赖数组加 markLines** — 文件末尾 `useEffect` 依赖数组（约 418 行）`[klineData, showMA, showMACD, showKDJ, showRSI, signals, showSignals, highlightPosition]` 加 `markLines`：

```ts
  }, [klineData, showMA, showMACD, showKDJ, showRSI, signals, showSignals, highlightPosition, markLines]);
```

- [ ] **Step 4: 验证 lint**

Run: `cd /home/admin/stock-trading-all/frontend && npm run lint`
Expected: 无新 error

- [ ] **Step 5: 提交**

```bash
cd /home/admin/stock-trading-all
git add frontend/src/components/KlineChart.tsx
git commit -m "feat(frontend): KlineChart 支持 markLines 水平参考线（关键点/止损标注）"
```

---

### Task 6: LivermoreModal 组件

**Files:**
- Create: `frontend/src/components/LivermoreModal.tsx`

- [ ] **Step 1: 创建组件** — 完整内容：

```tsx
import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Collapse, InputNumber, Modal, Space, Spin, Table, Tag, Typography, message,
} from 'antd';
import KlineChart from './KlineChart';
import { fetchLivermore, type LivermoreQuery } from '../api/analysis';
import { setStockHolding } from '../api/stocks';
import type { LivermoreResponse, StockInfo } from '../types';

const DEFAULT_QUERY: LivermoreQuery = {
  high_n: 60,
  box_n: 20,
  stop_pct: 5,
  first_pct: 30,
  add_step_pct: 3,
  add_pct: 20,
  levels: 3,
};

const STATE_COLORS: Record<LivermoreResponse['state'], string> = {
  confirmed: 'red',
  intraday: 'orange',
  approaching: 'gold',
  watching: 'default',
};

const PARAM_FIELDS: { key: keyof LivermoreQuery; label: string; min: number; max: number }[] = [
  { key: 'high_n', label: '关键点回看(日)', min: 20, max: 250 },
  { key: 'box_n', label: '箱体(日)', min: 5, max: 120 },
  { key: 'stop_pct', label: '止损(%)', min: 1, max: 20 },
  { key: 'first_pct', label: '首仓(%)', min: 5, max: 100 },
  { key: 'add_step_pct', label: '加仓级差(%)', min: 0.5, max: 20 },
  { key: 'add_pct', label: '每级加仓(%)', min: 5, max: 50 },
  { key: 'levels', label: '加仓级数', min: 1, max: 5 },
];

function extractError(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || '请求失败，请稍后重试';
}

function PriceCard({ label, value, tone }: { label: string; value: number | null; tone?: 'danger' }) {
  return (
    <div
      style={{
        flex: 1, minWidth: 110, background: '#fafafa', borderRadius: 8,
        padding: '8px 12px', textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 12, color: '#999' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: tone === 'danger' ? '#cf1322' : undefined }}>
        {value != null ? value.toFixed(2) : '—'}
      </div>
    </div>
  );
}

export default function LivermoreModal({
  stock,
  open,
  onClose,
}: {
  stock: StockInfo | null;
  open: boolean;
  onClose: () => void;
}) {
  const [data, setData] = useState<LivermoreResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useState<LivermoreQuery>(DEFAULT_QUERY);
  const [holdingDraft, setHoldingDraft] = useState<{
    cost: number | null;
    shares: number | null;
    planned_capital: number | null;
  }>({ cost: null, shares: null, planned_capital: null });
  const [savingHolding, setSavingHolding] = useState(false);

  const load = useCallback(
    async (query: LivermoreQuery) => {
      if (!stock) return;
      setLoading(true);
      setError(null);
      try {
        setData(await fetchLivermore(stock.code, query));
      } catch (e) {
        setError(extractError(e));
      } finally {
        setLoading(false);
      }
    },
    [stock],
  );

  useEffect(() => {
    if (!open || !stock) return;
    setHoldingDraft({
      cost: stock.cost ?? null,
      shares: stock.shares ?? null,
      planned_capital: stock.planned_capital ?? null,
    });
    setParams(DEFAULT_QUERY);
    void load(DEFAULT_QUERY);
  }, [open, stock, load]);

  const handleSaveHolding = async () => {
    if (stock?.id == null) return;
    setSavingHolding(true);
    try {
      await setStockHolding(stock.id, holdingDraft);
      message.success('持仓信息已保存');
      await load(params);
    } catch {
      message.error('保存失败，请重试');
    } finally {
      setSavingHolding(false);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
      title={`利弗莫尔买入法 · ${stock?.name ?? ''} ${stock?.code ?? ''}`}
    >
      <Spin spinning={loading}>
        {error ? (
          <Alert
            type="error"
            message="计算失败"
            description={error}
            action={<Button size="small" onClick={() => void load(params)}>重试</Button>}
          />
        ) : data ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div
              style={{
                background: '#fafafa', borderRadius: 8, padding: '10px 12px',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                flexWrap: 'wrap', gap: 8,
              }}
            >
              <Space size={6}>
                <Typography.Text type="secondary">现价</Typography.Text>
                <Typography.Text strong style={{ fontSize: 18 }}>
                  {data.current_price != null ? data.current_price.toFixed(2) : '—'}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {data.last_date}
                </Typography.Text>
              </Space>
              <Space size={6}>
                <Tag color={STATE_COLORS[data.state]}>{data.state_label}</Tag>
                {data.distance_pct != null && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    距关键点 {data.distance_pct > 0 ? '+' : ''}
                    {data.distance_pct.toFixed(2)}%
                  </Typography.Text>
                )}
              </Space>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <PriceCard label="主关键点" value={data.pivot} />
              <PriceCard label="平台位" value={data.box_top} />
              <PriceCard label="止损位" value={data.stop_loss} tone="danger" />
            </div>

            <Alert
              type={data.stop_breached ? 'error' : data.state === 'confirmed' ? 'success' : 'info'}
              message={data.advice}
              showIcon
            />

            <Typography.Text strong>金字塔加仓</Typography.Text>
            <Table
              size="small"
              pagination={false}
              rowKey="level"
              dataSource={data.ladder}
              columns={[
                { title: '档位', dataIndex: 'label' },
                { title: '累计仓位', dataIndex: 'cum_pct', align: 'right', render: (v: number) => `${v}%` },
                { title: '加仓价格', dataIndex: 'price', align: 'right', render: (v: number | null) => (v != null ? v.toFixed(2) : '—') },
                { title: '建议金额', dataIndex: 'amount', align: 'right', render: (v: number | null) => (v != null ? `¥${v.toLocaleString()}` : '—') },
              ]}
            />

            <div style={{ background: '#fafafa', borderRadius: 8, padding: '10px 12px' }}>
              <Space wrap>
                <Typography.Text strong>持仓</Typography.Text>
                <InputNumber
                  size="small" placeholder="成本" precision={3} min={0} controls={false}
                  style={{ width: 100 }} value={holdingDraft.cost}
                  onChange={(v) => setHoldingDraft((d) => ({ ...d, cost: v == null ? null : Number(v) }))}
                />
                <InputNumber
                  size="small" placeholder="股数" precision={0} min={0} controls={false}
                  style={{ width: 100 }} value={holdingDraft.shares}
                  onChange={(v) => setHoldingDraft((d) => ({ ...d, shares: v == null ? null : Number(v) }))}
                />
                <InputNumber
                  size="small" placeholder="计划资金" precision={2} min={0} controls={false}
                  style={{ width: 120 }} value={holdingDraft.planned_capital}
                  onChange={(v) => setHoldingDraft((d) => ({ ...d, planned_capital: v == null ? null : Number(v) }))}
                />
                <Button size="small" type="primary" loading={savingHolding} disabled={stock?.id == null} onClick={handleSaveHolding}>
                  保存
                </Button>
              </Space>
              {data.holding.position_pct != null && (
                <div style={{ marginTop: 6 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    当前仓位 {data.holding.position_pct.toFixed(1)}%
                    （已投入 ¥{(data.holding.invested ?? 0).toLocaleString()}）
                  </Typography.Text>
                </div>
              )}
            </div>

            <Collapse
              ghost
              size="small"
              items={[
                {
                  key: 'params',
                  label: '参数设置',
                  children: (
                    <Space wrap>
                      {PARAM_FIELDS.map((f) => (
                        <Space key={f.key} size={4}>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{f.label}</Typography.Text>
                          <InputNumber
                            size="small" min={f.min} max={f.max}
                            value={params[f.key] as number}
                            onChange={(v) => v != null && setParams((p) => ({ ...p, [f.key]: Number(v) }))}
                            style={{ width: 80 }}
                          />
                        </Space>
                      ))}
                      <Button size="small" type="primary" onClick={() => void load(params)}>
                        重新计算
                      </Button>
                    </Space>
                  ),
                },
              ]}
            />

            {data.kline.length > 0 && (
              <KlineChart
                klineData={data.kline}
                height={220}
                showMA={false}
                showSignals={false}
                markLines={[
                  { price: data.pivot, name: '关键点', color: '#cf1322' },
                  { price: data.stop_loss, name: '止损', color: '#3f8600' },
                ]}
              />
            )}

            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              风险提示：突破关键点买入、跌破止损位离场、让利润奔跑。计算结果仅供策略参考，不构成投资建议。
            </Typography.Text>
          </div>
        ) : null}
      </Spin>
    </Modal>
  );
}
```

- [ ] **Step 2: 验证 lint**

Run: `cd /home/admin/stock-trading-all/frontend && npm run lint`
Expected: 无新 error

- [ ] **Step 3: 提交**

```bash
cd /home/admin/stock-trading-all
git add frontend/src/components/LivermoreModal.tsx
git commit -m "feat(frontend): 利弗莫尔买入法浮层组件（状态/关键价/加仓表/持仓录入/参数/迷你K线）"
```

> **质量审查修正记录**（已随实现提交，代码以此为准）：① load 加单调序号 ref 防竞态（切换股票/快速重算时旧响应覆盖新数据）；② useEffect 依赖 `[open, stock?.code, load]`（按 code 而非对象身份）；③ `destroyOnClose` → `destroyOnHidden`（antd v6 弃用）；④ 错误 Alert 与数据共存渲染（保存后重算失败不再清空视图）；⑤ extractError 防御数组型 detail（422 返回数组防 React 崩溃）；⑥ 重新计算/重试按钮加 loading/disabled。

> **最终审查修正记录**（部署前已修）：收盘后（UTC≥07:00）当日 K 若仍为盘中快照（fetched_at 早于当日 07:00 UTC），`_refresh_daily_kline_if_stale` 强制刷新取最终收盘 bar，避免收盘后数小时内用盘中快照误判「突破确认·买入」。

---

### Task 7: Watchlist 入口按钮

**Files:**
- Modify: `frontend/src/pages/Watchlist.tsx`

- [ ] **Step 1: import** — 组件 import 区（`import WatchlistNewsCard ...` 之后）加：

```tsx
import LivermoreModal from '../components/LivermoreModal';
```

- [ ] **Step 2: 状态** — 在 `const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);` 之后加：

```tsx
  const [livermoreStock, setLivermoreStock] = useState<StockInfo | null>(null);
```

- [ ] **Step 3: 桌面操作列按钮** — 桌面 `title: '操作'` 列的 render 内，在「分析」按钮之前插入：

```tsx
          {filter === tagFilterKey('holding') && (
            <Button type="link" size="small" onClick={() => setLivermoreStock(record)}>
              利弗莫尔
            </Button>
          )}
```

- [ ] **Step 4: 移动端卡片按钮** — `renderMobileList` 的卡片头部 `<Space size={4}>` 内（「分析」按钮之前）插入同样的条件按钮：

```tsx
                  {filter === tagFilterKey('holding') && (
                    <Button type="link" size="small" onClick={() => setLivermoreStock(record)}>
                      利弗莫尔
                    </Button>
                  )}
```

- [ ] **Step 5: 渲染 Modal** — 组件 return 的最外层 `</div>` 之前（分组管理 `</Modal>` 之后）插入：

```tsx
      <LivermoreModal
        stock={livermoreStock}
        open={livermoreStock != null}
        onClose={() => setLivermoreStock(null)}
      />
```

- [ ] **Step 6: 验证 lint + build**

Run: `cd /home/admin/stock-trading-all/frontend && npm run lint && npm run build`
Expected: lint 无新 error；build 成功产出 `frontend/dist/`

- [ ] **Step 7: 提交**

```bash
cd /home/admin/stock-trading-all
git add frontend/src/pages/Watchlist.tsx
git commit -m "feat(frontend): 持仓列表每行新增「利弗莫尔」按钮弹出策略浮层（桌面+移动端）"
```

> **质量审查修正记录**（已随实现提交，代码以此为准）：① LivermoreModal 增加 `onSaved` 回调，保存持仓后回写 Watchlist 行数据（修复重开浮层时草稿从旧快照初始化、用户数据看似丢失）；② 重开/切换股票时 `setData(null)` 清旧分析内容（防标题 B 显示 A 的数据）；③ 桌面操作列 width 120→180（三按钮放不下）。

---

### Task 8: 版本水印 + 全量验证

**Files:**
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: 水印 bump** — 将 `v.26.07.31_10` 改为 `v.26.08.26_1`

- [ ] **Step 2: 后端测试全量**

Run: `cd /home/admin/stock-trading-all && .venv/bin/python -m pytest backend/test_services.py -v`
Expected: 全部 passed（含 5 个 livermore 测试）

- [ ] **Step 3: 前端 lint + build 全量**

Run: `cd /home/admin/stock-trading-all/frontend && npm run lint && npm run build`
Expected: lint 无 error，build 成功

- [ ] **Step 4: 提交**

```bash
cd /home/admin/stock-trading-all
git add frontend/src/components/AppLayout.tsx
git commit -m "chore: 版本水印 v.26.08.26_1（利弗莫尔买入法浮层）"
```

---

### Task 9: 部署

- [ ] **Step 1: 推送 main**

```bash
cd /home/admin/stock-trading-all
git push origin main
```

Expected: 推送成功（remote 为 git@github.com:mickshu/stock-trading-all.git）。若失败（如 SSH key 问题），停下报告，不要跳过。

- [ ] **Step 2: 触发 redeploy webhook**

```bash
curl -s -X POST http://localhost:8000/api/updatereload
```

Expected: JSON 含 `"status": "ok"`（或各步骤 exit_code 均为 0）。若 `git_pull_failed`，检查服务器工作区冲突后重试。

- [ ] **Step 3: 部署后验证**

```bash
sleep 8
CODE=$(cd /home/admin/stock-trading-all && .venv/bin/python -c "import sqlite3; c=sqlite3.connect('data/stocktool.db'); print(c.execute(\"select code from watchlist where tags like '%holding%' limit 1\").fetchone()[0])")
curl -s "http://localhost:8000/api/v1/analysis/livermore?code=$CODE" | .venv/bin/python -m json.tool | head -25
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
```

Expected: livermore 返回 200 且含 `pivot`/`state`/`ladder` 字段；`/` 返回 200（新前端已构建部署）。

---

## Self-Review 记录

- **Spec 覆盖**：计算口径→Task 1；模型/迁移/stocks API→Task 2；端点+缓存→Task 3；前端类型/客户端→Task 4；迷你 K 线 markLine→Task 5+6；浮层组件→Task 6；每行按钮（桌面+移动）→Task 7；水印→Task 8；部署→Task 9。无缺口。
- **类型一致性**：后端 `params`/`ladder`/`holding`/`state` 键名与前端 `LivermoreResponse` 逐字段对齐；`setStockHolding`/`fetchLivermore` 命名在 Task 4 定义、Task 6 使用一致；KlineChart `markLines` prop 在 Task 5 定义、Task 6 使用一致。
