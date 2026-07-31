# ETF 支持实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有个股分析系统中新增 A 股 ETF 全功能支持，通过 `security_type` 字段区分类型，数据源/API/前端按类型自动适配。

**Architecture:** 扩展现有代码而非新建平行系统。数据源层通过代码前缀检测 ETF 并调用 akshare 的 `fund_etf_*` 函数；Watchlist 表新增 `security_type` 列；API 返回数据带类型标记；前端根据类型条件渲染（ETF 隐藏财务指标、展示折溢价率/IOPV 等专用字段）。

**Tech Stack:** Python/FastAPI/SQLAlchemy/akshare, React/TypeScript/AntD/Zustand

---

### Task 1: 数据源 — 前缀函数修复 + ETF 检测

**Files:**
- Modify: `backend/data_sources/akshare.py`

- [ ] **Step 1: 修复三个前缀函数以识别 ETF 代码**

在 `backend/data_sources/akshare.py` 的 `AkshareDataSource` 类中，修改以下三个静态方法：

`_exchange_prefix`（约第 73 行）：
```python
@staticmethod
def _exchange_prefix(code: str) -> str:
    """推断交易所前缀：5/60/68xxxx → sh，0/3/15/16/18xxxx → sz"""
    if code.startswith(("5", "60", "68")):
        return "sh"
    return "sz"
```

`_em_secid`（约第 163 行）：
```python
@staticmethod
def _em_secid(code: str) -> str:
    """6 位代码 → 东方财富 push2 secid（1=沪，0=深）。"""
    return f"{'1' if code.startswith(('5', '60', '68', '11', '13')) else '0'}.{code}"
```

`_tencent_symbol`（约第 199 行）：
```python
@staticmethod
def _tencent_symbol(code: str) -> str:
    """6 位代码 → 腾讯股票接口 symbol（sh/sz 前缀）。"""
    return f"{'sh' if code.startswith(('5', '60', '68')) else 'sz'}{code}"
```

- [ ] **Step 2: 添加 `_is_etf` 辅助方法**

在 `AkshareDataSource` 类中新增静态方法（放在 `_exchange_prefix` 后面）：

```python
@staticmethod
def _is_etf(code: str) -> bool:
    """检测代码是否为 A 股 ETF（含 LOF）。"""
    return code.startswith(("51", "56", "58", "159", "16", "18"))
```

- [ ] **Step 3: 验证语法正确**

Run: `python -c "from backend.data_sources.akshare import AkshareDataSource; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/data_sources/akshare.py
git commit -m "fix(datasource): 修复前缀函数以识别 ETF 代码（5xxxxx→沪, 159xxx→深）"
```

---

### Task 2: 数据源 — ETF K 线支持

**Files:**
- Modify: `backend/data_sources/akshare.py`

- [ ] **Step 1: 新增 `_get_etf_kline` 方法**

在 `AkshareDataSource` 类中，`get_kline` 方法之前添加：

```python
def _get_etf_kline(self, code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
    """ETF K 线：日/周/月线通过 fund_etf_hist_em，分钟线通过 fund_etf_hist_min_em。"""
    import akshare as ak
    freq = PERIOD_MAP.get(period, "daily")

    if period in ("daily", "weekly", "monthly"):
        try:
            df = ak.fund_etf_hist_em(
                symbol=code,
                period=freq,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )
            if df is None or df.empty:
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "最高": "high",
                "最低": "low", "收盘": "close", "成交量": "volume",
            })
            cols = ["date", "open", "high", "low", "close", "volume"]
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[[c for c in cols if c in df.columns]]
        except Exception:
            logger.exception("ETF kline failed for code=%s period=%s", code, period)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    # 分钟线
    try:
        minute_period = {"60min": "60", "30min": "30", "15min": "15"}.get(period, "5")
        df = ak.fund_etf_hist_min_em(
            symbol=code,
            period=minute_period,
            start_date=f"{start_date} 09:30:00",
            end_date=f"{end_date} 15:00:00",
            adjust="qfq",
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "最高": "high",
            "最低": "low", "收盘": "close", "成交量": "volume",
        })
        cols = ["date", "open", "high", "low", "close", "volume"]
        df["date"] = pd.to_datetime(df["date"])
        return df[[c for c in cols if c in df.columns]]
    except Exception:
        logger.exception("ETF minute kline failed for code=%s period=%s", code, period)
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
```

- [ ] **Step 2: 修改 `get_kline` 方法添加 ETF 分支**

在 `get_kline` 方法开头（`try:` 之前）添加：

```python
def get_kline(self, code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
    if self._is_etf(code):
        return self._get_etf_kline(code, period, start_date, end_date)
    try:
        # ... 现有股票逻辑保持不变 ...
```

（即把现有的 `try:` 块整体放在 `else` 分支或直接跟在 `if` 后面用 early return 模式。）

- [ ] **Step 3: Commit**

```bash
git add backend/data_sources/akshare.py
git commit -m "feat(datasource): ETF K线支持（fund_etf_hist_em / fund_etf_hist_min_em）"
```

