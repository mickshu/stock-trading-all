"""股票名拼音/首字母匹配工具。

依赖 pypinyin；未安装时函数退化为空字符串，调用方仍能用代码/汉字子串匹配。
"""
from functools import lru_cache
from typing import Iterable

try:
    from pypinyin import lazy_pinyin, Style  # type: ignore
    _PYPINYIN_AVAILABLE = True
except ImportError:  # 兜底：未安装 pypinyin 时拼音相关结果为空
    _PYPINYIN_AVAILABLE = False


@lru_cache(maxsize=16384)
def name_pinyin(name: str) -> tuple[str, str]:
    """(full_pinyin_lower, initials_lower)；pypinyin 缺失或空名称返回 ("","")."""
    if not _PYPINYIN_AVAILABLE or not name:
        return "", ""
    pys = lazy_pinyin(name, style=Style.NORMAL)
    full = "".join(pys).lower()
    init = "".join(p[0] for p in pys if p).lower()
    return full, init


def is_ascii_alpha(s: str) -> bool:
    return bool(s) and s.isascii() and s.isalpha()


def rank_stock_matches(
    rows: Iterable[tuple[str, str]],
    keyword: str,
    limit: int = 20,
) -> list[tuple[str, str]]:
    """按相关度返回 (code, name) 匹配项。

    优先级桶：
      0 — code 前缀匹配
      1 — name 前缀匹配
      2 — 首字母前缀匹配（仅当 keyword 为 ASCII 字母）
      3 — 全拼前缀匹配（仅当 keyword 为 ASCII 字母）
      4 — 任意子串兜底（code/name/首字母/全拼）
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    kw_low = kw.lower()
    is_alpha = is_ascii_alpha(kw)
    buckets: list[list[tuple[str, str]]] = [[] for _ in range(5)]
    for code, name in rows:
        if not code:
            continue
        if code.startswith(kw):
            buckets[0].append((code, name))
            continue
        if name and name.startswith(kw):
            buckets[1].append((code, name))
            continue
        full_py, init = name_pinyin(name) if name else ("", "")
        if is_alpha and init and init.startswith(kw_low):
            buckets[2].append((code, name))
            continue
        if is_alpha and full_py and full_py.startswith(kw_low):
            buckets[3].append((code, name))
            continue
        if (
            kw in code
            or (name and kw in name)
            or (is_alpha and ((init and kw_low in init) or (full_py and kw_low in full_py)))
        ):
            buckets[4].append((code, name))
    merged: list[tuple[str, str]] = []
    for bucket in buckets:
        for item in bucket:
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged
