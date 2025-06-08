import pandas as pd
import numpy as np
import talib

def calculate_cpr(df_prev_day):
    """Calculates Central Pivot Range (CPR) and standard pivots."""
    if df_prev_day.empty:
        return {}
    high = df_prev_day['high'].iloc[-1]
    low = df_prev_day['low'].iloc[-1]
    close = df_prev_day['close'].iloc[-1]

    pivot = (high + low + close) / 3
    bc = (high + low) / 2
    tc = (pivot - bc) + pivot

    r1 = (2 * pivot) - low; s1 = (2 * pivot) - high
    r2 = pivot + (high - low); s2 = pivot - (high - low)
    r3 = high + 2 * (pivot - low); s3 = low - 2 * (high - pivot)

    pivots = {'pivot': pivot, 'bc': bc, 'tc': tc, 'r1': r1, 'r2': r2, 'r3': r3, 's1': s1, 's2': s2, 's3': s3}
    if pivots['tc'] < pivots['bc']:
        pivots['tc'], pivots['bc'] = pivots['bc'], pivots['tc']
    return pivots

def calculate_ema(prices, period):
    """Calculates the Exponential Moving Average (EMA)."""
    return talib.EMA(prices, timeperiod=period)

def calculate_rsi(prices, period=14):
    """Calculates the Relative Strength Index (RSI)."""
    return talib.RSI(prices, timeperiod=period)

def check_ema_crossover(df, current_candle, last_candle, period):
    """Checks for a bullish or bearish EMA crossover for two consecutive candles."""
    ema_col = f'ema_{period}'
    price = current_candle['close']
    last_price = last_candle['close']
    ema_val = current_candle[ema_col]
    last_ema_val = last_candle[ema_col]
    
    # Bullish Crossover: Price crossed above EMA and stayed above
    if price > ema_val and last_price > last_ema_val:
        return "Bullish"
    # Bearish Crossover: Price crossed below EMA and stayed below
    if price < ema_val and last_price < last_ema_val:
        return "Bearish"
    
    return "None"

def check_rsi_divergence(price_df, rsi_series):
    """Simplified check for bullish/bearish RSI divergence."""
    period = -30
    low_prices = price_df['low'][period:]; high_prices = price_df['high'][period:]
    rsi_values = rsi_series[period:]

    if rsi_values.empty or len(rsi_values) < 2: return "None"

    if low_prices.iloc[-1] < low_prices.iloc[:-1].min() and rsi_values.iloc[-1] > rsi_values.iloc[:-1].min():
        return "Bullish"
    if high_prices.iloc[-1] > high_prices.iloc[:-1].max() and rsi_values.iloc[-1] < rsi_values.iloc[:-1].max():
        return "Bearish"
    return "None"

def check_cpr_breakout(current_candle, cpr_pivots, last_candle):
    """Checks for a bullish or bearish breakout from the CPR."""
    if not cpr_pivots: return "None"
    price = current_candle['close']; last_price = last_candle['close']
    tc = cpr_pivots['tc']; bc = cpr_pivots['bc']

    if price > tc and last_price > tc: return "Bullish"
    if price < bc and last_price < bc: return "Bearish"
    return "None"

def lex_algo_supply_demand(df):
    """PLACEHOLDER for the 'Lex Algo Supply & Demand' indicator."""
    return "None"