---

### Task 3: 数据源 — ETF 搜索支持

**Files:**
- Modify: `backend/data_sources/akshare.py`

- [ ] **Step 1: 新增 ETF 名称索引缓存**

在 `AkshareDataSource` 类中，`_STOCK_INDEX_CACHE` 旁边添加：

```python
_ETF_INDEX_CACHE: dict = {"ts": 0.0, "rows": []}
_ETF_INDEX_TTL = 24 * 3600.0
```

- [ ] **Step 2: 新增 `_etf_name_index` 方法**

```python
def _etf_name_index(self) -> list[tuple[str, str]]:
    """全量 ETF (code, name) 列表缓存，24h TTL。"""
    import akshare as ak
    now = time.monotonic()
    cache = self._ETF_INDEX_CACHE
    if cache["rows"] and now - cache["ts"] < self._ETF_INDEX_TTL:
        return cache["rows"]
    try:
        df = ak.fund_etf_spot_em()
    except Exception:
        logger.exception("akshare fund_etf_spot_em failed")
        return cache["rows"]
    if df is None or df.empty:
        return cache["rows"]
    rows: list[tuple[str, str]] = [
        (str(row["代码"]).zfill(6), str(row["名称"]))
        for _, row in df.iterrows()
    ]
    cache["ts"] = now
    cache["rows"] = rows
    return rows
```

- [ ] **Step 3: 修改 `search_stocks` 方法同时搜索 ETF**

```python
def search_stocks(self, keyword: str) -> list[dict]:
    kw = (keyword or "").strip()
    if not kw:
        return []
    results: list[dict] = []
    try:
        # 搜索股票
        rows = self._stock_name_index()
        if rows:
            matched = rank_stock_matches(rows, kw, limit=20)
            for code, name in matched:
                results.append({"code": code, "name": name, "market": "A", "security_type": "stock"})
        # 搜索 ETF
        etf_rows = self._etf_name_index()
        if etf_rows:
            etf_matched = rank_stock_matches(etf_rows, kw, limit=10)
            for code, name in etf_matched:
                results.append({"code": code, "name": name, "market": "A", "security_type": "etf"})
        return results
    except Exception:
        logger.exception("akshare search_stocks failed for keyword=%r", kw)
        return []
```

- [ ] **Step 4: Commit**

```bash
git add backend/data_sources/akshare.py
git commit -m "feat(datasource): ETF 搜索支持（拼音匹配 ETF 名称）"
```

---

### Task 4: 数据源 — ETF 基本面

**Files:**
- Modify: `backend/data_sources/akshare.py`

- [ ] **Step 1: 在 `get_fundamentals` 方法开头添加 ETF 分支**

```python
def get_fundamentals(self, code: str) -> dict:
    if self._is_etf(code):
        return self._get_etf_fundamentals(code)
    # ... 现有股票逻辑保持不变 ...
```

- [ ] **Step 2: 新增 `_get_etf_fundamentals` 方法**

```python
def _get_etf_fundamentals(self, code: str) -> dict:
    """ETF 基本面：IOPV、折溢价率、份额、跟踪指数等。"""
    import akshare as ak
    result: dict = {
        "code": code,
        "name": "",
        "price": None,
        "change_pct": None,
        "iopv": None,
        "discount_rate": None,
        "total_size": None,
        "total_market_cap": None,
        "tracking_index": "",
        "management_fee": None,
        "listing_date": "",
        "as_of": date.today().isoformat(),
    }

    # 行情数据：EM push2 单股 + 腾讯兜底
    em = self._em_single_quote(code)
    qt = self._tencent_quote(code)

    if qt:
        result["name"] = qt[1] or ""
        price = _to_float(qt[3])
        if price is not None and price > 0:
            result["price"] = price
        cp = _to_float(qt[32]) if len(qt) > 32 else None
        if cp is not None:
            result["change_pct"] = cp
        ts = qt[30] if len(qt) > 30 else ""
        if ts and len(ts) >= 8 and ts[:8].isdigit():
            result["as_of"] = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"

    if em:
        if not result["name"]:
            result["name"] = str(em.get("f58") or "")
        if result["price"] is None:
            price = _to_float(em.get("f43"))
            if price is not None and price > 0:
                result["price"] = price
        if result["change_pct"] is None:
            cp = _to_float(em.get("f170"))
            if cp is not None:
                result["change_pct"] = cp
        tmc = _to_float(em.get("f116"))
        if tmc is not None:
            result["total_market_cap"] = tmc

    # ETF 专用字段：从 fund_etf_spot_em 全量表按代码查找
    try:
        df = ak.fund_etf_spot_em()
        if df is not None and not df.empty and "代码" in df.columns:
            row = df[df["代码"] == code]
            if not row.empty:
                r = row.iloc[0]
                if not result["name"]:
                    result["name"] = str(r.get("名称") or "")
                result["iopv"] = _to_float(r.get("IOPV实时估值"))
                result["discount_rate"] = _to_float(r.get("基金折价率"))
                result["total_size"] = _to_float(r.get("最新份额"))
                # 总规模：份额 × IOPV（如果都有值）
                if result["total_size"] is not None and result["iopv"] is not None:
                    result["total_market_cap"] = result["total_size"] * result["iopv"]
    except Exception:
        logger.exception("ETF spot fetch failed for %s", code)

    # 上市日期兜底：从交易所份额表获取
    if not result["listing_date"]:
        try:
            if code.startswith(("51", "56", "58")):
                sse = ak.fund_etf_scale_sse()
                if sse is not None and not sse.empty:
                    row = sse[sse["代码"] == code] if "代码" in sse.columns else None
                    if row is not None and not row.empty:
                        result["listing_date"] = str(row.iloc[0].get("上市日期", "") or "")
            else:
                szse = ak.fund_etf_scale_szse()
                if szse is not None and not szse.empty:
                    row = szse[szse["代码"] == code] if "代码" in szse.columns else None
                    if row is not None and not row.empty:
                        result["listing_date"] = str(row.iloc[0].get("上市日期", "") or "")
        except Exception:
            logger.exception("ETF listing date fetch failed for %s", code)

    # 名称兜底
    if not result["name"]:
        quote = self.get_realtime_quote(code)
        result["name"] = quote.get("name", "")

    return result
```

