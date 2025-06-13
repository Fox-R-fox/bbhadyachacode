import logging
import pandas as pd
import pandas_ta as ta
import datetime
from indicators import (
    calculate_cpr, calculate_rsi, check_rsi_divergence, 
    check_cpr_breakout, calculate_ema, check_ema_crossover
)

class BaseStrategy:
    """Base class for all trading strategies."""
    def __init__(self, kite, config):
        self.kite = kite
        self.config = config
        self.name = "Base"

    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        """
        Generates 'BUY', 'SELL', or 'HOLD' signals.
        The 'index' argument is now optional. If None, it defaults to the latest candle.
        """
        raise NotImplementedError

class Gemini_Default_Strategy(BaseStrategy):
    """The original Gemini strategy based on CPR, EMA, and RSI."""
    def __init__(self, kite, config):
        super().__init__(kite, config)
        self.name = "Gemini_Default"

    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 1: return 'HOLD'
        if 'ema_50' not in day_df.columns:
            day_df['ema_50'] = calculate_ema(day_df['close'], 50)
        if 'rsi' not in day_df.columns:
            day_df['rsi'] = calculate_rsi(day_df['close'], 14)

        cpr_pivots = kwargs.get('cpr_pivots', {})
        current_candle = day_df.iloc[index]
        
        primary_signal_met = False
        confirmation_signals_met = 0

        cpr_breakout_signal = check_cpr_breakout(current_candle, cpr_pivots, day_df.iloc[index-1])
        if cpr_breakout_signal == sentiment:
            primary_signal_met = True
        
        if primary_signal_met:
            if sentiment == 'Bullish':
                if current_candle['close'] > current_candle['ema_50']: confirmation_signals_met += 1
                if current_candle['rsi'] > 55: confirmation_signals_met += 1
            elif sentiment == 'Bearish':
                if current_candle['close'] < current_candle['ema_50']: confirmation_signals_met += 1
                if current_candle['rsi'] < 45: confirmation_signals_met += 1
        
        logging.debug(f"[{self.name}] Check on {current_candle.name}: Primary Met={primary_signal_met}, Confirmations Met={confirmation_signals_met}")

        if primary_signal_met and confirmation_signals_met >= 1:
            logging.info(f"[{self.name}] Signal confirmed: Primary condition and {confirmation_signals_met} confirmation(s) met.")
            return sentiment.upper()
        
        return 'HOLD'


class Supertrend_MACD_Strategy(BaseStrategy):
    """A trend-following strategy based on Supertrend and MACD."""
    def __init__(self, kite, config):
        super().__init__(kite, config)
        self.name = "Supertrend_MACD"

    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 1: return 'HOLD'
        
        # --- FIX APPLIED: Calculate required indicators ---
        if 'supertrend_direction' not in day_df.columns:
            supertrend = ta.supertrend(day_df['high'], day_df['low'], day_df['close'])
            day_df['supertrend_direction'] = supertrend['SUPERTd_7_3.0']
        if 'macd' not in day_df.columns:
            macd = ta.macd(day_df['close'])
            day_df[['macd', 'macd_signal']] = macd[['MACD_12_26_9', 'MACDs_12_26_9']]
        # --- END OF FIX ---

        current = day_df.iloc[index]
        supertrend_ok = current.get('supertrend_direction') == (1 if sentiment == 'Bullish' else -1)
        macd_ok = (current.get('macd') > current.get('macd_signal')) if sentiment == 'Bullish' else (current.get('macd') < current.get('macd_signal'))
        
        if supertrend_ok and macd_ok:
            logging.info(f"[{self.name}] Signal confirmed: Supertrend and MACD conditions met.")
            return sentiment.upper()
        return 'HOLD'
    
