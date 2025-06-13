import logging
import pandas as pd
import pandas_ta as ta

import datetime
from kiteconnect import KiteConnect

class OrderExecutionAgent:
    """Handles order sizing, placement, and retrieval."""
    def __init__(self, kite: KiteConnect, config: dict):
        self.kite = kite
        self.config = config
        self.flags = config['trading_flags']
        self.nfo_instruments = pd.DataFrame(kite.instruments('NFO'))
        self.underlying_token = self._get_instrument_token(self.flags['underlying_instrument'], 'NSE')

    def _get_instrument_token(self, name, exchange):
        """Helper to find instrument token."""
        return [i['instrument_token'] for i in self.kite.instruments(exchange) if i['tradingsymbol'] == name][0]

    def place_trade(self, direction):
        """Calculates quantity and places a market order for a live trade."""
        symbol, qty = self._get_trade_details(direction)
        if not symbol or not qty:
            return None
        try:
            order_id = self.kite.place_order(
                tradingsymbol=symbol,
                exchange=self.kite.EXCHANGE_NFO,
                transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                quantity=qty,
                product=self.flags['product_type'],
                order_type=self.kite.ORDER_TYPE_MARKET,
                variety=self.flags['order_variety']
            )
            logging.info(f"LIVE order placed for {symbol}. Order ID: {order_id}")
            import time; time.sleep(1) 
            order_history = self.kite.order_history(order_id)
            avg_price = [o['average_price'] for o in order_history if o['status'] == 'COMPLETE']
            if not avg_price or avg_price[0] == 0:
                raise Exception("Order did not execute or price is zero.")
            return {'order_id': order_id, 'symbol': symbol, 'quantity': qty, 'entry_price': avg_price[0], 'type': direction}
        except Exception as e:
            logging.error(f"Failed to place live order for {symbol}: {e}")
            return None

    def get_paper_trade_details(self, direction):
        """Simulates getting trade details for paper trading without placing a real order."""
        symbol, qty = self._get_trade_details(direction)
        if not symbol or not qty:
            return None
        try:
            entry_price = self.kite.ltp(f"NFO:{symbol}")[f"NFO:{symbol}"]['last_price']
            logging.info(f"[Paper Trade] Signal for {symbol} at price {entry_price}")
            return {'order_id': f"PAPER_{int(datetime.datetime.now().timestamp())}", 'symbol': symbol, 'quantity': qty, 'entry_price': entry_price, 'type': direction}
        except Exception as e:
            logging.error(f"Failed to get LTP for paper trade {symbol}: {e}")
            return None

    def _get_trade_details(self, direction):
        """Calculates the correct option symbol and quantity based on risk parameters."""
        ltp_data = self.kite.ltp(str(self.underlying_token))
        ltp = ltp_data[str(self.underlying_token)]['last_price']
        atm_strike = round(ltp / 50) * 50
        otm_strike = atm_strike + 50 if direction == 'BUY' else atm_strike - 50
        option_type = 'CE' if direction == 'BUY' else 'PE'
        today = datetime.date.today()
        expiry_date = today + datetime.timedelta(days=(3 - today.weekday() + 7) % 7)
        
        target = self.nfo_instruments[
            (self.nfo_instruments['name'] == self.flags['underlying_instrument'].split(" ")[0]) &
            (self.nfo_instruments['strike'] == otm_strike) &
            (self.nfo_instruments['instrument_type'] == option_type) &
            (pd.to_datetime(self.nfo_instruments['expiry']).dt.date == expiry_date)
        ]
        if target.empty:
            logging.warning(f"Could not find weekly option for strike {otm_strike}{option_type}.")
            return None, 0
            
        symbol, lot_size = target.iloc[0]['tradingsymbol'], target.iloc[0]['lot_size']
        capital = self.kite.margins()['equity']['available']['live_balance']
        risk_amount = capital * (self.flags['risk_per_trade_percent'] / 100)
        option_price = self.kite.ltp(f"NFO:{symbol}")[f"NFO:{symbol}"]['last_price']
        if option_price == 0:
            return None, 0
        quantity = max(1, int(risk_amount / (option_price * lot_size))) * lot_size
        return symbol, quantity

