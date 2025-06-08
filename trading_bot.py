import logging
import yaml
import time
import datetime
import pandas as pd
from kiteconnect import KiteConnect
from agents import SignalAgent, OrderExecutionAgent, PositionManagementAgent
from reporting import initialize_trade_log, log_trade, send_email_report
from indicators import calculate_cpr

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config():
    with open('config.yaml', 'r') as file: return yaml.safe_load(file)
def save_config(config):
    with open('config.yaml', 'w') as file: yaml.dump(config, file)

class TradingBotOrchestrator:
    def __init__(self, config):
        self.config = config
        self.kite = KiteConnect(api_key=config['zerodha']['api_key'])
        self.day_sentiment = ""
        self.trades_today_count = 0
        self.cpr_pivots = {}
        # Agents
        self.signal_agent = None
        self.order_agent = None
        self.position_agent = None

    def authenticate(self):
        """Handles the Zerodha authentication flow."""
        access_token = self.config['zerodha'].get('access_token')
        if access_token:
            try:
                self.kite.set_access_token(access_token)
                profile = self.kite.profile()
                logging.info(f"Authenticated as {profile.get('user_name', 'user')}.")
                return True
            except Exception:
                logging.warning("Access token expired. Starting new login.")
        
        logging.info(f"Login URL: {self.kite.login_url()}")
        request_token = input("Enter request_token: ")
        try:
            data = self.kite.generate_session(request_token, api_secret=self.config['zerodha']['api_secret'])
            self.kite.set_access_token(data['access_token'])
            self.config['zerodha']['access_token'] = data['access_token']
            save_config(self.config)
            logging.info("Authentication successful.")
            return True
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return False

    def setup(self):
        """Initial setup before market opens."""
        self.day_sentiment = input("Enter day's sentiment (Bullish/Bearish): ").strip().capitalize()
        if self.day_sentiment not in ["Bullish", "Bearish"]: return False
        
        initialize_trade_log()
        
        # Calculate CPR
        token = [i['instrument_token'] for i in self.kite.instruments('NSE') if i['tradingsymbol'] == self.config['trading_flags']['underlying_instrument']][0]
        to_date = datetime.date.today(); from_date = to_date - datetime.timedelta(days=7)
        hist = self.kite.historical_data(token, from_date, to_date, "day")
        self.cpr_pivots = calculate_cpr(pd.DataFrame(hist).iloc[-2:-1])
        if not self.cpr_pivots:
            logging.error("Could not calculate CPR. Exiting.")
            return False
        logging.info(f"CPR Calculated: TC={self.cpr_pivots['tc']:.2f}, P={self.cpr_pivots['pivot']:.2f}, BC={self.cpr_pivots['bc']:.2f}")

        # Initialize Agents
        self.signal_agent = SignalAgent(self.kite, self.config)
        self.order_agent = OrderExecutionAgent(self.kite, self.config)
        self.position_agent = PositionManagementAgent(self.kite, self.config, self.cpr_pivots)
        return True

    def run(self):
        """The main trading loop, orchestrating agents."""
        if not self.authenticate() or not self.setup():
            return
            
        logging.info("Bot is running...")
        
        while datetime.datetime.now().time() < datetime.time(15, 30):
            try:
                # --- Position Management ---
                if self.position_agent.active_trade:
                    status = self.position_agent.manage()
                    if status and status != 'ACTIVE': # A trade was closed
                        log_trade(status) # status is the completed trade dict
                    time.sleep(10) # Check active position more frequently
                    continue

                # --- Signal Generation & New Trades ---
                if self.trades_today_count >= self.config['trading_flags']['max_trades_per_day']:
                    logging.info("Max trades reached. Only managing open positions.")
                    time.sleep(300); continue

                to_d = datetime.datetime.now(); from_d = to_d - datetime.timedelta(days=5)
                hist_df = pd.DataFrame(self.kite.historical_data(self.signal_agent.underlying_token, from_d, to_d, self.config['trading_flags']['chart_timeframe']))
                if hist_df.empty: time.sleep(60); continue

                signal = self.signal_agent.check_for_signals(hist_df, self.cpr_pivots, self.day_sentiment)

                if signal != 'HOLD':
                    logging.info(f"Signal Agent returned: {signal}. Handing over to Order Agent.")
                    trade_details = self.order_agent.place_trade(signal)
                    if trade_details:
                        self.trades_today_count += 1
                        self.position_agent.start_trade(trade_details)
                
                # Wait for the next candle
                time.sleep(int(self.config['trading_flags']['chart_timeframe'].replace('minute','')) * 60 - 10)

            except Exception as e:
                logging.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(60)
        
        logging.info("Market closed. Sending daily report.")
        send_email_report(self.config, str(datetime.date.today()))

if __name__ == "__main__":
    bot = TradingBotOrchestrator(load_config())
    bot.run()