class VolatilityClusterStrategy(BaseStrategy):
    """A reversal strategy based on the concept of Volatility Clustering."""
    def __init__(self, kite, config):
        super().__init__(kite, config)
        self.name = "Volatility_Cluster_Reversal"

    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 20: return 'HOLD'

        # --- FIX APPLIED: Calculate required indicators ---
        if 'atr' not in day_df.columns:
            day_df['atr'] = ta.atr(day_df['high'], day_df['low'], day_df['close'], length=14)
        if 'atr_ma' not in day_df.columns:
            day_df['atr_ma'] = day_df['atr'].rolling(window=20).mean()
        # --- END OF FIX ---
            
        last_completed_candle = day_df.iloc[index - 1]

        if pd.isna(last_completed_candle['atr']) or pd.isna(last_completed_candle['atr_ma']): return 'HOLD'

        is_high_volatility = last_completed_candle['atr'] > last_completed_candle['atr_ma']
        avg_candle_size = day_df['atr'].iloc[index-1]
        last_candle_size = abs(last_completed_candle['open'] - last_completed_candle['close'])
        is_large_move = last_candle_size > (avg_candle_size * 1.5)

        if sentiment == 'Bullish':
            is_reversal_candle = last_completed_candle['close'] < last_completed_candle['open']
            if is_high_volatility and is_large_move and is_reversal_candle:
                logging.info(f"[{self.name}] Reversal BUY signal: High volatility detected after a large down move.")
                return 'BUY'
        elif sentiment == 'Bearish':
            is_reversal_candle = last_completed_candle['close'] > last_completed_candle['open']
            if is_high_volatility and is_large_move and is_reversal_candle:
                logging.info(f"[{self.name}] Reversal SELL signal: High volatility detected after a large up move.")
                return 'SELL'
            
        return 'HOLD'


class VSA_Strategy(BaseStrategy):
    """A strategy based on Volume Spread Analysis (VSA)."""
    def __init__(self, kite, config):
        super().__init__(kite, config)
        self.name = "Volume_Spread_Analysis"

    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 20: return 'HOLD'
        
        # --- FIX APPLIED: Calculate required indicators ---
        if 'volume_ma' not in day_df.columns:
            day_df['volume_ma'] = day_df['volume'].rolling(window=20).mean()
        if 'spread' not in day_df.columns:
            day_df['spread'] = day_df['high'] - day_df['low']
        # --- END OF FIX ---
        
        last_candle = day_df.iloc[index - 1]
        
        is_high_volume = last_candle.get('volume', 0) > (last_candle.get('volume_ma', 0) * 1.3)
        is_wide_spread = last_candle.get('spread', 0) > day_df['spread'].rolling(window=20).mean().iloc[index - 1]
        
        if sentiment == 'Bullish':
            is_down_bar = last_candle['close'] < last_candle['open']
            is_high_close = last_candle['close'] > (last_candle['low'] + last_candle['spread'] * 0.5)
            if is_down_bar and is_high_volume and is_wide_spread and is_high_close:
                logging.info(f"[{self.name}] Signal confirmed: Sign of Strength detected."); return 'BUY'
        
        if sentiment == 'Bearish':
            is_up_bar = last_candle['close'] > last_candle['open']
            is_low_close = last_candle['close'] < (last_candle['low'] + last_candle['spread'] * 0.5)
            if is_up_bar and is_high_volume and is_wide_spread and is_low_close:
                logging.info(f"[{self.name}] Signal confirmed: Sign of Weakness detected."); return 'SELL'
            
        return 'HOLD'

class Momentum_VWAP_RSI_Strategy(BaseStrategy):
    def __init__(self, kite, config): super().__init__(kite, config); self.name = "Momentum_VWAP_RSI"
    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 1: return 'HOLD'
        
        current = day_df.iloc[index]
        if sentiment == 'Bullish' and current['close'] > current['vwap'] and current['rsi'] > 55: return 'BUY'
        if sentiment == 'Bearish' and current['close'] < current['vwap'] and current['rsi'] < 45: return 'SELL'
        return 'HOLD'

