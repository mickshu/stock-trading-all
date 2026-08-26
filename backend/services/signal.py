"""信号引擎：从指标 DataFrame 中识别常见技术信号。

信号包含：
- type   : 唯一类型 key（如 macd_golden_cross）
- category: 趋势 / 动量 / 反转 / 量能
- level  : bullish(多) / bearish(空) / neutral(中性)
- indicator: 涉及的指标名（MACD / MA / KDJ / RSI / VOL / PRICE）
- description: 当次信号的具体描述
- date / position: 触发位置
- explanation: 信号原理解释（来自 SIGNAL_CATALOG）
- caveat    : 常见误导/失效情形（来自 SIGNAL_CATALOG）
"""
import pandas as pd


# 分类常量
CAT_TREND = "trend"        # 趋势
CAT_MOMENTUM = "momentum"  # 动量
CAT_REVERSAL = "reversal"  # 反转
CAT_VOLUME = "volume"      # 量能

LEVEL_BULL = "bullish"
LEVEL_BEAR = "bearish"
LEVEL_NEUTRAL = "neutral"


# 信号目录：type -> 元信息。category/level/explanation/caveat 在此集中维护。
SIGNAL_CATALOG: dict[str, dict] = {
    # ===== MACD =====
    "macd_golden_cross": {
        "name": "MACD 金叉",
        "category": CAT_TREND,
        "level": LEVEL_BULL,
        "indicator": "MACD",
        "explanation": "DIF 由下向上穿越 DEA，短期动能转强，常被视为买入信号；若发生在 0 轴之上，趋势确认更强。",
        "caveat": "震荡行情中会反复出现金叉死叉，单凭一次金叉容易被'假突破'套牢；建议结合 0 轴位置、成交量与上方压力位过滤。",
    },
    "macd_death_cross": {
        "name": "MACD 死叉",
        "category": CAT_TREND,
        "level": LEVEL_BEAR,
        "indicator": "MACD",
        "explanation": "DIF 由上向下穿越 DEA，短期动能转弱，常视为卖出信号；发生在 0 轴下方时空头力量更明显。",
        "caveat": "强势上涨途中的回踩也可能触发死叉，但价格随即反弹；高位放量死叉风险更大，低位缩量死叉常是末跌。",
    },
    "macd_zero_up": {
        "name": "MACD 零轴上穿",
        "category": CAT_TREND,
        "level": LEVEL_BULL,
        "indicator": "MACD",
        "explanation": "DIF 由负转正，向上突破 0 轴，多头趋势确认，常作为中期趋势启动信号。",
        "caveat": "横盘整理时 DIF 在 0 轴附近反复穿越，意义不大；需结合 K 线突破和量能。",
    },
    "macd_zero_down": {
        "name": "MACD 零轴下穿",
        "category": CAT_TREND,
        "level": LEVEL_BEAR,
        "indicator": "MACD",
        "explanation": "DIF 由正转负，向下跌破 0 轴，空头趋势确认，常作为中期趋势转弱信号。",
        "caveat": "在已经长期下跌的低位区出现意义有限，可能很快进入超跌反弹。",
    },
    # ===== MA =====
    "ma_golden_cross": {
        "name": "均线金叉",
        "category": CAT_TREND,
        "level": LEVEL_BULL,
        "indicator": "MA",
        "explanation": "短期均线上穿长期均线，反映短期成本回升至长期成本之上，是经典的趋势转多信号。",
        "caveat": "均线金叉具有滞后性，等到金叉时价格往往已经上涨一段；窄幅震荡中频繁交叉无效，需配合方向性确认。",
    },
    "ma_death_cross": {
        "name": "均线死叉",
        "category": CAT_TREND,
        "level": LEVEL_BEAR,
        "indicator": "MA",
        "explanation": "短期均线下穿长期均线，反映短期成本回落到长期成本之下，趋势转空。",
        "caveat": "下跌末端的死叉常对应低位反弹起点；同样具有滞后性，急跌行情中死叉时往往已接近阶段低点。",
    },
    "price_breakout_ma": {
        "name": "价格突破均线",
        "category": CAT_TREND,
        "level": LEVEL_BULL,
        "indicator": "PRICE",
        "explanation": "收盘价由下方上穿中长期均线（脱离），意味着多空力量切换，趋势可能反转向上。",
        "caveat": "假突破常见——若次日不能站稳均线，或量能未放大，容易演变为'诱多'。建议看放量+连续 2~3 日站稳。",
    },
    "price_breakdown_ma": {
        "name": "价格跌破均线",
        "category": CAT_TREND,
        "level": LEVEL_BEAR,
        "indicator": "PRICE",
        "explanation": "收盘价由上方下穿中长期均线，趋势支撑被打破，可能进入下跌通道。",
        "caveat": "缩量假跌破后常出现快速回升（'空头陷阱'），需观察放量与次日表现；急跌中跌破均线也可能是末段。",
    },
    "ma_bull_alignment": {
        "name": "均线多头排列",
        "category": CAT_TREND,
        "level": LEVEL_BULL,
        "indicator": "MA",
        "explanation": "MA5 > MA10 > MA20 > MA60 且当日新形成，表明中短期均线全面向上，主升浪特征。",
        "caveat": "出现时趋势已较成熟，追入风险增大；一旦最短均线先掉头，往往是阶段顶。",
    },
    "ma_bear_alignment": {
        "name": "均线空头排列",
        "category": CAT_TREND,
        "level": LEVEL_BEAR,
        "indicator": "MA",
        "explanation": "MA5 < MA10 < MA20 < MA60 且当日新形成，中短期均线全面向下，主跌特征。",
        "caveat": "深跌过程中出现往往离反弹不远；不宜单凭排列形态做空。",
    },
    # ===== KDJ =====
    "kdj_golden_cross": {
        "name": "KDJ 金叉",
        "category": CAT_MOMENTUM,
        "level": LEVEL_BULL,
        "indicator": "KDJ",
        "explanation": "K 线上穿 D 线，短期动能由空转多。在 20 以下低位金叉信号较强。",
        "caveat": "KDJ 灵敏度高，高位（>80）金叉常是'强势钝化'继续上涨而非反转；震荡市信号极不稳定。",
    },
    "kdj_death_cross": {
        "name": "KDJ 死叉",
        "category": CAT_MOMENTUM,
        "level": LEVEL_BEAR,
        "indicator": "KDJ",
        "explanation": "K 线下穿 D 线，短期动能由多转空。在 80 以上高位死叉警示意义较强。",
        "caveat": "低位（<20）死叉常为'弱势钝化'，并非加速下跌信号；强趋势中反复死叉容易被甩下车。",
    },
    "kdj_oversold": {
        "name": "KDJ 超卖",
        "category": CAT_REVERSAL,
        "level": LEVEL_BULL,
        "indicator": "KDJ",
        "explanation": "J 值 < 0，市场短期跌势透支，存在技术性反弹概率。",
        "caveat": "强势下跌中 J 值可在 0 以下'钝化'数日甚至数周（弱势钝化），抄底易被套；需等待 J 值回升且 KDJ 金叉确认。",
    },
    "kdj_overbought": {
        "name": "KDJ 超买",
        "category": CAT_REVERSAL,
        "level": LEVEL_BEAR,
        "indicator": "KDJ",
        "explanation": "J 值 > 100，短期涨势透支，存在回调风险。",
        "caveat": "强势主升浪中 J 值会长期 >100（强势钝化），过早离场会错过主升；需配合量能背离判断。",
    },
    # ===== RSI =====
    "rsi_oversold": {
        "name": "RSI 超卖",
        "category": CAT_REVERSAL,
        "level": LEVEL_BULL,
        "indicator": "RSI",
        "explanation": "RSI6 < 30，价格短期超跌，技术上反弹概率提高。",
        "caveat": "在单边下跌中 RSI 可长时间停在 30 以下；建议等待 RSI 上穿 30 再确认。",
    },
    "rsi_overbought": {
        "name": "RSI 超买",
        "category": CAT_REVERSAL,
        "level": LEVEL_BEAR,
        "indicator": "RSI",
        "explanation": "RSI6 > 70，价格短期超买，回调概率提高。",
        "caveat": "强势行情中 RSI 可长时间停留 >70 区域（高位钝化），仅凭超买做空风险大；优先看是否出现顶背离。",
    },
    # ===== 量能 =====
    "volume_spike": {
        "name": "巨量放量",
        "category": CAT_VOLUME,
        "level": LEVEL_NEUTRAL,
        "indicator": "VOL",
        "explanation": "成交量 ≥ 近 20 日均量的 2 倍。放量代表分歧加剧或资金大幅介入/撤离。",
        "caveat": "放量本身方向中性：底部放量上涨多为启动信号，高位放量滞涨/放量下跌则常是出货；需结合价格形态判断。",
    },
    "volume_dry": {
        "name": "极度缩量",
        "category": CAT_VOLUME,
        "level": LEVEL_NEUTRAL,
        "indicator": "VOL",
        "explanation": "成交量 ≤ 近 20 日均量的 50%。缩量代表分歧降低、惜售或观望。",
        "caveat": "下跌途中缩量未必是底，可能是'无量阴跌'；横盘末端的缩量常预示方向选择。",
    },
}


