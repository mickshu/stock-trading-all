"""
TradingAgents Web Interface — powered by Chainlit & DeepSeek.

Launch with:
    chainlit run app.py
"""

import os
import asyncio
from pathlib import Path
from datetime import datetime

import chainlit as cl
from chainlit.input_widget import Select, TextInput, Switch
from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG


# ---- Settings Panel ----

@cl.on_chat_start
async def start():
    """Show settings panel for user to configure analysis parameters."""
    settings = await cl.ChatSettings(
        [
            TextInput(
                id="ticker",
                label="股票代码 (Stock Ticker)",
                initial="600000",
                placeholder="A股输入6位代码如 600000，美股输入 NVDA",
            ),
            TextInput(
                id="trade_date",
                label="分析日期 (Analysis Date)",
                initial=datetime.now().strftime("%Y-%m-%d"),
                placeholder="YYYY-MM-DD",
            ),
            Select(
                id="data_source",
                label="数据源 (Data Source)",
                values=["akshare", "yfinance", "tushare"],
                initial_value="akshare",
            ),
            Select(
                id="research_depth",
                label="分析深度 (Research Depth)",
                values=["1", "2", "3"],
                initial_value="1",
                description="Debate rounds: 1=fast, 3=deep analysis",
            ),
            Switch(
                id="online_tools",
                label="使用在线数据 (Online Data)",
                initial=True,
            ),
        ]
    ).send()

    # Store default settings
    cl.user_session.set("settings", {
        "ticker": "600000",
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "akshare",
        "research_depth": 1,
        "online_tools": True,
    })

    await cl.Message(
        content="""# 🏦 TradingAgents —— AI 驱动的股票分析系统

欢迎使用多智能体金融交易分析框架！

**使用步骤：**
1. 点击顶部 ⚙️ 图标配置参数
2. 发送任意消息开始分析
3. 实时观察 AI Agent 分析流程
4. 获取最终 **BUY / HOLD / SELL** 决策

**数据源支持：** 新浪财经 / 东方财富 (A股) + Yahoo Finance (美股)
**模型：** DeepSeek v4 Pro
"""
    ).send()


@cl.on_settings_update
async def on_settings_update(settings):
    """Update session settings when user changes them."""
    cl.user_session.set("settings", settings)
    await cl.Message(
        content=f"✅ 配置已更新：**{settings['ticker']}** @ {settings['trade_date']} | 数据源: {settings['data_source']}"
    ).send()


# ---- Analysis Runner ----

