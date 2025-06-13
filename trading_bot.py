import logging
import yaml
import time
import datetime
import calendar
import pandas as pd
import asyncio # <-- IMPORT ASYNCIO
from kiteconnect import KiteConnect
from agents import OrderExecutionAgent, PositionManagementAgent
from sentiment_agent import SentimentAgent
from langgraph_agent import LangGraphAgent
from strategy_factory import get_strategy
from backtester import run_backtest
from reporting import send_daily_report, send_monthly_report, initialize_trade_log, log_trade
from indicators import calculate_cpr
from market_context import MarketConditionIdentifier
import multiprocessing

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config():
    """Loads the configuration from config.yaml."""
    with open('config.yaml', 'r') as file:
        return yaml.safe_load(file)

def save_config(config):
    """Saves the configuration to config.yaml."""
    with open('config.yaml', 'w') as file:
        yaml.dump(config, file)

class TradingBotOrchestrator:
    """
    The main orchestrator for the AI trading bot. It manages the setup,
    strategy selection, and trading loop by directing the various agents.
    """
    def __init__(self, config):
        self.config = config
        self.kite = KiteConnect(api_key=config['zerodha']['api_key'], timeout=120)
        self.active_strategy = None
        self.active_strategy_name = "None" # To hold the name of the winning strategy
        self.langgraph_agent = LangGraphAgent(config)
        self.sentiment_agent = SentimentAgent(config)
        self.market_condition_identifier = MarketConditionIdentifier(self.kite, config)
        self.order_agent = OrderExecutionAgent(self.kite, config)
        self.position_agent = None
        self.day_sentiment = ""
        self.trades_today_count = 0
        self.cpr_pivots = {}
        self.no_trade_reason = None
        self.starting_capital = 0 # To track daily P/L %

    def authenticate(self):
        """Handles the Zerodha authentication flow."""
        access_token = self.config['zerodha'].get('access_token')
        if access_token:
            try:
                self.kite.set_access_token(access_token)
                profile = self.kite.profile()
                logging.info(f"Authenticated as {profile.get('user_name', 'user')}.")
                # Capture starting capital right after successful authentication
                self.starting_capital = self.kite.margins()['equity']['available']['live_balance']
                logging.info(f"Today's starting capital: {self.starting_capital:,.2f}")
                return True
            except Exception:
                logging.warning("Access token expired. Re-authenticating.")
        
        logging.info(f"Login URL: {self.kite.login_url()}")
        request_token = input("Enter request_token: ")
        try:
            data = self.kite.generate_session(request_token, api_secret=self.config['zerodha']['api_secret'])
            self.kite.set_access_token(data['access_token'])
            self.config['zerodha']['access_token'] = data['access_token']
            save_config(self.config)
            logging.info("Authentication successful.")
            # Capture starting capital after new authentication
            self.starting_capital = self.kite.margins()['equity']['available']['live_balance']
            logging.info(f"Today's starting capital: {self.starting_capital:,.2f}")
            return True
        except Exception as e:
            logging.error(f"Auth failed: {e}")
            return False

    async def setup(self): # <-- MADE ASYNC
        """Runs the entire pre-market setup and strategy selection process."""
        logging.info("--- Starting Bot Setup Sequence ---")
        today = datetime.date.today()
        
        todays_conditions = self.market_condition_identifier.get_conditions_for_date(today)
        if 'UNKNOWN' in todays_conditions:
            self.no_trade_reason = "Could not determine today's market conditions."
            return False
        
        self.day_sentiment = self.sentiment_agent.get_market_sentiment()
        if self.day_sentiment not in ["Bullish", "Bearish"]:
            self.no_trade_reason = f"Market sentiment is neutral or invalid ('{self.day_sentiment}')."
            return False
        logging.info(f"Day's Sentiment set to: {self.day_sentiment}")
        
        # --- FIX APPLIED HERE: Must 'await' the async function ---
        ai_strategy_name = await self.langgraph_agent.get_recommended_strategy(todays_conditions)
        # --- END OF FIX ---

        if self.config['trading_flags']['run_startup_backtest']:
            to_date = today
            from_date = to_date - datetime.timedelta(days=365 * self.config['trading_flags']['backtest_years'])
            default_strategy = "Gemini_Default"
            tasks = [(self.kite, self.config, name, from_date, to_date, (todays_conditions if name == ai_strategy_name else None)) for name in list(set([default_strategy, ai_strategy_name]))]
            results = {}
            if self.config['trading_flags']['enable_parallel_processing']:
                with multiprocessing.Pool(processes=len(tasks)) as pool:
                    win_rates = pool.starmap(run_backtest, tasks)
                    for i, task in enumerate(tasks): results[task[2]] = win_rates[i]
            else:
                for task in tasks: results[task[2]] = run_backtest(*task)
            
            if not results: 
                self.no_trade_reason = "Backtesting yielded no results."
                return False
            self.active_strategy_name = max(results, key=results.get)
            best_win_rate = results[self.active_strategy_name]
            
            logging.info(f"Selected Strategy: '{self.active_strategy_name}' with win rate {best_win_rate:.2f}%")

            if best_win_rate < self.config['trading_flags']['win_rate_threshold']:
                self.no_trade_reason = f"Winning strategy '{self.active_strategy_name}' win rate ({best_win_rate:.2f}%) is below threshold."
                return False
        else:
            logging.warning("Startup backtest validation is DISABLED.")
            self.active_strategy_name = ai_strategy_name
            logging.info(f"Directly selecting AI Recommended Strategy: '{self.active_strategy_name}'")

        self.active_strategy = get_strategy(self.active_strategy_name, self.kite, self.config)
        initialize_trade_log()
        token = [i['instrument_token'] for i in self.kite.instruments('NSE') if i['tradingsymbol'] == self.config['trading_flags']['underlying_instrument']][0]
        hist = self.kite.historical_data(token, today - datetime.timedelta(days=7), today, "day")
        self.cpr_pivots = calculate_cpr(pd.DataFrame(hist).iloc[-2:-1])
        self.position_agent = PositionManagementAgent(self.kite, self.config, self.cpr_pivots)
        return True

    async def run(self): # <-- MADE ASYNC
        """The main trading loop, orchestrating all agent actions."""
        if not self.authenticate() or not await self.setup(): # <-- AWAIT SETUP
            logging.warning("Setup failed or trading conditions not met. Bot will exit after sending EOD report.")
            send_daily_report(self.config, str(datetime.date.today()), no_trades_reason=self.no_trade_reason)
            return
            
        is_paper_trading = self.config['trading_flags']['paper_trading']
        logging.info(f"Bot is running in {'PAPER TRADING' if is_paper_trading else 'LIVE TRADING'} mode with strategy '{self.active_strategy_name}'.")
        
        while datetime.datetime.now().time() < datetime.time(15, 30):
            try:
                if datetime.datetime.now().time() < datetime.time(9, 45):
                    await asyncio.sleep(60); continue # <-- USE ASYNCIO.SLEEP

                if not self.position_agent.active_trade and self.trades_today_count < self.config['trading_flags']['max_trades_per_day']:
                    token = [i['instrument_token'] for i in self.kite.instruments('NSE') if i['tradingsymbol'] == self.config['trading_flags']['underlying_instrument']][0]
                    hist_df = pd.DataFrame(self.kite.historical_data(token, datetime.datetime.now() - datetime.timedelta(days=5), datetime.datetime.now(), self.config['trading_flags']['chart_timeframe']))
                    
                    if not hist_df.empty:
                        signal = self.active_strategy.generate_signals(hist_df, self.day_sentiment, cpr_pivots=self.cpr_pivots)
                        if signal != 'HOLD':
                            trade_details = self.order_agent.get_paper_trade_details(signal) if is_paper_trading else self.order_agent.place_trade(signal)
                            if trade_details:
                                trade_details['Strategy'] = self.active_strategy_name
                                self.position_agent.start_trade(trade_details); self.trades_today_count += 1
                elif self.position_agent.active_trade:
                    status = self.position_agent.manage(is_paper_trading)
                    if status and status != 'ACTIVE': log_trade(status)
                
                await asyncio.sleep(30) # <-- USE ASYNCIO.SLEEP
            except Exception as e:
                logging.error(f"Error in main loop: {e}", exc_info=True); await asyncio.sleep(60)
        
        today = datetime.date.today()
        logging.info("Market closed. Sending daily report.")
        send_daily_report(self.config, str(today))
        
        _, last_day_of_month = calendar.monthrange(today.year, today.month)
        if today.day == last_day_of_month:
            logging.info("Last day of the month. Sending monthly summary report.")
            send_monthly_report(self.config, str(today))
        
if __name__ == "__main__":
    multiprocessing.freeze_support()
    bot = TradingBotOrchestrator(load_config())
    asyncio.run(bot.run()) # <-- USE ASYNCIO.RUN TO START THE BOT