class Breakout_Prev_Day_HL_Strategy(BaseStrategy):
    def __init__(self, kite, config): super().__init__(kite, config); self.name = "Breakout_Prev_Day_HL"
    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 1: return 'HOLD'

        cpr = kwargs.get('cpr_pivots', {})
        pdh, pdl = cpr.get('prev_high'), cpr.get('prev_low')
        if not pdh or not pdl: return 'HOLD'
        current, last = day_df.iloc[index], day_df.iloc[index - 1]
        if sentiment == 'Bullish' and last['close'] < pdh and current['close'] > pdh and current['volume'] > (current['volume_ma'] * 1.2): return 'BUY'
        if sentiment == 'Bearish' and last['close'] > pdl and current['close'] < pdl and current['volume'] > (current['volume_ma'] * 1.2): return 'SELL'
        return 'HOLD'
    
class Opening_Range_Breakout_Strategy(BaseStrategy):
    def __init__(self, kite, config):
        super().__init__(kite, config); self.name = "Opening_Range_Breakout"
        self.orb_high = None; self.orb_low = None; self.orb_period_set = False
    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        orb_minutes = self.config['trading_flags'].get('orb_minutes', 30)
        
        # Using the DataFrame's timestamp index directly
        current_time = day_df.index[index].time()
        market_open_time = datetime.time(9, 15)
        orb_end_time = (datetime.datetime.combine(datetime.date.today(), market_open_time) + datetime.timedelta(minutes=orb_minutes)).time()
        
        if not self.orb_period_set and current_time >= orb_end_time:
            orb_df = day_df.between_time(market_open_time.strftime("%H:%M"), orb_end_time.strftime("%H:%M"))
            if not orb_df.empty:
                self.orb_high, self.orb_low = orb_df['high'].max(), orb_df['low'].min()
                self.orb_period_set = True
                logging.info(f"[{self.name}] ORB Set: High={self.orb_high:.2f}, Low={self.orb_low:.2f}, Range={(self.orb_high - self.orb_low):.2f}")
        
        if not self.orb_period_set: return 'HOLD'
        
        # --- FIX APPLIED HERE: Ensure a minimum 10-point stop-loss margin ---
        # The natural stop-loss for an ORB trade is the other side of the range.
        # We only generate a signal if this range is wide enough.
        if (self.orb_high - self.orb_low) < 10:
            logging.debug(f"[{self.name}] ORB range is too narrow ({self.orb_high - self.orb_low:.2f} points). No trades will be taken.")
            return 'HOLD'
        # --- END OF FIX ---

        current, last = day_df.iloc[index], day_df.iloc[index - 1]
        if 'volume_ma' not in day_df.columns: day_df['volume_ma'] = day_df['volume'].rolling(window=20).mean()
        
        if sentiment == 'Bullish' and last['close'] < self.orb_high and current['close'] > self.orb_high and current['volume'] > (current.get('volume_ma', 0) * 1.5):
            logging.info(f"[{self.name}] BUY Signal on ORB High breakout.")
            return 'BUY'
        if sentiment == 'Bearish' and last['close'] > self.orb_low and current['close'] < self.orb_low and current['volume'] > (current.get('volume_ma', 0) * 1.5):
            logging.info(f"[{self.name}] SELL Signal on ORB Low breakdown.")
            return 'SELL'
        return 'HOLD'

class Bollinger_Band_Squeeze_Strategy(BaseStrategy):
    def __init__(self, kite, config): super().__init__(kite, config); self.name = "BB_Squeeze_Breakout"
    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 1: return 'HOLD'

        current, last = day_df.iloc[index], day_df.iloc[index - 1]
        if current['bb_bandwidth'] < current['bb_bandwidth_ma']:
            if sentiment == 'Bullish' and last['close'] < last['bb_upper'] and current['close'] > current['bb_upper']: return 'BUY'
            if sentiment == 'Bearish' and last['close'] > last['bb_lower'] and current['close'] < current['bb_lower']: return 'SELL'
        return 'HOLD'

