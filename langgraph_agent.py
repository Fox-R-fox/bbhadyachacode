import logging
import json
import asyncio
import aiohttp
from typing import TypedDict

class LangGraphAgent:
    """AI agent using Google's Gemini API to recommend a strategy from a full suite."""
    def __init__(self, config):
        self.config = config
        self.api_key = config.get('google_api', {}).get('api_key', "")
        self.model_name = "gemini-2.0-flash"

    async def get_recommended_strategy(self, market_conditions: set):
        """
        Gets a strategy recommendation directly from the Gemini API, considering all available strategies.
        """
        if not self.api_key:
            logging.error("[Gemini Agent] Google API key not found in config.yaml. Defaulting strategy.")
            return "Gemini_Default"
            
        logging.info(f"[Gemini Agent] Market Conditions: {market_conditions}. Recommending strategy...")
        
        prompt = f"""You are an expert intraday options trading strategist for the Indian NIFTY 50 index.
Based on these market conditions: {", ".join(market_conditions)}, which single trading strategy from the list below has the highest probability of success today?

**Available Strategies:**
1.  **'Gemini_Default'**: A balanced, multi-indicator strategy (CPR, EMA, RSI Divergence). A good all-rounder for low to medium volatility.
2.  **'Supertrend_MACD'**: A strong trend-following strategy. Best for medium volatility when a clear directional trend is expected.
3.  **'Volatility_Cluster_Reversal'**: A counter-trend strategy. Best for high volatility days to capture reversals after large, exhaustive moves.
4.  **'Volume_Spread_Analysis'**: A specialized strategy to detect smart money activity (accumulation/distribution). Excels at identifying the underlying strength or weakness in a market.
5.  **'EMA_Cross_RSI'**: A classic, fast-acting momentum strategy using a 9/15 EMA crossover confirmed by RSI. Good for capturing short, quick trends.
6.  **'Momentum_VWAP_RSI'**: A momentum strategy using VWAP as a dynamic support/resistance level. Good for trending days.
7.  **'Breakout_Prev_Day_HL'**: A breakout strategy triggering when the previous day's high or low is breached with significant volume.
8.  **'Opening_Range_Breakout'**: A classic ORB strategy that trades breakouts from the initial market range (e.g., first 30 mins).
9.  **'BB_Squeeze_Breakout'**: A volatility breakout strategy that waits for low volatility (Bollinger Bands squeeze) and then trades the subsequent expansion.
10. **'MA_Crossover'**: A simple and classic moving average crossover strategy (e.g., 9/21 EMA).
11. **'RSI_Divergence'**: A pure reversal strategy focusing only on bullish or bearish divergence between price and the RSI indicator.

Your recommendation (return only the single, most appropriate strategy name from the list):"""

        try:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}

            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload) as response:
                    response.raise_for_status()
                    result = await response.json()

            if (result.get("candidates") and result["candidates"][0].get("content") and 
                result["candidates"][0]["content"].get("parts")):
                recommended_strategy = result["candidates"][0]["content"]["parts"][0]["text"].strip().replace("'", "")
            else:
                raise ValueError("Invalid response structure from Gemini API")

            valid_strategies = [
                "Gemini_Default", "Supertrend_MACD", "Volatility_Cluster_Reversal", 
                "Volume_Spread_Analysis", "EMA_Cross_RSI", "Momentum_VWAP_RSI",
                "Breakout_Prev_Day_HL", "Opening_Range_Breakout", "BB_Squeeze_Breakout",
                "MA_Crossover", "RSI_Divergence"
            ]
            if recommended_strategy not in valid_strategies:
                logging.warning(f"[Gemini Agent] LLM recommended unknown strategy: '{recommended_strategy}'. Defaulting.")
                recommended_strategy = "Gemini_Default"
            
            logging.info(f"[Gemini Agent] AI Recommended Strategy: {recommended_strategy}")
            return recommended_strategy

        except Exception as e:
            logging.error(f"[Gemini Agent] Error calling Gemini API: {e}. Defaulting to Gemini_Default.")
            return "Gemini_Default"