@cl.on_message
async def on_message(msg: cl.Message):
    """Run analysis when user sends a message."""
    settings = cl.user_session.get("settings")

    ticker = settings["ticker"].strip().upper()
    trade_date = settings["trade_date"].strip()
    data_source = settings["data_source"]
    research_depth = int(settings["research_depth"])
    online_tools = settings["online_tools"]

    # Validate inputs
    if not ticker:
        await cl.Message(content="❌ 请输入股票代码").send()
        return

    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError:
        await cl.Message(content="❌ 日期格式错误，请使用 YYYY-MM-DD 格式").send()
        return

    # Build config
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai"
    config["backend_url"] = "https://api.deepseek.com/v1"
    config["deep_think_llm"] = "deepseek-v4-pro"
    config["quick_think_llm"] = "deepseek-v4-pro"
    config["max_debate_rounds"] = research_depth
    config["max_risk_discuss_rounds"] = research_depth
    config["online_tools"] = online_tools
    config["data_source"] = data_source
    config["data_source_fallback"] = ["yfinance"]

    # Status message
    is_cn = ticker.isdigit() and len(ticker) == 6
    market = "🇨🇳 A股" if is_cn else "🇺🇸 美股"

    status_msg = cl.Message(content=f"""
## 🔍 开始分析: **{ticker}** {market}

| 配置项 | 值 |
|--------|-----|
| 分析日期 | {trade_date} |
| 数据源 | {data_source} |
| 分析深度 | {research_depth} 轮辩论 |
| 模型 | DeepSeek v4 Pro |
""")
    await status_msg.send()

    # Initialize graph
    try:
        ta = TradingAgentsGraph(debug=False, config=config)
    except Exception as e:
        await cl.Message(content=f"❌ 初始化失败: {str(e)}").send()
        return

    # Progress steps
    market_step = cl.Step(name="📊 市场分析", type="tool")
    social_step = cl.Step(name="💬 舆情分析", type="tool")
    news_step = cl.Step(name="📰 新闻分析", type="tool")
    funda_step = cl.Step(name="📈 基本面分析", type="tool")
    debate_step = cl.Step(name="⚔️ 多空辩论", type="tool")
    risk_step = cl.Step(name="🛡️ 风险评估", type="tool")

    # Run analysis with progress indicators
    try:
        # Phase 1: Market Analysis
        await market_step.send()
        market_step.input = f"获取 {ticker} 市场数据 & 技术指标..."

        # Phase 2: All analysts run in the graph
        await social_step.send()
        social_step.input = "搜索社交媒体情绪..."

        await news_step.send()
        news_step.input = "收集新闻 & 宏观信息..."

        await funda_step.send()
        funda_step.input = "分析财务基本面..."

        # Run the full graph
        loop = asyncio.get_event_loop()
        final_state, decision = await loop.run_in_executor(
            None, ta.propagate, ticker, trade_date
        )

        # Phase 3: Debate
        await debate_step.send()
        debate_state = final_state.get("investment_debate_state", {})
        debate_step.output = format_debate_output(debate_state)

        await risk_step.send()
        risk_state = final_state.get("risk_debate_state", {})
        risk_step.output = format_risk_output(risk_state)

        # Mark steps complete
        market_step.output = format_section(final_state.get("market_report", ""), "市场分析报告")
        social_step.output = format_section(final_state.get("sentiment_report", ""), "舆情分析报告")
        news_step.output = format_section(final_state.get("news_report", ""), "新闻分析报告")
        funda_step.output = format_section(final_state.get("fundamentals_report", ""), "基本面分析报告")

        await market_step.update()
        await social_step.update()
        await news_step.update()
        await funda_step.update()
        await debate_step.update()
        await risk_step.update()

        # Final decision
        trade_decision = final_state.get("final_trade_decision", "UNKNOWN")
        decision_emoji = {
            "BUY": "🟢",
            "SELL": "🔴",
            "HOLD": "🟡",
        }.get(trade_decision.upper(), "⚪")

        await cl.Message(content=f"""
---

# {decision_emoji} 最终决策: **{trade_decision}**

### 分析摘要

| 分析维度 | 结论 |
|----------|------|
| 📊 市场技术 | {summarize_section(final_state.get('market_report', ''))} |
| 💬 社交媒体 | {summarize_section(final_state.get('sentiment_report', ''))} |
| 📰 新闻宏观 | {summarize_section(final_state.get('news_report', ''))} |
| 📈 基本面 | {summarize_section(final_state.get('fundamentals_report', ''))} |

> 🧠 分析引擎: DeepSeek v4 Pro | 数据源: {data_source}
""").send()

    except Exception as e:
        await cl.Message(content=f"❌ 分析过程出错: {str(e)}").send()
        import traceback
        await cl.Message(content=f"```\n{traceback.format_exc()}\n```").send()


# ---- Formatting Helpers ----

def format_section(report: str, title: str) -> str:
    """Truncate long report for step display."""
    if not report:
        return f"_{title}未生成_"
    if len(report) > 800:
        return report[:800] + "\n\n... (内容过长，已截断)"
    return report


def format_debate_output(debate_state: dict) -> str:
    """Format investment debate output."""
    if not debate_state:
        return "_辩论未进行_"

    parts = []
    bull = debate_state.get("bull_history", [])
    bear = debate_state.get("bear_history", [])
    judge = debate_state.get("judge_decision", "")

    if bull:
        parts.append(f"**多头论点** (共{len(bull)}轮):")
        for i, b in enumerate(bull[-2:], 1):
            content = str(b)[:300]
            parts.append(f"  轮次{i}: {content}...")
    if bear:
        parts.append(f"\n**空头论点** (共{len(bear)}轮):")
        for i, b in enumerate(bear[-2:], 1):
            content = str(b)[:300]
            parts.append(f"  轮次{i}: {content}...")
    if judge:
        parts.append(f"\n**评判**: {str(judge)[:500]}")

    return "\n".join(parts) if parts else "_辩论未生成_"


def format_risk_output(risk_state: dict) -> str:
    """Format risk assessment output."""
    if not risk_state:
        return "_风险评估未进行_"

    parts = []
    current = risk_state.get("current_response", "")
    if current:
        parts.append(str(current)[:500])

    return "\n".join(parts) if parts else "_风险评估未生成_"


def summarize_section(report: str) -> str:
    """Extract key point from a report section."""
    if not report:
        return "未生成"
    # Try to find FINAL TRANSACTION PROPOSAL
    if "FINAL TRANSACTION PROPOSAL" in report:
        idx = report.find("FINAL TRANSACTION PROPOSAL")
        return report[idx:idx+80].replace("\n", " ").strip()
    # Otherwise return last meaningful line
    lines = [l.strip() for l in report.split("\n") if l.strip() and not l.startswith("#")]
    if lines:
        return lines[-1][:100] + ("..." if len(lines[-1]) > 100 else "")
    return "已生成"


# ---- Run standalone ----

if __name__ == "__main__":
    from chainlit.cli import run_chainlit
    run_chainlit(__file__)