class PositionManagementAgent:
    """
    Monitors active trades and manages exits with advanced, configurable 
    trailing stop-loss strategies based on option premium and underlying asset indicators.
    """
    def __init__(self, kite: KiteConnect, config: dict, cpr_pivots: dict):
        self.kite, self.config = kite, config
        self.tsl_config = config.get('trailing_stop_loss', {})
        self.active_trade = None

    def manage(self, is_paper_trade=False, underlying_hist_df=None):
        """
        Monitors the active position for various exit triggers:
        1. Hard stop-loss on the option premium.
        2. Trailing stop-loss on the option premium (if enabled).
        3. Indicator-based exit signal on the underlying asset (if enabled).
        """
        if not self.active_trade: return None

        symbol = self.active_trade['symbol']
        current_price = self.kite.ltp(f"NFO:{symbol}")[f"NFO:{symbol}"]['last_price']
        
        # 1. Check the initial "hard" stop-loss
        hard_stop_loss_price = self.active_trade['initial_stop_loss']
        if current_price <= hard_stop_loss_price:
             logging.info(f"HARD stop-loss hit for {symbol} at {current_price:.2f} (SL: {hard_stop_loss_price:.2f}). Exiting.")
             return self.exit_trade(is_paper_trade)

        # 2. Calculate and check the trailing stop-loss on the option premium
        self._update_premium_trailing_stop(current_price)
        trailing_sl_price = self.active_trade['trailing_stop_loss']
        if current_price <= trailing_sl_price:
             logging.info(f"TRAILING stop-loss hit for {symbol} at {current_price:.2f} (Trailing SL: {trailing_sl_price:.2f}). Exiting.")
             return self.exit_trade(is_paper_trade)

        # 3. Check for an indicator-based exit signal on the underlying asset
        if self.tsl_config.get('use_indicator_exit') and underlying_hist_df is not None:
            if self._check_indicator_exit(underlying_hist_df):
                logging.info(f"INDICATOR-BASED exit signal triggered for {symbol} on the underlying asset. Exiting.")
                return self.exit_trade(is_paper_trade)

        return "ACTIVE"
    
    def _update_premium_trailing_stop(self, current_price):
        """Updates the trailing stop-loss level based on the option's peak price."""
        # Update the high-water mark (the highest price seen during the trade)
        self.active_trade['high_water_mark'] = max(self.active_trade.get('high_water_mark', 0), current_price)
        
        trail_type = self.tsl_config.get('type', 'NONE')
        new_sl_price = self.active_trade['trailing_stop_loss'] # Start with the current TSL

        if trail_type == 'PERCENTAGE':
            percentage = self.tsl_config.get('percentage', 15.0)
            new_sl_price = self.active_trade['high_water_mark'] * (1 - percentage / 100)
        
        # The trailing stop can only move up, never down.
        self.active_trade['trailing_stop_loss'] = max(self.active_trade['trailing_stop_loss'], new_sl_price)

    def _check_indicator_exit(self, underlying_hist_df):
        """
        Checks the underlying asset's data for an indicator-based exit signal.
        Returns True if an exit condition is met.
        """
        indicator_type = self.tsl_config.get('indicator_exit_type', 'NONE')
        underlying_price = underlying_hist_df.iloc[-1]['close']

        if indicator_type == 'MA':
            period = self.tsl_config.get('ma_period', 9)
            if 'ema' not in underlying_hist_df.columns:
                underlying_hist_df['ema'] = ta.ema(underlying_hist_df['close'], length=period)
            
            ma_value = underlying_hist_df.iloc[-1]['ema']
            if self.active_trade['type'] == 'BUY' and underlying_price < ma_value: # Long Call
                return True
            if self.active_trade['type'] == 'SELL' and underlying_price > ma_value: # Long Put
                return True

        elif indicator_type == 'PSAR':
            if 'psar' not in underlying_hist_df.columns:
                psar_data = ta.psar(underlying_hist_df['high'], underlying_hist_df['low'])
                underlying_hist_df['psar'] = psar_data['PSARl_0.02_0.2'] # Use long PSAR for bullish exit
                underlying_hist_df['psar_short'] = psar_data['PSARs_0.02_0.2'] # Use short PSAR for bearish exit

            psar_long = underlying_hist_df.iloc[-1]['psar']
            psar_short = underlying_hist_df.iloc[-1]['psar_short']
            
            if self.active_trade['type'] == 'BUY' and not pd.isna(psar_long): # Price crossed below PSAR
                return True
            if self.active_trade['type'] == 'SELL' and not pd.isna(psar_short): # Price crossed above PSAR
                return True
        
        return False

    def start_trade(self, trade_details):
        """Initializes management for a new trade."""
        self.active_trade = trade_details
        initial_sl, _ = self._calculate_initial_sl()
        self.active_trade['initial_stop_loss'] = initial_sl
        self.active_trade['trailing_stop_loss'] = initial_sl # TSL starts at the hard SL
        self.active_trade['high_water_mark'] = self.active_trade['entry_price']
        
        logging.info(f"Managing trade for {self.active_trade['symbol']}. Entry: {self.active_trade['entry_price']:.2f}, Initial Hard SL: {self.active_trade['initial_stop_loss']:.2f}")
    def exit_trade(self, is_paper_trade=False):
        """Exits the current active trade at market price and logs the result."""
        trade = self.active_trade
        exit_price = self.kite.ltp(f"NFO:{trade['symbol']}")[f"NFO:{trade['symbol']}"]['last_price']
        
        if not is_paper_trade:
            try:
                self.kite.place_order(tradingsymbol=trade['symbol'], exchange=self.kite.EXCHANGE_NFO, transaction_type=self.kite.TRANSACTION_TYPE_SELL, quantity=trade['quantity'], product=self.config['trading_flags']['product_type'], order_type=self.kite.ORDER_TYPE_MARKET, variety=self.config['trading_flags']['order_variety'])
            except Exception as e:
                logging.error(f"Failed to place live exit order for {trade['symbol']}: {e}")
                return None
        else:
            logging.info(f"[Paper Trade] Exiting {trade['symbol']} at {exit_price:.2f}")
        
        pnl = (exit_price - trade['entry_price']) * trade['quantity']
        if trade['type'] == 'SELL':
            pnl = -pnl
        
        completed = {
            'Timestamp': datetime.datetime.now(), 'Symbol': trade['symbol'], 
            'TradeType': trade['type'], 'EntryPrice': trade['entry_price'], 
            'ExitPrice': exit_price, 'Quantity': trade['quantity'], 
            'ProfitLoss': pnl, 'Status': 'CLOSED',
            'Strategy': trade.get('Strategy', 'N/A')
        }
        self.active_trade = None
        return completed

    def _calculate_initial_sl(self):
        """
        Calculates a hybrid stop-loss based on the greater of a percentage or a fixed point value.
        Returns the stop-loss price and the risk amount per share.
        """
        entry_price = self.active_trade['entry_price']
        sl_percent = self.config['trading_flags'].get('stop_loss_percent', 10.0)
        min_sl_points = self.config['trading_flags'].get('min_stop_loss_points', 2.0)

        # Calculate risk amount based on percentage
        percent_risk_amount = entry_price * (sl_percent / 100)
        
        # Determine the actual risk amount to use (the greater of the two)
        risk_per_share = max(percent_risk_amount, min_sl_points)
        
        # Calculate the final stop-loss price
        stop_loss_price = entry_price - risk_per_share
        
        return stop_loss_price, risk_per_share

    def _calculate_target_price(self, risk_per_share):
        """
        Calculates the take-profit target price based on the risk amount and a risk-reward ratio.
        """
        entry_price = self.active_trade['entry_price']
        rr_ratio = self.config['trading_flags'].get('risk_reward_ratio', 2.0) # Default to 1:2 R:R
        
        reward_per_share = risk_per_share * rr_ratio
        target_price = entry_price + reward_per_share
        
        return target_price