- [ ] **Step 3: Commit**

```bash
git add backend/data_sources/akshare.py
git commit -m "feat(datasource): ETF 基本面支持（IOPV/折溢价率/份额/跟踪指数）"
```

---

### Task 5: 数据源 — ETF 条件选股支持

**Files:**
- Modify: `backend/data_sources/akshare.py`
- Modify: `backend/data_sources/base.py`

- [ ] **Step 0: base.py 的 `screen_stocks` 签名新增 `security_type` 参数**

在 `backend/data_sources/base.py` 的 `screen_stocks` 方法签名中添加：

```python
def screen_stocks(
    self,
    sort_by: str = "amount",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50,
    codes: list[str] | None = None,
    security_type: str = "stock",  # 新增
) -> dict:
```

- [ ] **Step 1: 修改 `screen_stocks` 方法支持 ETF FS**

在 `screen_stocks` 方法中，当 `security_type` 参数为 `etf` 时使用 ETF 市场筛选：

```python
# 在类常量区域添加 ETF 筛选 FS
_ETF_SCREEN_FS = "b:MK0021,b:MK0022,b:MK0023,b:MK0024"

def screen_stocks(
    self,
    sort_by: str = "amount",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50,
    codes: list[str] | None = None,
    security_type: str = "stock",
) -> dict:
    fid = self._SCREEN_FIELD_MAP.get(sort_by, "f6")
    po = 1 if sort_order == "desc" else 0

    if codes:
        # codes 模式：不需要 FS，按 secid 批量查
        secids = ",".join(self._em_secid(c) for c in codes)
        payload = self._em_get(
            "/api/qt/ulist.np/get",
            {"secids": secids, "fields": self._SCREEN_FIELDS_STR, "fltt": "2", "invt": "2"},
            timeout=8,
        )
        if payload is None:
            return {"results": [], "total": 0}
        data = (payload or {}).get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        rows = [r for r in diff if isinstance(r, dict)]
        total = len(rows)
    else:
        fs = self._ETF_SCREEN_FS if security_type == "etf" else self._SCREEN_FS
        pz = max(page_size, 100)
        rows = self._em_clist(fs, self._SCREEN_FIELDS_STR, pn=1, pz=5000, fid=fid, po=po)
        total = len(rows)

    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("f12") or "")
        if not code:
            continue
        tmc = _to_float(row.get("f20"))
        results.append({
            "code": code,
            "name": str(row.get("f14") or ""),
            "price": _to_float(row.get("f2")),
            "change_pct": _to_float(row.get("f3")),
            "pe": _to_float(row.get("f9")),
            "pb": _to_float(row.get("f23")),
            "total_market_cap": tmc,
            "total_market_cap_yi": round(tmc / 1e8, 2) if tmc else None,
            "float_market_cap": _to_float(row.get("f21")),
            "turnover": _to_float(row.get("f8")),
            "volume_ratio": _to_float(row.get("f10")),
            "amplitude": _to_float(row.get("f7")),
            "amount": _to_float(row.get("f6")),
            "industry": str(row.get("f100") or ""),
        })

    return {"results": results, "total": total}
```

- [ ] **Step 2: Commit**

```bash
git add backend/data_sources/akshare.py
git commit -m "feat(datasource): ETF 条件选股支持（ETF 市场板块 FS）"
```

---

### Task 6: 数据库 — Watchlist 新增 security_type 列

**Files:**
- Modify: `backend/models/models.py`
- Modify: `backend/database.py`

- [ ] **Step 1: SQLAlchemy 模型新增字段**

在 `backend/models/models.py` 的 `Watchlist` 类中添加（`tags` 字段后面）：

```python
security_type = Column(String(10), default="stock")
```

- [ ] **Step 2: 数据库迁移**

