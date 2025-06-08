import logging
import pandas as pd
import datetime
from indicators import *

class SignalAgent:
    """Analyzes market data and generates trading signals based on strategy flags."""
    def __init__(self, kite, config):
        self.kite = kite
        self.config = config
        self.signals_config = config['strategy_signals']
        self.trading_flags = config['trading_flags']
        self.underlying_token = self._get_instrument_token(self.trading_flags['underlying_instrument'], 'NSE')
        self.vix_token = self._get_instrument_token('INDIA VIX', 'NSE')

    def _get_instrument_token(self, name, exchange):
        """Helper to find instrument token."""
        instruments = self.kite.instruments(exchange)
        token = [i['instrument_token'] for i in instruments if i['tradingsymbol'] == name]
        if not token:
            raise ValueError(f"Could not find instrument token for {name}")
        return token[0]
        
    def check_for_signals(self, hist_df, cpr_pivots, sentiment):
        """
        The main signal generation method. Returns 'BUY', 'SELL', or 'HOLD'.
        """
        # --- Pre-Trade Checks ---
        vix_ltp = self.kite.ltp(self.vix_token)[str(self.vix_token)]['last_price']
        if vix_ltp > self.trading_flags['max_vix_level']:
            logging.warning(f"VIX is {vix_ltp}, above max level. Holding.")
            return 'HOLD'

        # --- Indicator Calculations ---
        self._calculate_all_indicators(hist_df)
        
        current_candle = hist_df.iloc[-1]
        last_candle = hist_df.iloc[-2]
        
        # --- Collect Signal Votes ---
        signals = []
        if self.signals_config['use_rsi_divergence']:
            signals.append(check_rsi_divergence(hist_df, hist_df['rsi']))
        if self.signals_config['use_cpr_breakout']:
            signals.append(check_cpr_breakout(current_candle, cpr_pivots, last_candle))
        if self.signals_config['use_ema_20_crossover']:
            signals.append(check_ema_crossover(hist_df, current_candle, last_candle, 20))
        if self.signals_config['use_ema_50_crossover']:
            signals.append(check_ema_crossover(hist_df, current_candle, last_candle, 50))
        if self.signals_config['use_lex_algo']:
            signals.append(lex_algo_supply_demand(hist_df))

        # --- Decision Logic ---
        if sentiment == 'Bullish':
            # All enabled signals must vote 'Bullish'
            if all(s == 'Bullish' for s in signals if s != 'None'):
                logging.info(f"BUY signal confirmed by: {signals}")
                return 'BUY'
        elif sentiment == 'Bearish':
            # All enabled signals must vote 'Bearish'
            if all(s == 'Bearish' for s in signals if s != 'None'):
                logging.info(f"SELL signal confirmed by: {signals}")
                return 'SELL'

        return 'HOLD'

    def _calculate_all_indicators(self, df):
        """A helper to calculate and attach all required indicators to the dataframe."""
        df['rsi'] = calculate_rsi(df['close'])
        if self.signals_config['use_ema_20_crossover']:
            df['ema_20'] = calculate_ema(df['close'], 20)
        if self.signals_config['use_ema_50_crossover']:
            df['ema_50'] = calculate_ema(df['close'], 50)

class OrderExecutionAgent:
    """Handles order sizing, placement, and retrieval."""
    def __init__(self, kite, config):
        self.kite = kite
        self.config = config
        self.flags = config['trading_flags']
        self.nfo_instruments = pd.DataFrame(kite.instruments('NFO'))
        self.underlying_token = self._get_instrument_token(self.flags['underlying_instrument'], 'NSE')

    def _get_instrument_token(self, name, exchange):
        """Helper to find instrument token."""
        return [i['instrument_token'] for i in self.kite.instruments(exchange) if i['tradingsymbol'] == name][0]

    def place_trade(self, direction):
        """Calculates quantity and places a market order."""
        symbol, qty = self._get_trade_details(direction)
        if not symbol or not qty:
            return None

        try:
            order_id = self.kite.place_order(
                tradingsymbol=symbol,
                exchange=self.kite.EXCHANGE_NFO,
                transaction_type=self.kite.TRANSACTION_TYPE_BUY, # We always buy options (CE for Bullish, PE for Bearish)
                quantity=qty,
                product=self.flags['product_type'],
                order_type=self.kite.ORDER_TYPE_MARKET,
                variety=self.flags['order_variety']
            )
            logging.info(f"Order placed successfully for {symbol}. Order ID: {order_id}")
            # Wait for order confirmation
            import time
            time.sleep(1) 
            order_history = self.kite.order_history(order_id)
            avg_price = [o['average_price'] for o in order_history if o['status'] == 'COMPLETE']
            if not avg_price or avg_price[0] == 0:
                raise Exception("Order did not execute or price is zero.")

            return {
                'order_id': order_id, 'symbol': symbol, 'quantity': qty,
                'entry_price': avg_price[0], 'type': 'BUY' if direction == 'BUY' else 'SELL'
            }
        except Exception as e:
            logging.error(f"Failed to place order for {symbol}: {e}")
            return None

    def _get_trade_details(self, direction):
        ltp = self.kite.ltp(self.underlying_token)[str(self.underlying_token)]['last_price']
        atm_strike = round(ltp / 50) * 50
        otm_strike = atm_strike + 50 if direction == 'BUY' else atm_strike - 50
        option_type = 'CE' if direction == 'BUY' else 'PE'
        
        today = datetime.date.today()
        # Logic to find the nearest weekly expiry (usually Thursday)
        days_to_thursday = (3 - today.weekday() + 7) % 7
        expiry_date = today + datetime.timedelta(days=days_to_thursday)

        target = self.nfo_instruments[
            (self.nfo_instruments['name'] == self.flags['underlying_instrument'].split(" ")[0]) &
            (self.nfo_instruments['strike'] == otm_strike) &
            (self.nfo_instruments['instrument_type'] == option_type) &
            (pd.to_datetime(self.nfo_instruments['expiry']).dt.date == expiry_date)
        ]
        if target.empty: return None, 0
        
        symbol = target.iloc[0]['tradingsymbol']
        lot_size = target.iloc[0]['lot_size']
        
        margins = self.kite.margins()
        capital = margins['equity']['available']['live_balance']
        risk_amount = capital * (self.flags['risk_per_trade_percent'] / 100)
        
        option_price = self.kite.ltp(f"NFO:{symbol}")[f"NFO:{symbol}"]['last_price']
        if option_price == 0: return None, 0

        num_lots = int(risk_amount / (option_price * lot_size))
        quantity = max(1, num_lots) * lot_size
        
        return symbol, quantity

