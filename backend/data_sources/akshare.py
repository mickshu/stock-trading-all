import logging
import time
from datetime import date
import requests
import pandas as pd
import akshare as ak
from backend.data_sources.base import BaseDataSource, PERIOD_MAP
from backend.data_sources.pinyin_search import rank_stock_matches

logger = logging.getLogger(__name__)


def _to_float(v) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


class AkshareDataSource(BaseDataSource):
    name = "akshare"

    # 全 A 股 (code, name) 列表缓存，避免每次搜索都打 akshare；24h TTL 足够。
    _STOCK_INDEX_CACHE: dict = {"ts": 0.0, "rows": []}
    _STOCK_INDEX_TTL = 24 * 3600.0

    _ETF_INDEX_CACHE: dict = {"ts": 0.0, "rows": []}
    _ETF_INDEX_TTL = 24 * 3600.0

    def _stock_name_index(self) -> list[tuple[str, str]]:
        now = time.monotonic()
        cache = self._STOCK_INDEX_CACHE
        if cache["rows"] and now - cache["ts"] < self._STOCK_INDEX_TTL:
            return cache["rows"]
        try:
            df = ak.stock_info_a_code_name()
        except Exception:
            logger.exception("akshare stock_info_a_code_name failed")
            return cache["rows"]
        if df is None or df.empty:
            return cache["rows"]
        if "名称" in df.columns:
            code_col, name_col = "代码", "名称"
        else:
            code_col, name_col = "code", "name"
        rows: list[tuple[str, str]] = [
            (str(row[code_col]).zfill(6), str(row[name_col]))
            for _, row in df.iterrows()
        ]
        cache["ts"] = now
        cache["rows"] = rows
        return rows

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

    @staticmethod
    def _exchange_prefix(code: str) -> str:
        """推断交易所前缀：5/60/68xxxx → sh，0/3/15/16/18xxxx → sz"""
        if code.startswith(("5", "60", "68")):
            return "sh"
        return "sz"

    @staticmethod
    def _is_etf(code: str) -> bool:
        """检测代码是否为 A 股 ETF（含 LOF）。"""
        return code.startswith(("51", "56", "58", "159", "16", "18"))

    def _get_kline_daily_fallback(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """使用 stock_zh_a_daily 作为日线数据的后备接口"""
        symbol = f"{self._exchange_prefix(code)}{code}"
        try:
            df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_date, end_date=end_date, adjust="qfq")
            if df is None or df.empty:
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            df = df.rename(columns={
                "成交量": "volume",
            })
            cols = ["date", "open", "high", "low", "close", "volume"]
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[[c for c in cols if c in df.columns]]
        except Exception:
            logger.exception("akshare daily fallback failed for code=%s", code)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    @staticmethod
    def _resample_ohlcv(daily_df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """把日线 OHLCV resample 成周/月线"""
        if daily_df is None or daily_df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = daily_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        out = df.resample(rule).agg(agg).dropna(subset=["close"]).reset_index()
        out["date"] = out["date"].dt.date
        return out[["date", "open", "high", "low", "close", "volume"]]

    def _get_kline_resampled_fallback(self, code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
        """周/月线后备：拉日线后 resample"""
        rule = {"weekly": "W-FRI", "monthly": "MS"}.get(period)
        if rule is None:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        daily = self._get_kline_daily_fallback(code, start_date, end_date)
        if daily.empty:
            return daily
        return self._resample_ohlcv(daily, rule)

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

    def get_kline(self, code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
        if self._is_etf(code):
            return self._get_etf_kline(code, period, start_date, end_date)
        try:
            freq = PERIOD_MAP.get(period, "daily")
            # akshare 要求 YYYYMMDD 格式，调用方传入的是 ISO YYYY-MM-DD
            ak_start = start_date.replace("-", "")
            ak_end = end_date.replace("-", "")
            df = ak.stock_zh_a_hist(symbol=code, period=freq, start_date=ak_start, end_date=ak_end, adjust="qfq")
            if df is None or df.empty:
                logger.warning("akshare get_kline empty for code=%s period=%s %s~%s", code, period, ak_start, ak_end)
                if period == "daily":
                    return self._get_kline_daily_fallback(code, start_date, end_date)
                if period in ("weekly", "monthly"):
                    return self._get_kline_resampled_fallback(code, period, start_date, end_date)
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "最高": "high",
                "最低": "low", "收盘": "close", "成交量": "volume"
            })
            cols = ["date", "open", "high", "low", "close", "volume"]
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[[c for c in cols if c in df.columns]]
        except Exception:
            logger.exception("akshare get_kline failed for code=%s period=%s", code, period)
            if period == "daily":
                return self._get_kline_daily_fallback(code, start_date, end_date)
            if period in ("weekly", "monthly"):
                return self._get_kline_resampled_fallback(code, period, start_date, end_date)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def _get_em_spot_row(self, code: str) -> dict | None:
        """从 EastMoney 实时行情表中取出单只股票的整行（含 PE/PB/总市值等字段）。"""
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty or "代码" not in df.columns:
                return None
            row = df[df["代码"] == code]
            if row.empty:
                return None
            return row.iloc[0].to_dict()
        except Exception:
            logger.exception("EastMoney spot fetch failed for %s", code)
            return None

    @staticmethod
    def _em_secid(code: str) -> str:
        """6 位代码 → 东方财富 push2 secid（1=沪，0=深）。"""
        return f"{'1' if code.startswith(('5', '60', '68', '11', '13')) else '0'}.{code}"

    # 东方财富 push2 主备 host：实时主机偶尔限流封 IP，延时镜像作为兜底。
    _EM_HOSTS: tuple = ("push2.eastmoney.com", "push2delay.eastmoney.com")
    _EM_HEADERS: dict = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }

    @classmethod
    def _em_get(cls, path: str, params: dict, timeout: float = 6.0) -> dict | None:
        """按 _EM_HOSTS 顺序请求东方财富 push2 接口；连接错误自动切到延时镜像。"""
        last_exc: Exception | None = None
        for host in cls._EM_HOSTS:
            try:
                resp = requests.get(
                    f"https://{host}{path}",
                    params=params,
                    headers=cls._EM_HEADERS,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json() or {}
            except Exception as e:
                last_exc = e
                continue
        if last_exc is not None:
            logger.warning("EastMoney %s failed on all hosts: %s", path, last_exc)
        return None

    @staticmethod
    def _tencent_symbol(code: str) -> str:
        """6 位代码 → 腾讯股票接口 symbol（sh/sz 前缀）。"""
        return f"{'sh' if code.startswith(('5', '60', '68')) else 'sz'}{code}"

    # 上交所/深交所基础信息表内存缓存：上市日期、所属行业；TTL 24h 已足够
    _LISTING_CACHE: dict = {"ts": 0.0, "sh": {}, "sz": {}}
    _LISTING_CACHE_TTL = 24 * 3600.0

    def _listing_lookup(self, code: str) -> dict:
        """从交易所基础信息表查上市日期/行业。失败返回空 dict。"""
        now = time.monotonic()
        cache = self._LISTING_CACHE
        if not cache["sh"] or now - cache["ts"] > self._LISTING_CACHE_TTL:
            try:
                sh = ak.stock_info_sh_name_code(symbol="主板A股")
                sh_kc = ak.stock_info_sh_name_code(symbol="科创板")
                cache_sh: dict[str, dict] = {}
                for df in (sh, sh_kc):
                    if df is None or df.empty:
                        continue
                    for _, row in df.iterrows():
                        cache_sh[str(row.get("证券代码", "")).zfill(6)] = {
                            "listing_date": str(row.get("上市日期", "") or ""),
                            "industry": "",
                        }
                cache["sh"] = cache_sh
            except Exception:
                logger.exception("Listing cache sh fetch failed")
            try:
                sz = ak.stock_info_sz_name_code(symbol="A股列表")
                cache_sz: dict[str, dict] = {}
                if sz is not None and not sz.empty:
                    for _, row in sz.iterrows():
                        cache_sz[str(row.get("A股代码", "")).zfill(6)] = {
                            "listing_date": str(row.get("A股上市日期", "") or ""),
                            "industry": str(row.get("所属行业", "") or ""),
                        }
                cache["sz"] = cache_sz
            except Exception:
                logger.exception("Listing cache sz fetch failed")
            cache["ts"] = now
        return cache["sh"].get(code) or cache["sz"].get(code) or {}

    def _tencent_quote(self, code: str) -> list[str] | None:
        """腾讯实时行情（qt.gtimg.cn）字段更丰富、连接极稳。返回按 ~ 切分的字段列表。

        关键索引（A 股）：
        1=名称, 3=最新价, 30=时间戳, 32=涨跌幅%, 38=换手率, 39=PE_TTM,
        44=流通市值(亿元), 45=总市值(亿元), 46=PB, 72=流通股(股), 73=总股本(股)
        """
        symbol = self._tencent_symbol(code)
        try:
            resp = requests.get(
                f"http://qt.gtimg.cn/q={symbol}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                    "Referer": "https://stockapp.finance.qq.com/",
                },
                timeout=4,
            )
            resp.raise_for_status()
            text = resp.text or ""
            # 形如: v_sz000001="51~平安银行~000001~10.66~...";
            if "=" not in text or '"' not in text:
                return None
            payload = text.split('"', 2)
            if len(payload) < 2:
                return None
            fields = payload[1].split("~")
            if len(fields) < 50 or not fields[1]:
                return None
            return fields
        except Exception:
            logger.exception("Tencent quote fetch failed for %s", code)
            return None

    def _em_single_quote(self, code: str) -> dict | None:
        """直连 EastMoney push2 stock/get 拉单股完整行情/估值/股本，绕过 akshare 的不稳定 wrapper。

        字段映射（实测）：f43=最新价, f58=名称, f60=昨收, f84=总股本(股), f85=流通股,
        f116=总市值, f117=流通市值, f127=所属行业, f163=PE(动), f164=PE(静/TTM),
        f167=PB, f170=涨跌幅%, f189=上市日期(YYYYMMDD)。
        """
        secid = self._em_secid(code)
        fields = (
            "f43,f57,f58,f60,f84,f85,f86,f116,f117,f127,"
            "f162,f163,f164,f167,f168,f170,f173,f189"
        )
        params = {"secid": secid, "fields": fields, "fltt": "2", "invt": "2"}
        for attempt in range(2):
            payload = self._em_get("/api/qt/stock/get", params, timeout=4)
            if payload is not None:
                data = (payload or {}).get("data")
                if isinstance(data, dict) and data:
                    return data
                return None
            if attempt == 0:
                time.sleep(0.4)
        logger.warning("EastMoney single quote fetch failed for %s", code)
        return None

    _EMPTY_QUOTE_EXTRAS: dict = {
        "volume": None,
        "amount": None,
        "main_net": None,
        "main_net_ratio": None,
    }

    def _em_ulist_quotes(self, codes: list[str]) -> dict[str, dict]:
        """EastMoney ulist.np 批量行情 + 资金流。返回 {code: 标准化 quote dict}。"""
        codes = [c for c in (codes or []) if c]
        if not codes:
            return {}
        secids = ",".join(self._em_secid(c) for c in codes)
        fields = "f12,f14,f2,f3,f5,f6,f62,f184"
        payload = self._em_get(
            "/api/qt/ulist.np/get",
            {"secids": secids, "fields": fields, "fltt": "2", "invt": "2"},
            timeout=6,
        )
        if payload is None:
            return {}
        data = (payload or {}).get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        out: dict[str, dict] = {}
        for row in diff:
            if not isinstance(row, dict):
                continue
            code = str(row.get("f12") or "").zfill(6)
            if not code:
                continue
            volume_hand = _to_float(row.get("f5"))
            out[code] = {
                "code": code,
                "name": str(row.get("f14") or ""),
                "price": _to_float(row.get("f2")) or 0,
                "change_pct": _to_float(row.get("f3")) or 0,
                "volume": (volume_hand * 100) if volume_hand is not None else None,
                "amount": _to_float(row.get("f6")),
                "main_net": _to_float(row.get("f62")),
                "main_net_ratio": _to_float(row.get("f184")),
            }
        return out

    def get_quotes_batch(self, codes: list[str]) -> list[dict]:
        """批量行情；EM 一次往返，缺失项回退到单股路径。"""
        codes = [str(c).zfill(6) for c in (codes or []) if c]
        if not codes:
            return []
        em = self._em_ulist_quotes(codes)
        return [em.get(c) or self.get_realtime_quote(c) for c in codes]

    def get_realtime_quote(self, code: str) -> dict:
        # 优先 EM ulist 一次拿齐 行情 + 资金流；失败回退 腾讯 → EM spot → 名称兜底
        em = self._em_ulist_quotes([code]).get(code)
        if em:
            return em
        qt = self._tencent_quote(code)
        if qt:
            price = _to_float(qt[3]) if len(qt) > 3 else None
            change_pct = _to_float(qt[32]) if len(qt) > 32 else None
            return {
                "code": code,
                "name": qt[1] or "",
                "price": price if price is not None else 0,
                "change_pct": change_pct if change_pct is not None else 0,
                **self._EMPTY_QUOTE_EXTRAS,
            }
        row = self._get_em_spot_row(code)
        if row is None:
            return {**self._fallback_quote(code), **self._EMPTY_QUOTE_EXTRAS}
        try:
            price = _to_float(row.get("最新价"))
            change_pct = _to_float(row.get("涨跌幅"))
            return {
                "code": code,
                "name": str(row.get("名称") or ""),
                "price": price if price is not None else 0,
                "change_pct": change_pct if change_pct is not None else 0,
                **self._EMPTY_QUOTE_EXTRAS,
            }
        except (TypeError, ValueError):
            return {**self._fallback_quote(code), **self._EMPTY_QUOTE_EXTRAS}

    def _fallback_quote(self, code: str) -> dict:
        try:
            df = ak.stock_info_a_code_name()
            if "名称" in df.columns:
                code_col, name_col = "代码", "名称"
            else:
                code_col, name_col = "code", "name"
            code_series = df[code_col].astype(str).str.zfill(6)
            row = df[code_series == code]
            if row.empty:
                return {"code": code, "name": "", "price": 0, "change_pct": 0}
            return {
                "code": code,
                "name": str(row.iloc[0][name_col]),
                "price": 0,
                "change_pct": 0,
            }
        except Exception:
            logger.exception("Fallback quote lookup failed for %s", code)
            return {"code": code, "name": "", "price": 0, "change_pct": 0}

    def _fill_baidu_valuation(self, code: str, result: dict) -> None:
        """用百度股市通历史估值时间序列补齐 PE_TTM/PS_TTM/股息率/PB 的最新值。"""
        mapping = [
            ("pe_ttm", "市盈率(TTM)"),
            ("pb", "市净率"),
            ("ps_ttm", "市销率(TTM)"),
            ("dv_ttm", "股息率(TTM)"),
        ]
        for key, indicator in mapping:
            if result.get(key) is not None:
                continue
            try:
                df = ak.stock_zh_valuation_baidu(symbol=code, indicator=indicator, period="近一年")
                if df is None or df.empty or "value" not in df.columns:
                    continue
                if "date" in df.columns:
                    df = df.sort_values("date")
                v = _to_float(df["value"].iloc[-1])
                if v is not None:
                    result[key] = v
                    if not result.get("as_of") and "date" in df.columns:
                        result["as_of"] = str(df["date"].iloc[-1])
            except Exception:
                logger.exception("Baidu valuation fetch failed for %s %s", code, indicator)

    # 资金流接口的内存缓存，5 分钟 TTL（盘中刷新够用，盘后稳定不变）
    _FUND_FLOW_CACHE: dict = {"stocks": {"ts": 0.0, "data": None}, "sectors": {"ts": 0.0, "data": None}}
    _FUND_FLOW_TTL = 300.0

    def _em_clist(self, fs: str, fields: str, pn: int = 1, pz: int = 50, fid: str = "f62", po: int = 1) -> list[dict]:
        """通用 EM push2 clist 拉取。po=1 降序，po=0 升序；按 fid 字段排。"""
        payload = self._em_get(
            "/api/qt/clist/get",
            {
                "pn": pn, "pz": pz, "po": po, "np": 1, "fltt": 2, "invt": 2,
                "fid": fid, "fs": fs, "fields": fields,
            },
            timeout=6,
        )
        if payload is None:
            return []
        data = (payload or {}).get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        return [it for it in diff if isinstance(it, dict)]

    @staticmethod
    def _ts_to_date(ts: float | int | None) -> str | None:
        if not ts:
            return None
        try:
            return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
        except Exception:
            return None

    def get_fund_flow_top(self, n: int = 10) -> dict:
        """主力资金流入/流出 TOP N 个股。EM 直连 clist 排序，单次往返完成。"""
        now = time.monotonic()
        cache = self._FUND_FLOW_CACHE["stocks"]
        if cache["data"] is not None and now - cache["ts"] < self._FUND_FLOW_TTL:
            return cache["data"]

        # fs 覆盖沪深 A 股 + 创业板 + 科创板
        fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
        fields = "f2,f3,f12,f14,f62,f124,f184"
        top_in = self._em_clist(fs, fields, pn=1, pz=n, fid="f62", po=1)
        top_out = self._em_clist(fs, fields, pn=1, pz=n, fid="f62", po=0)

        def shape(row: dict) -> dict:
            return {
                "code": str(row.get("f12") or ""),
                "name": str(row.get("f14") or ""),
                "price": _to_float(row.get("f2")),
                "change_pct": _to_float(row.get("f3")),
                "main_net": _to_float(row.get("f62")),
                "main_net_ratio": _to_float(row.get("f184")),
            }

        date_str = None
        for r in (top_in + top_out):
            date_str = self._ts_to_date(r.get("f124"))
            if date_str:
                break
        if not date_str:
            date_str = date.today().isoformat()

        result = {
            "date": date_str,
            "inflow": [shape(r) for r in top_in if _to_float(r.get("f62")) and _to_float(r.get("f62")) > 0],
            "outflow": [shape(r) for r in top_out if _to_float(r.get("f62")) and _to_float(r.get("f62")) < 0],
        }
        # 仅当拿到非空结果时才写缓存，避免一次 EM 抽风把空结果钉死 5 分钟。
        if result["inflow"] or result["outflow"]:
            self._FUND_FLOW_CACHE["stocks"] = {"ts": now, "data": result}
        return result

    def get_sector_fund_flow_top(self, n: int = 5) -> dict:
        """行业板块资金流入/流出 TOP N。EM 行业板块 fs=m:90+t:2。"""
        now = time.monotonic()
        cache = self._FUND_FLOW_CACHE["sectors"]
        if cache["data"] is not None and now - cache["ts"] < self._FUND_FLOW_TTL:
            return cache["data"]

        fs = "m:90+t:2"
        fields = "f3,f12,f14,f62,f124,f184,f204,f205,f206"
        top_in = self._em_clist(fs, fields, pn=1, pz=n, fid="f62", po=1)
        top_out = self._em_clist(fs, fields, pn=1, pz=n, fid="f62", po=0)

        def shape(row: dict) -> dict:
            return {
                "code": str(row.get("f12") or ""),
                "name": str(row.get("f14") or ""),
                "change_pct": _to_float(row.get("f3")),
                "main_net": _to_float(row.get("f62")),
                "main_net_ratio": _to_float(row.get("f184")),
                "lead_stock": str(row.get("f204") or ""),
                "lead_change_pct": _to_float(row.get("f206")),
            }

        date_str = None
        for r in (top_in + top_out):
            date_str = self._ts_to_date(r.get("f124"))
            if date_str:
                break
        if not date_str:
            date_str = date.today().isoformat()

        result = {
            "date": date_str,
            "inflow": [shape(r) for r in top_in if _to_float(r.get("f62")) and _to_float(r.get("f62")) > 0],
            "outflow": [shape(r) for r in top_out if _to_float(r.get("f62")) and _to_float(r.get("f62")) < 0],
        }
        if result["inflow"] or result["outflow"]:
            self._FUND_FLOW_CACHE["sectors"] = {"ts": now, "data": result}
        return result

    def get_fundamentals(self, code: str) -> dict:
        """合并多源行情/估值/股本数据。akshare 的 stock_individual_info_em / stock_zh_a_spot_em
        端点对外网偶发 RemoteDisconnected，stock_a_indicator_lg 已被 akshare 移除，故主路径改用
        EastMoney push2 stock/get 直连：

        - 主源 EM 直连 → 名称/最新价/涨跌幅/PE/PB/总市值/流通市值/总股本/流通股/行业/上市日期
        - akshare wrapper 兜底 → 上述字段任一缺失时补齐
        - 百度估值时间序列 → PE_TTM/PS_TTM/股息率(TTM)
        """
        result: dict = {
            "code": code,
            "name": "",
            "price": None,
            "change_pct": None,
            "pe": None,
            "pe_ttm": None,
            "pb": None,
            "ps_ttm": None,
            "dv_ttm": None,
            "total_market_cap": None,
            "float_market_cap": None,
            "total_shares": None,
            "float_shares": None,
            "industry": "",
            "listing_date": "",
            "as_of": None,
        }

        # 主源 1：腾讯实时接口（qt.gtimg.cn）— 字段全 + 连接稳
        qt = self._tencent_quote(code)
        if qt:
            if not result["name"]:
                result["name"] = qt[1]
            price = _to_float(qt[3])
            if price is not None and price > 0:
                result["price"] = price
            cp = _to_float(qt[32]) if len(qt) > 32 else None
            if cp is not None:
                result["change_pct"] = cp
            pe_ttm = _to_float(qt[39]) if len(qt) > 39 else None
            if pe_ttm is not None and pe_ttm != 0:
                result["pe_ttm"] = pe_ttm
            pe_static = _to_float(qt[53]) if len(qt) > 53 else None
            if pe_static is not None and pe_static != 0:
                result["pe"] = pe_static
            pb = _to_float(qt[46]) if len(qt) > 46 else None
            if pb is not None and pb != 0:
                result["pb"] = pb
            # 腾讯的市值单位是「亿元」，统一换算回「元」与后端约定一致
            fmc_yi = _to_float(qt[44]) if len(qt) > 44 else None
            if fmc_yi is not None and fmc_yi > 0:
                result["float_market_cap"] = fmc_yi * 1e8
            tmc_yi = _to_float(qt[45]) if len(qt) > 45 else None
            if tmc_yi is not None and tmc_yi > 0:
                result["total_market_cap"] = tmc_yi * 1e8
            ts_float = _to_float(qt[72]) if len(qt) > 72 else None
            if ts_float is not None and ts_float > 0:
                result["float_shares"] = ts_float
            ts_total = _to_float(qt[73]) if len(qt) > 73 else None
            if ts_total is not None and ts_total > 0:
                result["total_shares"] = ts_total
            # 时间戳格式 YYYYMMDDHHMMSS → as_of 取日期
            ts = qt[30] if len(qt) > 30 else ""
            if ts and len(ts) >= 8 and ts[:8].isdigit():
                result["as_of"] = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"

        # 主源 2：EastMoney push2 stock/get — 补 PE(动)、行业、上市日期（腾讯没有）
        em = self._em_single_quote(code)
        if em:
            if not result["name"]:
                name = em.get("f58")
                if name:
                    result["name"] = str(name)
            if result["price"] is None:
                price = _to_float(em.get("f43"))
                if price is not None and price > 0:
                    result["price"] = price
            if result["change_pct"] is None:
                cp = _to_float(em.get("f170"))
                if cp is not None:
                    result["change_pct"] = cp
            if result["pe"] is None:
                pe_dyn = _to_float(em.get("f163"))
                if pe_dyn is not None and pe_dyn != 0:
                    result["pe"] = pe_dyn
            if result["pe_ttm"] is None:
                pe_static = _to_float(em.get("f164"))
                if pe_static is not None and pe_static != 0:
                    result["pe_ttm"] = pe_static
            if result["pb"] is None:
                pb = _to_float(em.get("f167"))
                if pb is not None and pb != 0:
                    result["pb"] = pb
            if result["total_market_cap"] is None:
                tmc = _to_float(em.get("f116"))
                if tmc is not None and tmc > 0:
                    result["total_market_cap"] = tmc
            if result["float_market_cap"] is None:
                fmc = _to_float(em.get("f117"))
                if fmc is not None and fmc > 0:
                    result["float_market_cap"] = fmc
            if result["total_shares"] is None:
                ts_total = _to_float(em.get("f84"))
                if ts_total is not None and ts_total > 0:
                    result["total_shares"] = ts_total
            if result["float_shares"] is None:
                ts_float = _to_float(em.get("f85"))
                if ts_float is not None and ts_float > 0:
                    result["float_shares"] = ts_float
            if not result["industry"]:
                industry = em.get("f127")
                if industry:
                    result["industry"] = str(industry)
            if not result["listing_date"]:
                listing = em.get("f189")
                if listing is not None:
                    s = str(listing).strip()
                    if len(s) == 8 and s.isdigit():
                        result["listing_date"] = f"{s[0:4]}-{s[4:6]}-{s[6:8]}"

        # akshare wrapper 兜底：仅在 EM 直连缺失关键字段时调用
        missing_basics = (
            not result["industry"]
            or not result["listing_date"]
            or result["total_shares"] is None
            or result["float_shares"] is None
            or result["total_market_cap"] is None
            or result["float_market_cap"] is None
        )
        if missing_basics:
            try:
                info_df = ak.stock_individual_info_em(symbol=code)
                if (
                    info_df is not None
                    and not info_df.empty
                    and {"item", "value"}.issubset(info_df.columns)
                ):
                    kv = dict(zip(info_df["item"].astype(str), info_df["value"]))
                    if not result["industry"]:
                        result["industry"] = str(kv.get("行业", "") or "")
                    if result["total_market_cap"] is None:
                        result["total_market_cap"] = _to_float(kv.get("总市值"))
                    if result["float_market_cap"] is None:
                        result["float_market_cap"] = _to_float(kv.get("流通市值"))
                    if result["total_shares"] is None:
                        result["total_shares"] = _to_float(kv.get("总股本"))
                    if result["float_shares"] is None:
                        result["float_shares"] = _to_float(kv.get("流通股"))
                    if not result["listing_date"]:
                        listing = kv.get("上市时间")
                        if listing is not None:
                            s = str(listing).strip()
                            if len(s) == 8 and s.isdigit():
                                result["listing_date"] = f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
                            else:
                                result["listing_date"] = s
                    name = kv.get("股票简称")
                    if name and not result["name"]:
                        result["name"] = str(name)
            except Exception:
                logger.exception("akshare stock_individual_info_em failed for code=%s", code)

        # EastMoney 全量 spot 兜底：当单股 push2 直连失败时再尝试
        if result["price"] is None or result["change_pct"] is None or result["pe"] is None:
            spot = self._get_em_spot_row(code)
            if spot:
                if not result["name"]:
                    n = spot.get("名称")
                    if n:
                        result["name"] = str(n)
                price = _to_float(spot.get("最新价"))
                if price is not None and price > 0 and result["price"] is None:
                    result["price"] = price
                cp = _to_float(spot.get("涨跌幅"))
                if cp is not None and result["change_pct"] is None:
                    result["change_pct"] = cp
                if result["pe"] is None:
                    result["pe"] = _to_float(spot.get("市盈率-动态"))
                if result["pb"] is None:
                    result["pb"] = _to_float(spot.get("市净率"))
                if result["total_market_cap"] is None:
                    result["total_market_cap"] = _to_float(spot.get("总市值"))
                if result["float_market_cap"] is None:
                    result["float_market_cap"] = _to_float(spot.get("流通市值"))

        # 百度估值时间序列：补 PE_TTM/PS_TTM/股息率(TTM)
        if any(result.get(k) is None for k in ("pe_ttm", "ps_ttm", "dv_ttm", "pb")):
            self._fill_baidu_valuation(code, result)

        # 交易所基础信息表兜底：补上市日期/行业
        if not result["listing_date"] or not result["industry"]:
            info = self._listing_lookup(code)
            if info:
                if not result["listing_date"] and info.get("listing_date"):
                    result["listing_date"] = info["listing_date"]
                if not result["industry"] and info.get("industry"):
                    result["industry"] = info["industry"]

        if not result["as_of"]:
            result["as_of"] = date.today().isoformat()

        return result

    # ── 条件选股：批量行情+指标 ──────────────────────────────────────

    _SCREEN_FIELD_MAP = {
        "price": "f2",
        "change_pct": "f3",
        "amplitude": "f7",
        "turnover": "f8",
        "pe": "f9",
        "volume_ratio": "f10",
        "code": "f12",
        "name": "f14",
        "total_market_cap": "f20",
        "float_market_cap": "f21",
        "pb": "f23",
        "amount": "f6",
        "industry": "f100",
    }
    _SCREEN_FIELDS_STR = ",".join([
        "f2", "f3", "f6", "f7", "f8", "f9", "f10",
        "f12", "f14", "f20", "f21", "f23", "f100",
    ])
    _SCREEN_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"

    def screen_stocks(
        self,
        sort_by: str = "amount",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 50,
        codes: list[str] | None = None,
    ) -> dict:
        fid = self._SCREEN_FIELD_MAP.get(sort_by, "f6")
        po = 1 if sort_order == "desc" else 0

        if codes:
            secids = ",".join(self._em_secid(c) for c in codes)
            fields = self._SCREEN_FIELDS_STR
            payload = self._em_get(
                "/api/qt/ulist.np/get",
                {"secids": secids, "fields": fields, "fltt": "2", "invt": "2"},
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
            pz = max(page_size, 100)
            rows = self._em_clist(self._SCREEN_FS, self._SCREEN_FIELDS_STR, pn=1, pz=5000, fid=fid, po=po)
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

    # 指数行情内存缓存：避免每次请求都打外网；TTL 默认 15 秒，足以覆盖刷新洪峰
    _INDEX_CACHE: dict = {"ts": 0.0, "data": []}
    _INDEX_CACHE_TTL = 15.0

    _INDEX_TARGETS = [
        # (secid, 显示名称, 6 位代码, akshare 日线 symbol)
        ("1.000001", "上证指数", "000001", "sh000001"),
        ("0.399001", "深证成指", "399001", "sz399001"),
        ("0.399006", "创业板指", "399006", "sz399006"),
        ("1.000688", "科创50", "000688", "sh000688"),
    ]

    def _eastmoney_indices_batch(self) -> list[dict]:
        """一次 HTTP 拉取 4 个主要指数的实时行情（push2 批量接口）。"""
        secids = ",".join(t[0] for t in self._INDEX_TARGETS)
        try:
            resp = requests.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                params={
                    "secids": secids,
                    "fields": "f2,f3,f12,f13,f14",
                    "fltt": "2",  # 返回已按精度处理过的浮点数
                    "invt": "2",
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    ),
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=4,
            )
            resp.raise_for_status()
            payload = resp.json() or {}
        except Exception:
            logger.exception("EastMoney push2 index batch fetch failed")
            return []

        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):  # 偶发返回 {"0": {...}}
            diff = list(diff.values())

        by_secid: dict[str, dict] = {}
        for item in diff:
            if not isinstance(item, dict):
                continue
            market = item.get("f13")
            code = item.get("f12")
            if market is None or code is None:
                continue
            by_secid[f"{market}.{code}"] = item

        result: list[dict] = []
        for secid, name, code, _ in self._INDEX_TARGETS:
            item = by_secid.get(secid)
            if not item:
                continue
            price = _to_float(item.get("f2"))
            change_pct = _to_float(item.get("f3"))
            if price is None or price <= 0:
                continue
            result.append({
                "name": name,
                "code": code,
                "price": price,
                "change_pct": change_pct if change_pct is not None else 0.0,
            })
        return result

    def get_index_data(self) -> list[dict]:
        """指数实时行情：EastMoney 直连 → Sina 兜底 → 日线兜底；带 15s 内存缓存。"""
        now = time.monotonic()
        if (
            self._INDEX_CACHE["data"]
            and now - self._INDEX_CACHE["ts"] < self._INDEX_CACHE_TTL
        ):
            return list(self._INDEX_CACHE["data"])

        # 1) EastMoney 批量直连（最快）
        result = self._eastmoney_indices_batch()
        if result:
            self._INDEX_CACHE.update({"ts": now, "data": result})
            return result

        # 2) Sina 实时兜底
        try:
            sina = ak.stock_zh_index_spot_sina()
            if sina is not None and not sina.empty and "名称" in sina.columns:
                fallback: list[dict] = []
                for _secid, name, code, _ in self._INDEX_TARGETS:
                    row = sina[sina["名称"] == name]
                    if row.empty:
                        continue
                    r = row.iloc[0]
                    price = _to_float(r.get("最新价"))
                    cp = _to_float(r.get("涨跌幅"))
                    if price is None:
                        continue
                    fallback.append({
                        "name": name,
                        "code": code,
                        "price": price,
                        "change_pct": cp if cp is not None else 0.0,
                    })
                if fallback:
                    self._INDEX_CACHE.update({"ts": now, "data": fallback})
                    return fallback
        except Exception:
            logger.exception("Sina index spot fetch failed")

        # 3) 日线历史（最后兜底，可能是昨日收盘）
        daily_result: list[dict] = []
        for _secid, name, code, daily_symbol in self._INDEX_TARGETS:
            try:
                df = ak.stock_zh_index_daily(symbol=daily_symbol)
                if df is None or df.empty:
                    continue
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else last
                price = float(last["close"])
                prev_close = float(prev["close"])
                change_pct = (price - prev_close) / prev_close * 100 if prev_close != 0 else 0
                daily_result.append({
                    "name": name,
                    "code": code,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                })
            except Exception:
                logger.exception("akshare index daily fetch failed for %s", name)

        if daily_result:
            self._INDEX_CACHE.update({"ts": now, "data": daily_result})
        return daily_result
