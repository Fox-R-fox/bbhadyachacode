Adaptive AI Trading Framework (v2)
This is an experimental, hyper-advanced framework for an autonomous options trading bot. It uses a multi-stage AI process to analyze market conditions, recommend the best strategy, validate it via backtesting, and execute trades with proper risk management.

CRITICAL DISCLAIMER: This is a sophisticated software project intended for educational exploration ONLY. Algorithmic trading is extremely risky. Do NOT use this bot with real money. The author and code bear no responsibility for any financial losses.

Core Architecture & Workflow

The bot's pre-market setup is a fully automated strategy competition:

Context Analysis: The bot identifies today's market "context," including volatility (VIX) and major economic events.

AI Strategy Recommendation: A LangGraph agent recommends the best strategy from a diverse pool.

Conditional Backtesting: Validates the AI's choice against relevant historical data.

Parallel Processing: Uses multiple CPU cores for high-speed backtesting.

Data-Driven Selection & Execution: The strategy with the highest relevant win rate is selected and deployed.

Proper Stop-Loss: A percentage-based stop-loss is now correctly calculated based on the option's premium, ensuring trades are not exited prematurely.

Setup Instructions

Get API Keys: You need keys for Zerodha and NewsAPI. The Gemini agent uses a keyless model by default in the Canvas environment but can be configured to use your key.

Install Dependencies: Run brew install ta-lib (on macOS), then pip install -r requirements.txt, and finally python -m textblob.download_corpora.

Configure config.yaml:

Enter your API keys.

Set the stop_loss_percent to define your risk on each trade (e.g., 10.0 for 10%).

Configure other flags like paper_trading, backtest_years, and win_rate_threshold.

Run: Execute python trading_bot.py.