在 `backend/database.py` 的 `_migrate_sqlite` 函数中添加（`alert_diff_pct` 迁移块后面）：

```python
if cols and "security_type" not in col_names:
    conn.execute(text("ALTER TABLE watchlist ADD COLUMN security_type VARCHAR(10) DEFAULT 'stock'"))
```

- [ ] **Step 3: 验证迁移**

Run: `python -c "from backend.database import init_db; init_db(); print('OK')"`
Expected: `OK`（无报错）

- [ ] **Step 4: Commit**

```bash
git add backend/models/models.py backend/database.py
git commit -m "feat(db): watchlist 表新增 security_type 字段（stock/etf）"
```

---

### Task 7: API — stocks 端点适配 security_type

**Files:**
- Modify: `backend/api/stocks.py`

- [ ] **Step 1: `_stock_dict` 函数新增字段**

```python
def _stock_dict(r: Watchlist) -> dict:
    return {
        "id": r.id,
        "code": r.code,
        "name": r.name,
        "market": r.market,
        "security_type": getattr(r, "security_type", "stock") or "stock",
        "group_id": r.group_id,
        "tags": _parse_tags(r.tags),
        "target_price": r.target_price,
        "alert_diff_pct": r.alert_diff_pct,
    }
```

- [ ] **Step 2: `add_stock` 端点新增参数**

```python
@router.post("")
def add_stock(
    code: str = Query(...),
    name: str = Query(""),
    market: str = Query("A"),
    security_type: str = Query("stock"),
    group_id: int | None = Query(None),
    tags: str = Query("", description="逗号分隔的系统标签，如 watching 或 holding,watching"),
):
    db: Session = next(get_db())
    try:
        existing = db.execute(
            select(Watchlist).where(Watchlist.code == code, Watchlist.market == market)
        ).scalar()
        if existing:
            raise HTTPException(status_code=409, detail=f"Stock {code} already in watchlist")
        if group_id is not None:
            g = db.get(WatchlistGroup, group_id)
            if not g:
                raise HTTPException(status_code=400, detail="目标分组不存在")
        initial_tags = _serialize_tags(_parse_tags(tags))
        stock = Watchlist(
            code=code, name=name, market=market,
            security_type=security_type,
            group_id=group_id, tags=initial_tags,
        )
        db.add(stock)
        db.commit()
        db.refresh(stock)
        return _stock_dict(stock)
    finally:
        db.close()
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/stocks.py
git commit -m "feat(api): stocks 端点支持 security_type 字段"
```

---

### Task 8: API — screener/condition 端点适配 ETF

**Files:**
- Modify: `backend/api/screener.py`

- [ ] **Step 1: 新增 ETF 筛选参数**

在 `condition_screen_stocks` 函数签名中添加：

```python
@router.get("/condition")
def condition_screen_stocks(
    pe_min: float | None = Query(None),
    pe_max: float | None = Query(None),
    pb_min: float | None = Query(None),
    pb_max: float | None = Query(None),
    market_cap_min: float | None = Query(None, description="总市值下限（亿元）"),
    market_cap_max: float | None = Query(None, description="总市值上限（亿元）"),
    change_pct_min: float | None = Query(None),
    change_pct_max: float | None = Query(None),
    turnover_min: float | None = Query(None),
    turnover_max: float | None = Query(None),
    volume_ratio_min: float | None = Query(None),
    volume_ratio_max: float | None = Query(None),
    amplitude_min: float | None = Query(None),
    amplitude_max: float | None = Query(None),
    amount_min: float | None = Query(None, description="成交额下限（亿元）"),
    amount_max: float | None = Query(None, description="成交额上限（亿元）"),
    discount_rate_min: float | None = Query(None, description="ETF 折溢价率下限"),
    discount_rate_max: float | None = Query(None, description="ETF 折溢价率上限"),
    size_min: float | None = Query(None, description="ETF 规模下限（亿份）"),
    size_max: float | None = Query(None, description="ETF 规模上限（亿份）"),
    sort_by: str = Query("amount"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    scope: str = Query("all", description="all=全市场 / watchlist=仅自选股 / all_etf=全市场ETF"),
    group_id: int | None = Query(None),
    tag: str | None = Query(None),
):
```

- [ ] **Step 2: 在筛选逻辑中处理 ETF scope**

在函数体中 `has_filter` 检查之前，修改 scope 解析逻辑：

```python
    security_type = "etf" if scope == "all_etf" else "stock"
    codes: list[str] | None = None
    if scope == "watchlist":
        db: Session = next(get_db())
        try:
            stmt = select(Watchlist)
            if group_id is not None:
                stmt = stmt.where(Watchlist.group_id == group_id)
            rows = db.execute(stmt).scalars().all()
            tag_norm = tag.strip() if tag else None
            if tag_norm and tag_norm in SYSTEM_TAGS:
                rows = [r for r in rows if tag_norm in _parse_tags(r.tags)]
            codes = [r.code for r in rows]
            if not codes:
                return {"results": [], "total": 0, "page": page, "page_size": page_size}
        finally:
            db.close()

    ds = get_data_source()
    raw = ds.screen_stocks(
        sort_by=sort_by,
        sort_order=sort_order,
        page=1,
        page_size=5000,
        codes=codes,
        security_type=security_type,
    )
    items = raw.get("results", [])

    has_filter = any(v is not None for v in [
        pe_min, pe_max, pb_min, pb_max, market_cap_min, market_cap_max,
        change_pct_min, change_pct_max, turnover_min, turnover_max,
        volume_ratio_min, volume_ratio_max, amplitude_min, amplitude_max,
        amount_min, amount_max, discount_rate_min, discount_rate_max,
        size_min, size_max,
    ])
```

