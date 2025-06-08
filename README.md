Zerodha Intraday Options Trading Bot (Advanced Version)
This project provides an advanced Python framework for an automated intraday options trading bot using Zerodha's Kite Connect API. It uses a modular, agent-based architecture to handle signal generation, order execution, position management, and reporting.

DISCLAIMER: Trading in the stock market involves substantial risk. This is a framework for educational and developmental purposes. You are solely responsible for any financial losses incurred from using or adapting this code. NEVER run a trading bot with real money without extensive backtesting, paper trading, and a complete understanding of the code and its risks.

Project Structure

/zerodha-trading-bot
|-- output/                  # Folder for trade logs
|   `-- trade_log.xlsx`      # Automatically generated trade log
|-- trading_bot.py           # The main application orchestrator
|-- agents.py                # Contains all specialized agents (Signal, Order, Position)
|-- indicators.py            # All technical indicator calculation functions
|-- reporting.py             # Handles Excel logging and email reports
|-- backtester.py            # Script to backtest the strategy on historical data
|-- config.yaml              # Configuration file for API keys and strategy parameters
|-- requirements.txt         # List of required Python libraries

Setup Instructions

Step 1: Install Dependencies
First, install all the necessary Python libraries. A virtual environment is highly recommended.
Special Instructions for TA-Lib on macOS (Apple Silicon M1/M2/M3 & Intel):
The TA-Lib library requires a C-language dependency to be installed first. The easiest way to do this is with Homebrew.
Install the TA-Lib C library using Homebrew. Open your terminal and run:

brew install ta-lib

Install Python packages. Once the command above completes successfully, you can install all the required Python packages from the requirements.txt file.

pip install -r requirements.txt

For Windows & Linux users:
Simply run the following command:

pip install -r requirements.txt


Step 2: Get Your Zerodha API Credentials
Go to the Zerodha Developers Console to create an app and get your api_key and api_secret.
The access_token is generated daily after a successful login.

Step 3: Configure the Bot
Create your own config.yaml file and fill in all your details:
Your Zerodha api_key and api_secret etc. (Else contact me for a config.yaml template with placeholders)

Your trading parameters, including the chart_timeframe and EMA flags.
Crucially, fill out the email_settings section if you want to receive daily reports. Use an "App Password" for Gmail if you have 2-Factor Authentication enabled.

Step 4: The First Run (Authentication)
The first time you run the bot, you must authenticate to get an access_token.
Run the main script: python trading_bot.py
The script will print a login URL. Copy it into your browser.
Log in with your Zerodha credentials. After login, the browser will redirect, and the new URL will contain a request_token.
Copy only the request_token value.
Paste it into the console where the script is prompting you.
An access_token will be generated and saved to config.yaml for you.

You will need to do this each trading morning.

Step 5: Running the Bot
Once authenticated, the bot will start. Before the market opens, it will ask for the Day's Sentiment:

Enter the day's sentiment (Bullish/Bearish): Bullish

The bot will then run, analyze the market based on your strategy, manage trades, and log the results. At the end of the day, it will automatically email you the trade report.

Backtesting

To test your strategy's signal logic, run the backtester.py script:

python backtester.py

The backtester has been updated to include the new EMA crossover conditions. Remember, this tool is for strategy logic validation, not precise P/L prediction, due to the complexities of options pricing.