class PositionManagementAgent:
    """Monitors active trades and manages exits based on SL/TSL rules."""
    # This is a complex agent and the logic below is a foundational structure.
    # Real-world TSL requires robust WebSocket integration for real-time ticks.
    # This implementation polls, which is a good starting point.
    
    def __init__(self, kite, config, cpr_pivots):
        self.kite = kite
        self.config = config
        self.cpr_pivots = cpr_pivots
        self.active_trade = None

    def manage(self):
        """The main management loop to be called repeatedly."""
        if not self.active_trade:
            return None # No active trade to manage

        symbol = self.active_trade['symbol']
        ltp_data = self.kite.ltp(f"NFO:{symbol}")
        current_price = ltp_data[f"NFO:{symbol}"]['last_price']

        # Check if stop loss is hit
        if current_price <= self.active_trade['stop_loss']:
            logging.info(f"Stop loss hit for {symbol} at {current_price}. Exiting trade.")
            return self.exit_trade()

        # Update Trailing Stop Loss (TSL)
        new_sl = self._calculate_trailing_sl(current_price)
        if new_sl > self.active_trade['stop_loss']:
            self.active_trade['stop_loss'] = new_sl
            logging.info(f"TSL updated for {symbol} to {new_sl}")
        
        return "ACTIVE" # Position is still active

    def start_trade(self, trade_details):
        """Initializes management for a new trade by setting the initial SL."""
        self.active_trade = trade_details
        self.active_trade['stop_loss'] = self._calculate_initial_sl()
        logging.info(f"Managing new trade for {self.active_trade['symbol']}. Initial SL set to {self.active_trade['stop_loss']}.")

    def exit_trade(self):
        """Exits the current active trade at market price."""
        trade_to_exit = self.active_trade
        try:
            self.kite.place_order(
                tradingsymbol=trade_to_exit['symbol'],
                exchange=self.kite.EXCHANGE_NFO,
                transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                quantity=trade_to_exit['quantity'],
                product=self.config['trading_flags']['product_type'],
                order_type=self.kite.ORDER_TYPE_MARKET,
                variety=self.config['trading_flags']['order_variety']
            )
            # Simplified exit price logic, in reality, you'd confirm from order history
            exit_price = self.kite.ltp(f"NFO:{trade_to_exit['symbol']}")[f"NFO:{trade_to_exit['symbol']}"]['last_price']
            
            pnl = (exit_price - trade_to_exit['entry_price']) * trade_to_exit['quantity']
            if trade_to_exit['type'] == 'SELL': # If it was a PE buy (short position)
                pnl = -pnl

            completed_trade = {
                'Timestamp': datetime.datetime.now(),
                'Symbol': trade_to_exit['symbol'],
                'TradeType': trade_to_exit['type'],
                'EntryPrice': trade_to_exit['entry_price'],
                'ExitPrice': exit_price,
                'Quantity': trade_to_exit['quantity'],
                'ProfitLoss': pnl,
                'Status': 'CLOSED'
            }
            self.active_trade = None # Clear active trade
            return completed_trade
        except Exception as e:
            logging.error(f"Failed to exit trade for {trade_to_exit['symbol']}: {e}")
            return None # Failed to exit

    def _calculate_initial_sl(self):
        """Calculates SL based on the nearest pivot."""
        price = self.active_trade['entry_price']
        pivots = self.cpr_pivots
        if self.active_trade['type'] == 'BUY': # Long CE
            # Find nearest support pivot below entry
            supports = sorted([p for p in [pivots.get(k) for k in ['s1','s2','s3','pivot','bc']] if p and p < price], reverse=True)
            return (supports[0] - 5) if supports else price * 0.9 # Fallback to 10% SL
        else: # Long PE
            # Find nearest resistance pivot above entry
            resistances = sorted([p for p in [pivots.get(k) for k in ['r1','r2','r3','pivot','tc']] if p and p > price])
            return (resistances[0] + 5) if resistances else price * 1.1 # Fallback to 10% SL

    def _calculate_trailing_sl(self, current_price):
        """Calculates new TSL based on pivot progression. Highly simplified."""
        # This logic can get very complex. This is a basic implementation.
        # A full implementation would track which pivot was last crossed.
        return self.active_trade['stop_loss'] # For now, we don't trail to keep it simple and safe.