- [ ] **Step 3: 在筛选循环中添加 ETF 专用条件**

在 `has_filter` 块的筛选循环中，现有条件之后、`filtered.append(item)` 之前添加：

```python
            if discount_rate_min is not None or discount_rate_max is not None:
                if not _in_range(item.get("discount_rate"), discount_rate_min, discount_rate_max):
                    continue
            if size_min is not None or size_max is not None:
                # total_market_cap 对 ETF 是总规模（份额×净值），单位元
                size_yi = item.get("total_market_cap")
                if size_yi is not None:
                    size_yi = size_yi / 1e8  # 转为亿份当量
                if not _in_range(size_yi, size_min, size_max):
                    continue
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/screener.py
git commit -m "feat(api): 条件选股新增 ETF scope 及折溢价率/规模筛选"
```

---

### Task 9: API — 新增 ETF 列表端点

**Files:**
- Modify: `backend/api/market.py`

- [ ] **Step 1: 新增 `GET /api/v1/market/etf-list` 端点**

在 `backend/api/market.py` 末尾添加：

```python
@router.get("/etf-list")
def get_etf_list(
    sort_by: str = Query("amount", description="排序字段：amount/change_pct/price/volume"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """ETF 全量列表，支持排序和分页。"""
    ds = get_data_source()
    raw = ds.screen_stocks(
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
        security_type="etf",
    )
    return raw
```

- [ ] **Step 2: 验证端点可访问**

Run: `curl -s http://localhost:8000/api/v1/market/etf-list?page_size=5 | python -m json.tool | head -20`
Expected: 返回 ETF 列表 JSON

- [ ] **Step 3: Commit**

```bash
git add backend/api/market.py
git commit -m "feat(api): 新增 ETF 列表端点 GET /market/etf-list"
```

---

### Task 10: 后端启动验证

**Files:**
- None（验证步骤）

- [ ] **Step 1: 启动后端并验证 ETF 搜索**

```bash
# 终端 1：启动后端
uvicorn backend.main:app --reload --port 8000 &

# 终端 2：测试 ETF 搜索
curl -s "http://localhost:8000/api/v1/stocks/search?q=科创50" | python -m json.tool | head -30
```
Expected: 返回结果中包含 `"security_type": "etf"` 的条目（如 588000 科创50ETF）

- [ ] **Step 2: 测试 ETF K线**

```bash
curl -s "http://localhost:8000/api/v1/market/kline?code=510050&period=daily&start=2026-06-01&end=2026-07-31" | python -m json.tool | head -20
```
Expected: 返回上证50ETF 的 K线数据

- [ ] **Step 3: 测试 ETF 基本面**

```bash
curl -s "http://localhost:8000/api/v1/market/fundamentals?code=510050" | python -m json.tool
```
Expected: 返回包含 `iopv`、`discount_rate` 等 ETF 专用字段

- [ ] **Step 4: 测试添加 ETF 到自选**

```bash
curl -s -X POST "http://localhost:8000/api/v1/stocks?code=510050&name=上证50ETF&security_type=etf" | python -m json.tool
```
Expected: 成功添加，返回 `"security_type": "etf"`

- [ ] **Step 5: Commit（如有 CI 配置调整）**

```bash
# 仅如有文件变更
git add -A && git commit -m "chore: 后端 ETF 端到端验证通过"
```

---

### Task 11: 前端 — 类型定义更新

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: 新增 SecurityType 和 ETF 基本面类型**

在 `frontend/src/types/index.ts` 末尾添加：

```typescript
export type SecurityType = 'stock' | 'etf';
```

在 `StockInfo` 接口中添加 `security_type` 字段：

```typescript
export interface StockInfo {
  id?: number;
  code: string;
  name: string;
  market: string;
  security_type?: SecurityType;  // 新增
  group_id?: number | null;
  tags?: string[];
  target_price?: number | null;
  alert_diff_pct?: number | null;
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无新增类型错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(frontend): 类型定义新增 SecurityType 和 EtfFundamentals"
```

---

### Task 12: 前端 — API 客户端适配

**Files:**
- Modify: `frontend/src/api/market.ts`
- Modify: `frontend/src/api/screener.ts`

- [ ] **Step 1: market.ts 新增 ETF 列表接口和 Fundamentals 扩展**

