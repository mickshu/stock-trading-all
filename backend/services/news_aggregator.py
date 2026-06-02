"""自选股相关重要资讯聚合服务。

设计目标
--------
- 多源拉取：akshare 提供的个股新闻（东财）+ 全市场快讯（财联社 / 东财 / 同花顺 / 新浪）
  - 用户期望中的「金十 / 雪球」akshare 暂无稳定中文 A 股新闻接口；保留扩展位，命中即并入
- 自选股相关性过滤：仅保留命中自选股代码或公司名的条目
- 标题相似度去重 + 热度评分：同一新闻被越多源覆盖、关联越多自选股、越新鲜 → 越靠前

返回结构对前端友好（统一 NewsItem dict），支持时间区间筛选 today / week / all。

健壮性
------
- 任一数据源失败 silent skip 并记录日志，不影响整体返回
- 模块级 TTL 缓存（默认 300s）按 (codes_set, time_range) 缓存结果，降低重复调用
- 列名差异较大，使用候选列名映射 + 字段缺失兜底
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

# 中国时区（akshare 文本时间默认为 Asia/Shanghai）
CST = timezone(timedelta(hours=8))

# 模块级缓存：{ cache_key: (timestamp, list[dict]) }
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL_SEC = 300

# 标题相似度阈值（Jaccard），高于此视为同一新闻
SIMILARITY_THRESHOLD = 0.55

# 单源拉取上限，防止历史数据爆量
PER_SOURCE_LIMIT = 200
# 个股新闻每只 ticker 拉取条数上限
PER_STOCK_LIMIT = 30


@dataclass
class NewsItem:
    id: str
    title: str
    summary: str
    url: str | None
    sources: list[str]
    published_at: datetime
    related_codes: list[str] = field(default_factory=list)
    related_names: list[str] = field(default_factory=list)
    hot_score: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        # ISO + 北京时间字符串均提供，前端按需取
        d["published_at"] = self.published_at.astimezone(CST).isoformat()
        return d


# -----------------------------
# 工具：时间解析、相似度
# -----------------------------

_DATETIME_PATTERNS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m-%d %H:%M",
    "%m/%d %H:%M",
]


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CST)
    if isinstance(value, pd.Timestamp):
        ts = value.to_pydatetime()
        return ts if ts.tzinfo else ts.replace(tzinfo=CST)
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    for fmt in _DATETIME_PATTERNS:
        try:
            ts = datetime.strptime(s, fmt)
            # %m-%d 格式补当前年
            if ts.year == 1900:
                ts = ts.replace(year=datetime.now(CST).year)
            return ts.replace(tzinfo=CST)
        except ValueError:
            continue
    # 兜底：pandas 解析
    try:
        ts = pd.to_datetime(s, errors="coerce")
        if pd.isna(ts):
            return None
        py = ts.to_pydatetime()
        return py if py.tzinfo else py.replace(tzinfo=CST)
    except Exception:
        return None


_TOKEN_RE = re.compile(r"[\w一-鿿]+")


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _make_id(title: str, source: str, ts: datetime) -> str:
    raw = f"{title}|{source}|{ts.isoformat()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


# -----------------------------
# 时间区间
# -----------------------------

def _time_range_floor(time_range: str) -> datetime:
    now = datetime.now(CST)
    if time_range == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if time_range == "week":
        return (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    # all：限制最长 30 天，避免拉无界历史
    return (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)


# -----------------------------
# 列名兜底
# -----------------------------

def _pick_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    # 模糊匹配（akshare 偶尔加空格 / 改别名）
    for c in candidates:
        for col in cols:
            if c in str(col):
                return col
    return None


# -----------------------------
# 各数据源适配
# -----------------------------

def _fetch_em_per_stock(code: str) -> list[dict]:
    """东方财富个股新闻 stock_news_em(symbol=code)。"""
    import akshare as ak
    try:
        df = ak.stock_news_em(symbol=code)
    except Exception:
        logger.warning("stock_news_em failed for %s", code, exc_info=True)
        return []
    if df is None or df.empty:
        return []
    title_col = _pick_col(df, ["新闻标题", "标题"])
    summary_col = _pick_col(df, ["新闻内容", "摘要", "内容"])
    time_col = _pick_col(df, ["发布时间", "时间", "发布日期"])
    url_col = _pick_col(df, ["新闻链接", "链接", "url"])
    if not title_col or not time_col:
        return []
    out: list[dict] = []
    for _, row in df.head(PER_STOCK_LIMIT).iterrows():
        ts = _parse_datetime(row.get(time_col))
        if not ts:
            continue
        out.append({
            "title": str(row.get(title_col, "")).strip(),
            "summary": str(row.get(summary_col, "") if summary_col else "").strip(),
            "url": str(row.get(url_col, "") if url_col else "").strip() or None,
            "source": "东方财富",
            "published_at": ts,
            "preset_codes": [code],
        })
    return out


def _fetch_global(source_label: str, fn_name: str, **kwargs) -> list[dict]:
    """通用全市场快讯抓取。fn_name 取自 akshare 模块。"""
    import akshare as ak
    fn = getattr(ak, fn_name, None)
    if fn is None:
        logger.warning("akshare has no %s, skipped", fn_name)
        return []
    try:
        df = fn(**kwargs) if kwargs else fn()
    except Exception:
        logger.warning("%s failed", fn_name, exc_info=True)
        return []
    if df is None or df.empty:
        return []
    title_col = _pick_col(df, ["标题", "新闻标题", "title"])
    summary_col = _pick_col(df, ["摘要", "内容", "新闻内容", "summary"])
    time_col = _pick_col(df, ["发布时间", "时间", "发布日期", "publish_time"])
    date_col = _pick_col(df, ["发布日期", "日期"]) if time_col else None
    url_col = _pick_col(df, ["链接", "url", "新闻链接"])
    if not title_col and not summary_col:
        return []
    out: list[dict] = []
    for _, row in df.head(PER_SOURCE_LIMIT).iterrows():
        # 财联社：发布日期 + 发布时间 拆两列
        if time_col == "发布时间" and date_col == "发布日期":
            d = str(row.get(date_col, "")).strip()
            t = str(row.get(time_col, "")).strip()
            ts = _parse_datetime(f"{d} {t}".strip()) if d or t else None
        elif time_col:
            ts = _parse_datetime(row.get(time_col))
        else:
            ts = None
        if not ts:
            continue
        title = str(row.get(title_col, "")).strip() if title_col else ""
        summary = str(row.get(summary_col, "")).strip() if summary_col else ""
        if not title and summary:
            # 新浪只有「时间 / 内容」两列；用内容前 40 字代标题
            title = summary[:40]
        if not title:
            continue
        out.append({
            "title": title,
            "summary": summary,
            "url": str(row.get(url_col, "") if url_col else "").strip() or None,
            "source": source_label,
            "published_at": ts,
            "preset_codes": [],
        })
    return out


# -----------------------------
# 相关性匹配
# -----------------------------

def _annotate_related(
    raw_items: list[dict],
    code_to_name: dict[str, str],
) -> list[dict]:
    """根据 title+summary 命中哪些自选股代码 / 公司名，写入 related_codes / related_names。

    preset_codes 已强制相关（个股新闻直拉路径）。
    """
    annotated: list[dict] = []
    name_index: list[tuple[str, str]] = []  # (公司简称, 代码)
    for code, name in code_to_name.items():
        if name:
            name_index.append((name, code))
    # 长名优先，避免「中国平安」匹配到「平安银行」之前先抽走「平安」
    name_index.sort(key=lambda x: -len(x[0]))

    for item in raw_items:
        text = f"{item.get('title','')} {item.get('summary','')}"
        hit_codes: set[str] = set(item.get("preset_codes") or [])
        # 代码硬匹配
        for code in code_to_name:
            if code in text:
                hit_codes.add(code)
        # 名字匹配
        for name, code in name_index:
            if name and name in text:
                hit_codes.add(code)
        if not hit_codes:
            continue
        item["related_codes"] = sorted(hit_codes)
        item["related_names"] = sorted({code_to_name.get(c, "") for c in hit_codes if code_to_name.get(c)})
        annotated.append(item)
    return annotated


# -----------------------------
# 去重 + 评分
# -----------------------------

def _deduplicate_and_score(items: list[dict]) -> list[NewsItem]:
    """按标题 Jaccard 相似度合并同一新闻。"""
    items = sorted(items, key=lambda x: x["published_at"], reverse=True)
    clusters: list[dict] = []
    cluster_tokens: list[set[str]] = []

    for it in items:
        tokens = _tokenize(it["title"])
        merged = False
        for idx, base_tokens in enumerate(cluster_tokens):
            if _jaccard(tokens, base_tokens) >= SIMILARITY_THRESHOLD:
                base = clusters[idx]
                if it["source"] not in base["sources"]:
                    base["sources"].append(it["source"])
                # 合并相关代码
                base["related_codes"] = sorted(set(base["related_codes"]) | set(it.get("related_codes", [])))
                base["related_names"] = sorted(set(base["related_names"]) | set(it.get("related_names", [])))
                # 取较长摘要
                if len(it.get("summary", "")) > len(base.get("summary", "")):
                    base["summary"] = it["summary"]
                # 取最早发布时间作代表（更准确，去重后用最早）
                if it["published_at"] < base["published_at"]:
                    base["published_at"] = it["published_at"]
                # 链接保留首个非空
                if not base.get("url") and it.get("url"):
                    base["url"] = it["url"]
                merged = True
                break
        if not merged:
            clusters.append({
                "title": it["title"],
                "summary": it.get("summary", ""),
                "url": it.get("url"),
                "sources": [it["source"]],
                "published_at": it["published_at"],
                "related_codes": list(it.get("related_codes", [])),
                "related_names": list(it.get("related_names", [])),
            })
            cluster_tokens.append(tokens)

    # 评分：源数 * 2 + 关联自选股数 + 新鲜度（最近 1h 加 5、24h 加 2、3d 加 1）
    now = datetime.now(CST)
    out: list[NewsItem] = []
    for c in clusters:
        age = now - c["published_at"]
        if age < timedelta(hours=1):
            recency = 5.0
        elif age < timedelta(hours=24):
            recency = 2.0
        elif age < timedelta(days=3):
            recency = 1.0
        else:
            recency = 0.0
        score = len(c["sources"]) * 2.0 + len(c["related_codes"]) + recency
        out.append(NewsItem(
            id=_make_id(c["title"], ",".join(c["sources"]), c["published_at"]),
            title=c["title"],
            summary=c["summary"][:300],
            url=c["url"],
            sources=c["sources"],
            published_at=c["published_at"],
            related_codes=c["related_codes"],
            related_names=c["related_names"],
            hot_score=round(score, 2),
        ))
    return out


# -----------------------------
# 入口
# -----------------------------

def fetch_news_for_watchlist(
    code_to_name: dict[str, str],
    time_range: str = "today",
    limit: int = 50,
) -> list[dict]:
    """聚合自选股相关重要资讯。

    code_to_name: {"000001": "平安银行", ...}
    time_range:   "today" | "week" | "all"
    """
    if not code_to_name:
        return []

    cache_key = f"{','.join(sorted(code_to_name.keys()))}|{time_range}"
    now_ts = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_ts - cached[0] < CACHE_TTL_SEC:
            return cached[1][:limit]

    floor = _time_range_floor(time_range)
    raw: list[dict] = []

    # 1) 个股新闻（东财，按代码各拉一次）
    for code in code_to_name:
        raw.extend(_fetch_em_per_stock(code))

    # 2) 全市场快讯：财联社 / 东财快讯 / 同花顺 / 新浪
    raw.extend(_fetch_global("财联社", "stock_info_global_cls", symbol="全部"))
    raw.extend(_fetch_global("东财快讯", "stock_info_global_em"))
    raw.extend(_fetch_global("同花顺", "stock_info_global_ths"))
    raw.extend(_fetch_global("新浪", "stock_info_global_sina"))
    # 富途 / 金十 / 雪球 — akshare 暂无稳定 A 股资讯接口，跳过；后续接入时追加 _fetch_global 即可

    # 3) 时间窗口过滤
    raw = [r for r in raw if r["published_at"] >= floor]

    # 4) 自选股相关性过滤（个股新闻 preset_codes 已带）
    raw = _annotate_related(raw, code_to_name)

    # 5) 去重 + 评分
    items = _deduplicate_and_score(raw)
    items.sort(key=lambda n: (-n.hot_score, -n.published_at.timestamp()))

    payload = [n.to_dict() for n in items]
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now_ts, payload)
    return payload[:limit]
