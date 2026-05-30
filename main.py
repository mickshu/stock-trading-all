from dotenv import load_dotenv
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Create a custom config for DeepSeek
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"  # DeepSeek uses OpenAI-compatible API
config["backend_url"] = "https://api.deepseek.com/v1"  # DeepSeek endpoint
config["deep_think_llm"] = "deepseek-v4-pro"  # DeepSeek v4 Pro model
config["quick_think_llm"] = "deepseek-v4-pro"  # DeepSeek v4 Pro model
config["max_debate_rounds"] = 1
config["online_tools"] = True
config["data_source"] = "akshare"  # Use 东方财富 via akshare for Chinese stocks
config["data_source_fallback"] = ["yfinance"]  # Fallback to Yahoo Finance

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate with Chinese stock using akshare
_, decision = ta.propagate("600000", "2024-05-10")
print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