```typescript
// 在 fetchFundamentals 下方新增：

export async function fetchEtfList(params: {
  sort_by?: string;
  sort_order?: string;
  page?: number;
  page_size?: number;
}): Promise<{ results: ConditionScreenerResult[]; total: number }> {
  const { data } = await api.get('/market/etf-list', { params });
  return data;
}
```

- [ ] **Step 2: screener.ts 新增 ETF 条件参数**

在 `ConditionScreenerParams` 接口中添加：

```typescript
export interface ConditionScreenerParams {
  // ... 现有字段
  discount_rate_min?: number;
  discount_rate_max?: number;
  size_min?: number;
  size_max?: number;
}
```

- [ ] **Step 3: 验证编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/market.ts frontend/src/api/screener.ts
git commit -m "feat(frontend): API 客户端新增 ETF 列表和筛选参数"
```

---

### Task 13: 前端 — 自选股搜索标记 ETF

**Files:**
- Modify: `frontend/src/pages/Watchlist.tsx`
- Modify: `frontend/src/components/StockSearchInput.tsx`

- [ ] **Step 1: StockSearchInput 显示 ETF 标记**

在 `StockSearchInput.tsx` 的下拉渲染中，为 ETF 项添加标签。找到渲染搜索结果的 `renderItem` 部分，在名称后添加：

```tsx
// 在搜索结果项的 Space 中，{item.name} 后面添加：
{item.security_type === 'etf' && (
  <Tag color="orange" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>ETF</Tag>
)}
```

- [ ] **Step 2: Watchlist 表格 ETF 标记**

在 `Watchlist.tsx` 桌面端 `columns` 的定义中，在名称列的 render 函数里已有 `StockTagBadges`，在其旁边添加 ETF 标签：

```tsx
// 在 <StockTagBadges tags={record.tags} size="mini" /> 后面添加：
{record.security_type === 'etf' && (
  <Tag color="orange" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', marginInlineEnd: 0 }}>ETF</Tag>
)}
```

移动端 `renderMobileList` 中同理，在名称旁的 `StockTagBadges` 后添加。

- [ ] **Step 3: 添加 stock 时的 security_type 传递**

在 `handleAdd` 函数中：

```typescript
const handleAdd = async (stock: StockInfo) => {
  try {
    await addStock(
      stock.code, stock.name, stock.market || 'A',
      addTargetGroup, ['watching'],
      stock.security_type || 'stock',  // 新增参数
    );
    // ...
  }
};
```

需要同步更新 `addStock` API 函数签名（`frontend/src/api/stocks.ts`），添加 `security_type` 参数：

```typescript
export async function addStock(
  code: string,
  name: string,
  market: string = 'A',
  groupId?: number | null,
  tags?: string[],
  securityType: string = 'stock',
): Promise<StockInfo> {
  const { data } = await api.post<StockInfo>('/stocks', null, {
    params: { code, name, market, security_type: securityType, group_id: groupId, tags: tags?.join(',') },
  });
  return data;
}
```

- [ ] **Step 4: 验证编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Watchlist.tsx frontend/src/components/StockSearchInput.tsx frontend/src/api/stocks.ts
git commit -m "feat(frontend): 自选股搜索和列表显示 ETF 标记"
```

---

### Task 14: 前端 — 详情页条件渲染

**Files:**
- Modify: `frontend/src/pages/StockDetail.tsx`

- [ ] **Step 1: 获取 security_type**

在 `StockDetail` 组件中，从后端获取 security_type。在 `fetchQuote` 之后新增状态：

```typescript
const [securityType, setSecurityType] = useState<SecurityType>('stock');
```

在已有的 `fetchQuote` 调用之后，添加获取 security_type 的逻辑。可以在添加 ETF 到自选时从前端 state 获取，或者从 watchlist API 推断。最简单的方式是：在 `useEffect` 中调用 `/api/v1/stocks` 查一下该 code 是否在自选中。

但更简单的方式是：直接从行情数据无法获取 security_type。我们改为在页面加载时从 URL 跳转携带，或者通过代码前缀推断（前端 `_is_etf`）：

```typescript
function isEtfCode(code: string): boolean {
  return /^(51|56|58|159|16|18)/.test(code);
}

// 在组件中
const isEtf = isEtfCode(code);
```

这比增加一次 API 调用更轻量。

- [ ] **Step 2: 条件隐藏财务指标 Tab**

修改 `items` 数组，对 ETF 过滤：

```typescript
items={[
  {
    key: 'signal',
    label: (
      <Space size={6}>
        <ThunderboltOutlined />
        <span>信号分析</span>
      </Space>
    ),
    children: (/* 现有信号分析内容 */),
  },
  // 仅个股显示财务指标
  ...(isEtf ? [] : [{
    key: 'financials' as AnalysisTabKey,
    label: (
      <Space size={6}>
        <FundOutlined />
        <span>财务指标</span>
      </Space>
    ),
    children: <FinancialHistoryTable code={code} />,
  }]),
  {
    key: 'ai',
    label: (
      <Space size={6}>
        <ExperimentOutlined />
        <span>AI 分析</span>
      </Space>
    ),
    children: (
      <TradingAgentsPanel code={code} stockName={stockName} />
    ),
  },
]}
```