def _cross_up(a_now, b_now, a_prev, b_prev) -> bool:
    return (
        pd.notna(a_now) and pd.notna(b_now) and pd.notna(a_prev) and pd.notna(b_prev)
        and a_prev <= b_prev and a_now > b_now
    )


def _cross_down(a_now, b_now, a_prev, b_prev) -> bool:
    return (
        pd.notna(a_now) and pd.notna(b_now) and pd.notna(a_prev) and pd.notna(b_prev)
        and a_prev >= b_prev and a_now < b_now
    )


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


def _enrich(sig_type: str, description: str, df: pd.DataFrame, i: int) -> dict:
    meta = SIGNAL_CATALOG[sig_type]
    return {
        "type": sig_type,
        "category": meta["category"],
        "level": meta["level"],
        "indicator": meta["indicator"],
        "name": meta["name"],
        "description": description,
        "explanation": meta["explanation"],
        "caveat": meta["caveat"],
        "date": str(df["date"].iloc[i]),
        "position": i,
    }


class SignalEngine:
    """从带指标的 K 线 DataFrame 中识别多类技术信号。"""

    MA_CROSS_PAIRS = [("MA5", "MA10"), ("MA5", "MA20"), ("MA10", "MA20"), ("MA20", "MA60")]
    PRICE_BREAK_MAS = ["MA20", "MA60"]

    def detect(self, df: pd.DataFrame) -> list[dict]:
        signals: list[dict] = []
        if df.empty or "date" not in df.columns:
            return signals

        n = len(df)

        # ---- MACD ----
        if {"MACD_DIF", "MACD_DEA"}.issubset(df.columns):
            for i in range(1, n):
                dif_n, dea_n = df["MACD_DIF"].iloc[i], df["MACD_DEA"].iloc[i]
                dif_p, dea_p = df["MACD_DIF"].iloc[i - 1], df["MACD_DEA"].iloc[i - 1]
                if _cross_up(dif_n, dea_n, dif_p, dea_p):
                    signals.append(_enrich("macd_golden_cross", "MACD 金叉：DIF 上穿 DEA", df, i))
                elif _cross_down(dif_n, dea_n, dif_p, dea_p):
                    signals.append(_enrich("macd_death_cross", "MACD 死叉：DIF 下穿 DEA", df, i))
                if pd.notna(dif_n) and pd.notna(dif_p):
                    if dif_p <= 0 and dif_n > 0:
                        signals.append(_enrich("macd_zero_up", "MACD 上穿 0 轴：DIF 由负转正", df, i))
                    elif dif_p >= 0 and dif_n < 0:
                        signals.append(_enrich("macd_zero_down", "MACD 跌破 0 轴：DIF 由正转负", df, i))

        # ---- MA 交叉 ----
        for short_c, long_c in self.MA_CROSS_PAIRS:
            if short_c not in df.columns or long_c not in df.columns:
                continue
            for i in range(1, n):
                s_n, l_n = df[short_c].iloc[i], df[long_c].iloc[i]
                s_p, l_p = df[short_c].iloc[i - 1], df[long_c].iloc[i - 1]
                if _cross_up(s_n, l_n, s_p, l_p):
                    signals.append(_enrich(
                        "ma_golden_cross", f"均线金叉：{short_c} 上穿 {long_c}", df, i))
                elif _cross_down(s_n, l_n, s_p, l_p):
                    signals.append(_enrich(
                        "ma_death_cross", f"均线死叉：{short_c} 下穿 {long_c}", df, i))

        # ---- 价格突破/跌破均线（脱离） ----
        if "close" in df.columns:
            for ma in self.PRICE_BREAK_MAS:
                if ma not in df.columns:
                    continue
                for i in range(1, n):
                    c_n, m_n = df["close"].iloc[i], df[ma].iloc[i]
                    c_p, m_p = df["close"].iloc[i - 1], df[ma].iloc[i - 1]
                    if _cross_up(c_n, m_n, c_p, m_p):
                        signals.append(_enrich(
                            "price_breakout_ma", f"价格突破 {ma}：收盘价上穿 {ma}", df, i))
                    elif _cross_down(c_n, m_n, c_p, m_p):
                        signals.append(_enrich(
                            "price_breakdown_ma", f"价格跌破 {ma}：收盘价下穿 {ma}", df, i))

        # ---- 均线多/空头排列（仅在当日新成立时触发） ----
        ma_cols = ["MA5", "MA10", "MA20", "MA60"]
        if all(c in df.columns for c in ma_cols):
            def _is_bull(row_idx: int) -> bool:
                vals = [df[c].iloc[row_idx] for c in ma_cols]
                if any(pd.isna(v) for v in vals):
                    return False
                return vals[0] > vals[1] > vals[2] > vals[3]

            def _is_bear(row_idx: int) -> bool:
                vals = [df[c].iloc[row_idx] for c in ma_cols]
                if any(pd.isna(v) for v in vals):
                    return False
                return vals[0] < vals[1] < vals[2] < vals[3]

            for i in range(1, n):
                if _is_bull(i) and not _is_bull(i - 1):
                    signals.append(_enrich(
                        "ma_bull_alignment", "均线多头排列形成：MA5>MA10>MA20>MA60", df, i))
                elif _is_bear(i) and not _is_bear(i - 1):
                    signals.append(_enrich(
                        "ma_bear_alignment", "均线空头排列形成：MA5<MA10<MA20<MA60", df, i))

        # ---- KDJ ----
        if {"KDJ_K", "KDJ_D", "KDJ_J"}.issubset(df.columns):
            for i in range(1, n):
                k_n, d_n = df["KDJ_K"].iloc[i], df["KDJ_D"].iloc[i]
                k_p, d_p = df["KDJ_K"].iloc[i - 1], df["KDJ_D"].iloc[i - 1]
                if _cross_up(k_n, d_n, k_p, d_p):
                    signals.append(_enrich("kdj_golden_cross", "KDJ 金叉：K 上穿 D", df, i))
                elif _cross_down(k_n, d_n, k_p, d_p):
                    signals.append(_enrich("kdj_death_cross", "KDJ 死叉：K 下穿 D", df, i))
                j_n = df["KDJ_J"].iloc[i]
                if pd.notna(j_n):
                    if j_n < 0:
                        signals.append(_enrich(
                            "kdj_oversold", f"KDJ 超卖：J={j_n:.1f} < 0", df, i))
                    elif j_n > 100:
                        signals.append(_enrich(
                            "kdj_overbought", f"KDJ 超买：J={j_n:.1f} > 100", df, i))

        # ---- RSI ----
        if "RSI6" in df.columns:
            for i in range(n):
                r = df["RSI6"].iloc[i]
                if pd.isna(r):
                    continue
                if r < 30:
                    signals.append(_enrich(
                        "rsi_oversold", f"RSI 超卖：RSI6={r:.1f} < 30", df, i))
                elif r > 70:
                    signals.append(_enrich(
                        "rsi_overbought", f"RSI 超买：RSI6={r:.1f} > 70", df, i))

        # ---- 量能：与 20 日均量比较 ----
        if "volume" in df.columns:
            vol_ma = df["volume"].rolling(window=20, min_periods=10).mean()
            for i in range(n):
                v, vm = df["volume"].iloc[i], vol_ma.iloc[i]
                if pd.isna(v) or pd.isna(vm) or vm <= 0:
                    continue
                ratio = v / vm
                if ratio >= 2.0:
                    signals.append(_enrich(
                        "volume_spike", f"放量：成交量为 20 日均量的 {ratio:.1f} 倍", df, i))
                elif ratio <= 0.5:
                    signals.append(_enrich(
                        "volume_dry", f"缩量：成交量仅为 20 日均量的 {ratio:.1f} 倍", df, i))

        signals.sort(key=lambda s: (s["position"], s["type"]))
        return signals


def get_signal_catalog() -> list[dict]:
    """返回所有支持的信号类型说明，供前端展示一份信号字典。"""
    return [
        {
            "type": t,
            "name": meta["name"],
            "category": meta["category"],
            "level": meta["level"],
            "indicator": meta["indicator"],
            "explanation": meta["explanation"],
            "caveat": meta["caveat"],
        }
        for t, meta in SIGNAL_CATALOG.items()
    ]
