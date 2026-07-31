"""每日关注机会扫描服务。

每日凌晨扫描自选股，筛选处于买入区间的个股（技术信号 + 目标价触发），
取前 5 支，调用配置的 LLM 做买入机会评估。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database import SessionLocal, engine
from backend.models.models import Watchlist
from backend.data_sources.factory import get_data_source
from backend.services.signal import SignalEngine
from backend.services.indicator import compute_indicators
from backend.api.settings import get_ai_settings_dict
from backend.services.ai_summary import _run_openai, _run_anthropic, _run_local_agent

logger = logging.getLogger(__name__)

LOCAL_AGENT_NAMES = ("hermes", "ollama", "llamafile", "claude", "codex", "gemini")

SYSTEM_PROMPT = (
    "你是 A 股短线买入机会评估专家。用户会给你一只股票的名称、代码、近期技术信号"
    "和估值数据。请用 1-2 句话简明判断当前是否值得关注（如：趋势/支撑位/量价配合/风险提示），"
    "不要长篇大论。"
)


def _scan_watchlist(db: Session) -> list[dict]:
    """扫描自选股，返回处于买入区间的候选列表。"""
    rows = db.execute(select(Watchlist)).scalars().all()
    if not rows:
        return []

    ds = get_data_source()
    engine = SignalEngine()
    candidates: list[dict] = []

    for row in rows:
        code = row.code
        name = row.name or code
        score = 0
        reasons: list[str] = []
        signal_names: list[str] = []

        # ── 获取 K 线 + 计算指标 ──
        try:
            end = date.today().isoformat()
            start = "2026-01-01"  # 足够覆盖近期信号
            df = ds.get_kline(code, "daily", start, end)
            if df is None or df.empty or len(df) < 30:
                continue
            df = compute_indicators(df, ["MACD", "MA", "KDJ", "RSI"])
            if df.empty:
                continue
        except Exception:
            logger.exception("K-line/indicator fetch failed for %s", code)
            continue

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        # ── 信号检测 ──
        signals = engine.detect(df)

        # 取最近 5 个交易日的信号
        recent_days = 5
        recent_df = df.tail(recent_days)
        for _, r in recent_df.iterrows():
            sigs = engine.detect_from_row(r, prev) if hasattr(engine, "detect_from_row") else []
            for s in sigs:
                signal_names.append(s.get("type", ""))

        # 取最近 N 天的已计算信号
        recent_signals = [s for s in signals if _days_ago(s.get("date", "")) <= recent_days]

        for s in recent_signals:
            stype = s.get("type", "")
            name_s = s.get("name", stype)

            # RSI 超卖
            if "oversold" in stype.lower() or "超卖" in name_s:
                score += 3
                reasons.append("RSI超卖")
            # KDJ 低位金叉
            if ("golden_cross" in stype.lower() or "金叉" in name_s) and "kdj" in stype.lower():
                score += 3
                reasons.append("KDJ低位金叉")
            # MACD 金叉
            if ("golden_cross" in stype.lower() or "金叉" in name_s) and "macd" in stype.lower():
                score += 4
                reasons.append("MACD金叉")
            # 一般金叉
            if ("golden_cross" in stype.lower() or "金叉" in name_s) and "macd" not in stype.lower() and "kdj" not in stype.lower():
                score += 2
                reasons.append(f"金叉信号")

        # ── 价格回踩 MA60 ──
        ma60 = last.get("MA60")
        close = last.get("close")
        if ma60 and close and ma60 > 0:
            pct = abs(close - ma60) / ma60 * 100
            if pct <= 3:
                score += 2
                reasons.append("价格接近MA60支撑")

        # ── 目标价触发 ──
        target = row.target_price
        alert_pct = row.alert_diff_pct
        if target and target > 0 and close:
            diff_pct = abs(close - target) / target * 100
            threshold = alert_pct if alert_pct and alert_pct > 0 else 5.0
            if diff_pct <= threshold:
                score += 3
                reasons.append(f"目标价临近(差{diff_pct:.1f}%)")

        if score >= 3 and reasons:
            candidates.append({
                "code": code,
                "name": name,
                "score": score,
                "reasons": list(set(reasons)),
                "signals": list(set(signal_names)),
                "price": float(close) if close else None,
                "target_price": target,
            })

    # 按 score 降序，取前 5
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:5]


def _days_ago(date_str: str) -> int:
    """计算日期字符串距离今天的天数。"""
    try:
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return 999


def _build_ai_prompt(candidates: list[dict]) -> str:
    """为 LLM 构建评估 prompt。"""
    lines = ["## 候选买入机会", ""]
    for i, c in enumerate(candidates, 1):
        price_str = f"{c['price']:.2f}" if c.get("price") else "—"
        target_str = f"{c['target_price']:.2f}" if c.get("target_price") else "—"
        lines.append(
            f"{i}. {c['code']} {c['name']} 最新价{price_str} 目标价{target_str}\n"
            f"   信号: {', '.join(c.get('reasons', []))}\n"
            f"   技术信号标签: {', '.join(c.get('signals', [])[:5])}"
        )
    lines += [
        "",
        "请基于以上数据，对每只股票用 1-2 句话评估买入机会（关注/谨慎/回避），",
        "输出格式：序号. 代码 名称 → 判定：一句话理由",
        "例如：1. 000001 平安银行 → 关注：RSI超卖反弹 + MA60支撑，短期有修复空间",
        "不要输出其他无关内容。",
    ]
    return "\n".join(lines)


def _call_ai(settings: dict, prompt: str) -> str:
    """调用配置的 LLM 做机会评估。"""
    provider = (settings or {}).get("provider") or "hermes"
    try:
        if provider in LOCAL_AGENT_NAMES:
            from backend.services.ai_agent import get_agent, run_agent
            spec = get_agent(provider)
            if spec is None:
                return "本地 AI agent 未安装，跳过 AI 评估"
            full_prompt = f"{SYSTEM_PROMPT.strip()}\n\n{prompt}"
            result = run_agent(provider, full_prompt, timeout=180)
            if not result.get("ok"):
                return f"AI 评估失败: {result.get('stderr', '')[:200]}"
            return (result.get("output") or "").strip()
        elif provider == "anthropic":
            content, _, _ = _run_anthropic(settings, prompt, system_prompt=SYSTEM_PROMPT)
            return content
        else:
            content, _, _ = _run_openai(settings, prompt, system_prompt=SYSTEM_PROMPT)
            return content
    except Exception as e:
        logger.exception("AI evaluation failed")
        return f"AI 评估异常: {str(e)[:200]}"


def run_opportunity_scan() -> dict:
    """主入口：扫描自选股 → 取前5 → AI评估 → 存入 DB → 返回结果。"""
    db: Session = SessionLocal()
    try:
        candidates = _scan_watchlist(db)

        if not candidates:
            result = {
                "date": date.today().isoformat(),
                "candidates": [],
                "ai_evaluation": "",
                "generated_at": datetime.now().isoformat(),
            }
        else:
            settings = get_ai_settings_dict()
            ai_prompt = _build_ai_prompt(candidates)
            ai_eval = _call_ai(settings, ai_prompt)

            result = {
                "date": date.today().isoformat(),
                "candidates": [
                    {
                        "code": c["code"],
                        "name": c["name"],
                        "score": c["score"],
                        "reasons": c["reasons"],
                        "price": c.get("price"),
                        "target_price": c.get("target_price"),
                    }
                    for c in candidates
                ],
                "ai_evaluation": ai_eval,
                "generated_at": datetime.now().isoformat(),
            }

        # 存入数据库
        from sqlalchemy import text
        payload_json = json.dumps(result, ensure_ascii=False)
        trade_date = date.today().isoformat()
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT 1 FROM daily_opportunity WHERE trade_date = :d"),
                {"d": trade_date},
            ).fetchone()
            if existing:
                conn.execute(
                    text("UPDATE daily_opportunity SET payload = :p, created_at = :c WHERE trade_date = :d"),
                    {"p": payload_json, "c": datetime.now(), "d": trade_date},
                )
            else:
                conn.execute(
                    text("INSERT INTO daily_opportunity (trade_date, payload, created_at) VALUES (:d, :p, :c)"),
                    {"d": trade_date, "p": payload_json, "c": datetime.now()},
                )

        return result
    finally:
        db.close()


def get_latest_opportunities() -> dict | None:
    """获取最近一次机会扫描结果。"""
    from sqlalchemy import text
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT payload FROM daily_opportunity ORDER BY trade_date DESC LIMIT 1")
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None