- [ ] **Step 3: 将 isEtf 传递给 FundamentalsCard**

```tsx
<FundamentalsCard code={code} isEtf={isEtf} />
```

- [ ] **Step 4: 页面标题适配**

```typescript
useEffect(() => {
  const prev = document.title;
  if (code) {
    const label = isEtf ? 'ETF分析' : '股票分析';
    document.title = stockName ? `${code} ${stockName} · ${label}` : `${code} · ${label}`;
  }
  return () => {
    document.title = prev;
  };
}, [code, stockName, isEtf]);
```

- [ ] **Step 5: 验证编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/StockDetail.tsx
git commit -m "feat(frontend): 详情页 ETF 条件渲染（隐藏财务指标 Tab）"
```

---

### Task 15: 前端 — FundamentalsCard ETF 模式

**Files:**
- Modify: `frontend/src/components/FundamentalsCard.tsx`

- [ ] **Step 1: 接收 isEtf prop 并切换展示**

修改 `Props` 接口：

```typescript
interface Props {
  code: string;
  isEtf?: boolean;
}
```

- [ ] **Step 2: ETF 基本面数据获取**

ETF 基本面复用同一个 `fetchFundamentals` API（后端已适配返回 ETF 字段）。新增类型：

```typescript
// 在组件内定义（或从 types 导入）
interface EtfFundamentalsData {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  iopv: number | null;
  discount_rate: number | null;
  total_size: number | null;
  total_market_cap: number | null;
  tracking_index: string;
  management_fee: number | null;
  listing_date: string;
  as_of: string | null;
}
```

数据类型用 `Fundamentals | EtfFundamentalsData`。

- [ ] **Step 3: 条件渲染 Descriptions**

```tsx
{isEtf ? (
  <Descriptions column={{ xs: 2, sm: 3, md: 4, lg: 6 }} size="small" colon={false}>
    <Descriptions.Item label="最新价">
      <Typography.Text strong>
        {data?.price != null ? data.price.toFixed(3) : '—'}
      </Typography.Text>
    </Descriptions.Item>
    <Descriptions.Item label="涨跌幅">
      <Typography.Text strong style={{ color: changeColor }}>
        {formatPct(change)}
      </Typography.Text>
    </Descriptions.Item>
    <Descriptions.Item label="IOPV">
      {data?.iopv != null ? (data as any).iopv.toFixed(3) : '—'}
    </Descriptions.Item>
    <Descriptions.Item label="折溢价率">
      {formatPct((data as any)?.discount_rate)}
    </Descriptions.Item>
    {!isMobile && <Descriptions.Item label="最新份额">{formatBigYuan((data as any)?.total_size)}</Descriptions.Item>}
    {!isMobile && <Descriptions.Item label="总规模">{formatBigYuan(data?.total_market_cap)}</Descriptions.Item>}
    {!isMobile && <Descriptions.Item label="跟踪指数">{(data as any)?.tracking_index || '—'}</Descriptions.Item>}
    {!isMobile && <Descriptions.Item label="上市日期">{data?.listing_date || '—'}</Descriptions.Item>}
  </Descriptions>
) : (
  /* 现有个股 Descriptions 保持不变 */
)}
```

- [ ] **Step 4: 标题适配**

```typescript
const titleNode = (
  <Space size={8}>
    <span>{isEtf ? 'ETF 指标' : '关键指标'}</span>
    {!isEtf && data?.industry && <Tag color="blue">{(data as Fundamentals).industry}</Tag>}
    {isEtf && <Tag color="orange">ETF</Tag>}
    {!isMobile && data?.as_of && (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        数据日期 {data.as_of}
      </Typography.Text>
    )}
  </Space>
);
```

- [ ] **Step 5: 验证编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/FundamentalsCard.tsx
git commit -m "feat(frontend): FundamentalsCard 新增 ETF 模式（IOPV/折溢价率/份额）"
```

---

### Task 16: 前端 — 筛选器 ETF 模式

**Files:**
- Modify: `frontend/src/pages/Screener.tsx`

- [ ] **Step 1: ConditionScreenerTab 新增 security_type 状态**

在 `ConditionScreenerTab` 组件中添加：

```typescript
const [securityType, setSecurityType] = useState<'stock' | 'etf'>('stock');
```

- [ ] **Step 2: scope 逻辑适配**

修改 scope 的 Segmented：

```typescript
<Segmented
  size="small"
  value={securityType === 'etf' ? 'all_etf' : scope}
  onChange={(v) => {
    if (v === 'all_etf') {
      setSecurityType('etf');
      setScope('all');
    } else {
      setSecurityType('stock');
      setScope(v as 'all' | 'watchlist');
    }
  }}
  options={[
    { label: '全部A股', value: 'all' },
    { label: '全部ETF', value: 'all_etf' },
    { label: '自选股', value: 'watchlist' },
  ]}
/>
```

- [ ] **Step 3: 筛选条件行条件渲染**

在 PE/PB/市值筛选行外层包裹条件：

