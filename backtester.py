import pandas as pd
import datetime
import logging
import yaml
from kiteconnect import KiteConnect
from indicators import *

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config():
    with open('config.yaml', 'r') as file: return yaml.safe_load(file)

def run_backtest(kite, config, from_date, to_date):
    underlying_name = config['trading_flags']['underlying_instrument']
    signals_config = config['strategy_signals']
    timeframe = config['trading_flags']['chart_timeframe']
    
    token = [i['instrument_token'] for i in kite.instruments('NSE') if i['tradingsymbol'] == underlying_name][0]

    all_data_day = kite.historical_data(token, from_date, to_date, "day", continuous=True)
    all_data_tf = kite.historical_data(token, from_date, to_date, timeframe, continuous=True)
    
    daily_df = pd.DataFrame(all_data_day)
    daily_df['date'] = pd.to_datetime(daily_df['date']).dt.date
    df_tf = pd.DataFrame(all_data_tf)
    df_tf['date_only'] = pd.to_datetime(df_tf['date']).dt.date

    trades = []
    logging.info(f"Starting backtest from {from_date} to {to_date}...")

    for i in range(1, len(daily_df)):
        current_date = daily_df.iloc[i]['date']
        day_tf_df = df_tf[df_tf['date_only'] == current_date].copy()
        if day_tf_df.empty or len(day_tf_df) < 50: continue # Need enough data for indicators

        cpr_pivots = calculate_cpr(daily_df.iloc[i-1:i])
        day_sentiment = "Bullish" if daily_df.iloc[i-1]['close'] > cpr_pivots.get('pivot', 0) else "Bearish"
        
        # Calculate indicators for the whole day at once
        day_tf_df['rsi'] = calculate_rsi(day_tf_df['close'])
        if signals_config['use_ema_20_crossover']: day_tf_df['ema_20'] = calculate_ema(day_tf_df['close'], 20)
        if signals_config['use_ema_50_crossover']: day_tf_df['ema_50'] = calculate_ema(day_tf_df['close'], 50)
        
        position = None
        for j in range(30, len(day_tf_df)): # Start after enough data for divergence calc
            if position: # Simplified exit for backtesting
                if position == 'BUY' and day_tf_df.iloc[j]['close'] < cpr_pivots['pivot']:
                    trades.append({'entry': entry_price, 'exit': day_tf_df.iloc[j]['close'], 'type': 'BUY'})
                    position = None
                elif position == 'SELL' and day_tf_df.iloc[j]['close'] > cpr_pivots['pivot']:
                    trades.append({'entry': entry_price, 'exit': day_tf_df.iloc[j]['close'], 'type': 'SELL'})
                    position = None
            
            if not position:
                hist_slice = day_tf_df.iloc[:j+1]
                current_candle = day_tf_df.iloc[j]; last_candle = day_tf_df.iloc[j-1]
                
                signal_votes = []
                if signals_config['use_rsi_divergence']: signal_votes.append(check_rsi_divergence(hist_slice, hist_slice['rsi']))
                if signals_config['use_cpr_breakout']: signal_votes.append(check_cpr_breakout(current_candle, cpr_pivots, last_candle))
                if signals_config['use_ema_20_crossover']: signal_votes.append(check_ema_crossover(hist_slice, current_candle, last_candle, 20))
                if signals_config['use_ema_50_crossover']: signal_votes.append(check_ema_crossover(hist_slice, current_candle, last_candle, 50))
                
                if day_sentiment == "Bullish" and all(s == 'Bullish' for s in signal_votes if s != 'None'):
                    position = 'BUY'; entry_price = current_candle['close']
                elif day_sentiment == "Bearish" and all(s == 'Bearish' for s in signal_votes if s != 'None'):
                    position = 'SELL'; entry_price = current_candle['close']
    
    # --- Analyze Results ---
    wins = sum(1 for t in trades if (t['type'] == 'BUY' and t['exit'] > t['entry']) or (t['type'] == 'SELL' and t['exit'] < t['entry']))
    logging.info("\n--- BACKTEST RESULTS ---")
    logging.info(f"Total Signals Generated: {len(trades)}")
    logging.info(f"Winning Signals: {wins}")
    logging.info(f"Win Probability: {(wins / len(trades) * 100) if trades else 0:.2f}%")
    logging.info("------------------------\n")

if __name__ == "__main__":
    config = load_config()
    kite = KiteConnect(api_key=config['zerodha']['api_key'])
    if not config['zerodha'].get('access_token'):
        print("Access token not found. Please run trading_bot.py first.")
    else:
        kite.set_access_token(config['zerodha']['access_token'])
        from_date = datetime.date(2023, 12, 1); to_date = datetime.date(2023, 12, 31)
        run_backtest(kite, config, from_date, to_date)
