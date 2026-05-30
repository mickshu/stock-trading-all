"""TradingAgents 多智能体框架的后端包装层。

把 backend AppSetting (LLM provider/key/model/base_url) 与 active data_source 注入
tradingagents.default_config，跑 TradingAgentsGraph.propagate，返回前端可消费的字段。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.api.settings import get_ai_settings_dict
from backend.config import settings as bs

logger = logging.getLogger(__name__)


def _build_ta_config(depth: int, online_tools: bool) -> dict[str, Any]:
    """合并 AppSetting + 数据源设置 → tradingagents config dict。"""
    from tradingagents.default_config import DEFAULT_CONFIG

    ai = get_ai_settings_dict()
    cfg: dict[str, Any] = dict(DEFAULT_CONFIG)

    provider = (ai.get("provider") or "openai").lower()
    if provider in ("hermes", "openai"):
        cfg["llm_provider"] = "openai"
        cfg["backend_url"] = (
            ai.get("ta_backend_url")
            or ai.get("openai_base_url")
            or "https://api.deepseek.com/v1"
        )
        model = ai.get("ta_deep_think_llm") or ai.get("openai_model") or "deepseek-v4-pro"
        cfg["deep_think_llm"] = model
        cfg["quick_think_llm"] = ai.get("ta_quick_think_llm") or model
        key = ai.get("openai_api_key") or ""
        if key:
            os.environ["OPENAI_API_KEY"] = key
    elif provider == "anthropic":
        cfg["llm_provider"] = "anthropic"
        cfg["backend_url"] = ai.get("ta_backend_url") or "https://api.anthropic.com"
        model = ai.get("ta_deep_think_llm") or ai.get("anthropic_model") or "claude-sonnet-4-6"
        cfg["deep_think_llm"] = model
        cfg["quick_think_llm"] = ai.get("ta_quick_think_llm") or model
        key = ai.get("anthropic_api_key") or ""
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
    else:
        raise ValueError(f"unsupported provider for tradingagents: {provider}")

    cfg["max_debate_rounds"] = int(ai.get("ta_max_debate_rounds") or depth or 1)
    cfg["max_risk_discuss_rounds"] = cfg["max_debate_rounds"]
    cfg["online_tools"] = bool(online_tools)
    cfg["data_source"] = bs.active_data_source or "akshare"
    cfg["data_source_fallback"] = ["yfinance"]
    return cfg


def _summarize(report: str, *, fallback: str = "未生成") -> str:
    if not report:
        return fallback
    if "FINAL TRANSACTION PROPOSAL" in report:
        i = report.find("FINAL TRANSACTION PROPOSAL")
        return report[i : i + 120].replace("\n", " ").strip()
    lines = [ln.strip() for ln in report.splitlines() if ln.strip() and not ln.startswith("#")]
    return (lines[-1][:160] + "...") if lines else "已生成"


def run_single(ticker: str, trade_date: str, depth: int, online_tools: bool) -> dict[str, Any]:
    """同步跑一次单股分析。返回结构化结果。"""
    cfg = _build_ta_config(depth=depth, online_tools=online_tools)

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    ta = TradingAgentsGraph(debug=False, config=cfg)
    final_state, decision = ta.propagate(ticker, trade_date)

    market = final_state.get("market_report", "") or ""
    sentiment = final_state.get("sentiment_report", "") or ""
    news = final_state.get("news_report", "") or ""
    funda = final_state.get("fundamentals_report", "") or ""
    debate_state = final_state.get("investment_debate_state", {}) or {}
    risk_state = final_state.get("risk_debate_state", {}) or {}
    final_trade_decision = final_state.get("final_trade_decision", "") or str(decision or "")

    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "decision": final_trade_decision,
        "summary": {
            "market": _summarize(market),
            "sentiment": _summarize(sentiment),
            "news": _summarize(news),
            "fundamentals": _summarize(funda),
        },
        "reports": {
            "market": market,
            "sentiment": sentiment,
            "news": news,
            "fundamentals": funda,
        },
        "debate": {
            "bull_history": debate_state.get("bull_history", []),
            "bear_history": debate_state.get("bear_history", []),
            "judge_decision": debate_state.get("judge_decision", ""),
        },
        "risk": {
            "current_response": risk_state.get("current_response", ""),
        },
        "config": {
            "llm_provider": cfg["llm_provider"],
            "deep_think_llm": cfg["deep_think_llm"],
            "quick_think_llm": cfg["quick_think_llm"],
            "data_source": cfg["data_source"],
            "max_debate_rounds": cfg["max_debate_rounds"],
            "online_tools": cfg["online_tools"],
        },
    }