```tsx
{securityType === 'stock' && (
  <>
    {/* PE 筛选 */}
    <div>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
        市盈率(PE)
      </Typography.Text>
      <Space size={0}>
        <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={peMin} onChange={setPeMin} />
        {separator}
        <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={peMax} onChange={setPeMax} />
      </Space>
    </div>
    {/* PB 筛选 */}
    <div>...</div>
    {/* 总市值筛选 */}
    <div>...</div>
  </>
)}
```

ETF 专用筛选行：

```tsx
{securityType === 'etf' && (
  <>
    <div>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
        折溢价率(%)
      </Typography.Text>
      <Space size={0}>
        <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={discountRateMin} onChange={setDiscountRateMin} />
        {separator}
        <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={discountRateMax} onChange={setDiscountRateMax} />
      </Space>
    </div>
    <div>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
        规模（亿）
      </Typography.Text>
      <Space size={0}>
        <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={sizeMin} onChange={setSizeMin} />
        {separator}
        <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={sizeMax} onChange={setSizeMax} />
      </Space>
    </div>
  </>
)}
```

（需要新增对应的 state：`discountRateMin`, `discountRateMax`, `sizeMin`, `sizeMax`）

- [ ] **Step 4: doSearch 传递 ETF 参数**

在 `doSearch` 函数中：

```typescript
if (discountRateMin != null) params.discount_rate_min = discountRateMin;
if (discountRateMax != null) params.discount_rate_max = discountRateMax;
if (sizeMin != null) params.size_min = sizeMin;
if (sizeMax != null) params.size_max = sizeMax;

// scope 适配
if (securityType === 'etf') {
  params.scope = 'all_etf';
}
```

- [ ] **Step 5: 结果表格列适配**

PE/PB/行业 列在 ETF 模式下显示 "—"：

```typescript
{
  title: 'PE',
  dataIndex: 'pe',
  width: 70,
  sorter: securityType === 'stock',  // ETF 模式不可排序
  render: (v: number | null) => {
    if (securityType === 'etf') return '—';
    return v != null ? v.toFixed(2) : '-';
  },
},
// PB 同理
```

- [ ] **Step 6: 重置逻辑适配**

在 `handleReset` 中添加 ETF 状态重置：

```typescript
setDiscountRateMin(null);
setDiscountRateMax(null);
setSizeMin(null);
setSizeMax(null);
setSecurityType('stock');
```

- [ ] **Step 7: 验证编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Screener.tsx
git commit -m "feat(frontend): 筛选器新增 ETF 模式（折溢价率/规模筛选）"
```

---

### Task 17: 前端 — 版本水印更新

**Files:**
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: 更新版本号**

```tsx
{/* 第 55 行 */}
v.26.07.31_9
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/AppLayout.tsx
git commit -m "chore: bump version watermark to v.26.07.31_9"
```

---

### Task 18: 端到端验证

**Files:**
- None（验证步骤）

- [ ] **Step 1: 构建前端**

```bash
cd frontend && npm run build
```
Expected: build 成功，无 TS 错误

- [ ] **Step 2: 启动完整应用**

```bash
# 终端 1: 后端
uvicorn backend.main:app --reload --port 8000

# 终端 2: 前端（可选，构建后已通过 FastAPI 服务）
# 访问 http://localhost:8000
```

- [ ] **Step 3: 手动验证清单**

1. 搜索 "科创50" → 结果中应出现 ETF 且标记为 `[ETF]`
2. 添加一个 ETF（如 510050）到自选 → 列表中出现且显示橙色 "ETF" 标签
3. 点击 ETF 进入详情页 → 页面标题显示 "ETF分析"，无「财务指标」Tab
4. 基本面卡片显示 IOPV、折溢价率等 ETF 指标
5. K线图和信号分析正常工作
6. 筛选器切换到「全部ETF」→ 显示折溢价率/规模筛选，PE/PB 隐藏
7. ETF 筛选能正常返回结果

- [ ] **Step 4: 记录发现的问题**

如有问题，创建 bug fix 任务；如无问题，流程完成。

---

### 实施顺序总结

```
Task 1  (前缀修复)         ──┐
Task 2  (ETF K线)           ├─ 数据源层（顺序依赖）
Task 3  (ETF 搜索)          │
Task 4  (ETF 基本面)        │
Task 5  (ETF 筛选器DS)     ─┘
Task 6  (DB 迁移)          ── 独立，可与 1-5 并行
Task 7  (API stocks)       ──┐
Task 8  (API screener)       ├─ API 层（依赖 1-6）
Task 9  (API etf-list)      ─┘
Task 10 (后端验证)          ── 依赖 1-9
Task 11 (类型定义)          ──┐
Task 12 (API 客户端)         ├─ 前端层（依赖 7-9）
Task 13 (搜索/自选)          │
Task 14 (详情页)             │
Task 15 (FundamentalsCard)   │
Task 16 (筛选器)             │
Task 17 (水印)              ─┘
Task 18 (端到端验证)        ── 依赖全部
```