class MA_Crossover_Strategy(BaseStrategy):
    def __init__(self, kite, config): super().__init__(kite, config); self.name = "MA_Crossover"
    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 1: return 'HOLD'

        current, last = day_df.iloc[index], day_df.iloc[index - 1]
        if sentiment == 'Bullish' and last['ema_9'] <= last['ema_21'] and current['ema_9'] > current['ema_21']: return 'BUY'
        if sentiment == 'Bearish' and last['ema_9'] >= last['ema_21'] and current['ema_9'] < current['ema_21']: return 'SELL'
        return 'HOLD'

class RSI_Divergence_Strategy(BaseStrategy):
    def __init__(self, kite, config): super().__init__(kite, config); self.name = "RSI_Divergence"
    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        
        divergence = check_rsi_divergence(day_df.iloc[:index + 1], day_df['rsi'].iloc[:index + 1])
        if sentiment == 'Bullish' and divergence == 'Bullish': return 'BUY'
        if sentiment == 'Bearish' and divergence == 'Bearish': return 'SELL'
        return 'HOLD'

class EMACrossRSIStrategy(BaseStrategy):
    def __init__(self, kite, config):
        super().__init__(kite, config)
        self.name = "EMA_Cross_RSI"

    def generate_signals(self, day_df, sentiment, index=None, **kwargs):
        if index is None: index = len(day_df) - 1
        if index < 2: return 'HOLD'
        
        # --- FIX APPLIED: Calculate required indicators ---
        if 'ema_9' not in day_df.columns: day_df['ema_9'] = calculate_ema(day_df['close'], 9)
        if 'ema_15' not in day_df.columns: day_df['ema_15'] = calculate_ema(day_df['close'], 15)
        if 'rsi' not in day_df.columns: day_df['rsi'] = calculate_rsi(day_df['close'], 14)
        # --- END OF FIX ---
        
        signal_candle, prev_candle = day_df.iloc[index], day_df.iloc[index - 1]
        was_below = prev_candle['ema_9'] < prev_candle['ema_15']
        is_above = signal_candle['ema_9'] > signal_candle['ema_15']
        was_above = prev_candle['ema_9'] > prev_candle['ema_15']
        is_below = signal_candle['ema_9'] < signal_candle['ema_15']

        if sentiment == 'Bullish' and was_below and is_above and signal_candle['rsi'] > 50 and signal_candle['close'] > signal_candle['ema_9']:
            logging.info(f"[{self.name}] Signal confirmed: 9/15 EMA Golden Cross with RSI > 50.")
            return 'BUY'
        elif sentiment == 'Bearish' and was_above and is_below and signal_candle['rsi'] < 50 and signal_candle['close'] < signal_candle['ema_9']:
            logging.info(f"[{self.name}] Signal confirmed: 9/15 EMA Death Cross with RSI < 50.")
            return 'SELL'
        return 'HOLD'

def get_strategy(name, kite, config):
    """Factory function to get a strategy instance by name."""
    strategies = {
        "Gemini_Default": Gemini_Default_Strategy, 
        "Supertrend_MACD": Supertrend_MACD_Strategy,
        "Volatility_Cluster_Reversal": VolatilityClusterStrategy,
        "Volume_Spread_Analysis": VSA_Strategy, 
        "Momentum_VWAP_RSI": Momentum_VWAP_RSI_Strategy,
        "Breakout_Prev_Day_HL": Breakout_Prev_Day_HL_Strategy,
        "Opening_Range_Breakout": Opening_Range_Breakout_Strategy,
        "BB_Squeeze_Breakout": Bollinger_Band_Squeeze_Strategy,
        "MA_Crossover": MA_Crossover_Strategy, 
        "RSI_Divergence": RSI_Divergence_Strategy,
        "EMA_Cross_RSI": EMACrossRSIStrategy,
    }
    strategy_class = strategies.get(name)
    if not strategy_class: raise ValueError(f"Strategy '{name}' not found.")
    return strategy_class(kite, config)
