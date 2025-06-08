import pandas as pd
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging

LOG_FILE = 'output/trade_log.xlsx'
os.makedirs('output', exist_ok=True)

def initialize_trade_log():
    """Creates the trade log Excel file with headers if it doesn't exist."""
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame(columns=[
            'Timestamp', 'Symbol', 'TradeType', 'EntryPrice',
            'ExitPrice', 'Quantity', 'ProfitLoss', 'Status'
        ])
        df.to_excel(LOG_FILE, index=False)
        logging.info(f"Trade log created at {LOG_FILE}")

def log_trade(trade_details):
    """Appends a single trade record to the Excel log file."""
    try:
        df = pd.read_excel(LOG_FILE)
        # Use concat instead of append
        new_trade_df = pd.DataFrame([trade_details])
        df = pd.concat([df, new_trade_df], ignore_index=True)
        df.to_excel(LOG_FILE, index=False)
        logging.info(f"Successfully logged trade for {trade_details['Symbol']}")
    except Exception as e:
        logging.error(f"Failed to log trade to Excel: {e}")

def send_email_report(config, date_str):
    """Reads today's trades from the log and sends an email report."""
    email_conf = config['email_settings']
    if not email_conf['send_daily_report']:
        logging.info("Email reporting is disabled in config.")
        return

    try:
        df = pd.read_excel(LOG_FILE)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        today_trades = df[df['Timestamp'].dt.date == pd.to_datetime(date_str).date()]

        if today_trades.empty:
            body = "No trades were executed today."
            total_pnl = 0
        else:
            total_pnl = today_trades['ProfitLoss'].sum()
            body = today_trades.to_html(index=False)
        
        # Create email
        msg = MIMEMultipart()
        msg['From'] = email_conf['sender_email']
        msg['To'] = email_conf['receiver_email']
        msg['Subject'] = f"Trading Report for {date_str} | P/L: {total_pnl:,.2f}"
        
        html_content = f"""
        <html><body>
        <h2>Daily Trading Summary</h2>
        <p>Here is the summary of trades executed today.</p>
        {body}
        <hr>
        <p>Total Profit/Loss for the day: <strong>{total_pnl:,.2f}</strong></p>
        <p><em>This is an automated report.</em></p>
        </body></html>
        """
        msg.attach(MIMEText(html_content, 'html'))
        
        # Send email
        with smtplib.SMTP(email_conf['smtp_server'], email_conf['smtp_port']) as server:
            server.starttls()
            server.login(email_conf['sender_email'], email_conf['sender_password'])
            server.send_message(msg)
            logging.info(f"Successfully sent email report to {email_conf['receiver_email']}.")

    except Exception as e:
        logging.error(f"Failed to send email report: {e}")

