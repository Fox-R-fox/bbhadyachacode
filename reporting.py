import logging
import os
import smtplib
import datetime
import calendar
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

LOG_FILE = 'output/trade_log.xlsx'
os.makedirs('output', exist_ok=True)

def initialize_trade_log():
    """Creates the trade log Excel file with headers if it doesn't exist."""
    if not os.path.exists(LOG_FILE):
        pd.DataFrame(columns=['Timestamp', 'Symbol', 'TradeType', 'EntryPrice', 'ExitPrice', 'Quantity', 'ProfitLoss', 'Status']).to_excel(LOG_FILE, index=False)
        logging.info(f"Trade log created at {LOG_FILE}")

def log_trade(trade_details):
    """Appends a single trade record to the Excel log file."""
    try:
        df = pd.read_excel(LOG_FILE)
        new_trade_df = pd.DataFrame([trade_details])
        df = pd.concat([df, new_trade_df], ignore_index=True)
        df.to_excel(LOG_FILE, index=False)
        logging.info(f"Successfully logged trade for {trade_details['Symbol']}")
    except Exception as e:
        logging.error(f"Failed to log trade to Excel: {e}")

def send_daily_report(config, date_str, no_trades_reason=None):
    """
    Reads the trade log and sends a daily report with daily and month-to-date stats.
    """
    email_conf = config.get('email_settings', {})
    if not email_conf.get('send_daily_report', False):
        logging.info("Email reporting is disabled."); return

    try:
        df = pd.read_excel(LOG_FILE)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        today = pd.to_datetime(date_str).date()

        # --- Calculate Month-to-date stats ---
        monthly_trades = df[(df['Timestamp'].dt.year == today.year) & (df['Timestamp'].dt.month == today.month)]
        monthly_wins = int((monthly_trades['ProfitLoss'] > 0).sum())
        monthly_losses = int((monthly_trades['ProfitLoss'] <= 0).sum())

        # --- Create email body ---
        today_trades = df[df['Timestamp'].dt.date == today]
        daily_wins = int((today_trades['ProfitLoss'] > 0).sum())
        daily_losses = int((today_trades['ProfitLoss'] <= 0).sum())
        total_pnl = today_trades['ProfitLoss'].sum()

        subject = ""
        body_content = ""

        summary_html = f"""
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 400px;">
            <tr style="background-color: #f2f2f2;">
                <th colspan="2">Performance Summary</th>
            </tr>
            <tr>
                <td>Today's Winning Trades</td>
                <td>{daily_wins}</td>
            </tr>
            <tr>
                <td>Today's Losing Trades</td>
                <td>{daily_losses}</td>
            </tr>
            <tr style="background-color: #f2f2f2;">
                <td><strong>Month-to-Date Winning Trades</strong></td>
                <td><strong>{monthly_wins}</strong></td>
            </tr>
            <tr>
                <td><strong>Month-to-Date Losing Trades</strong></td>
                <td><strong>{monthly_losses}</strong></td>
            </tr>
        </table>
        <hr>
        """

        if no_trades_reason:
            subject = f"Trading Report for {date_str}: No Trades Executed"
            body_content = f"<h3>Reason for No Trades:</h3><p><strong>{no_trades_reason}</strong></p>"
        elif today_trades.empty:
            subject = f"Trading Report for {date_str}: No Trades Executed"
            body_content = "<h3>Trades Today:</h3><p>No trades were executed today.</p>"
        else:
            subject = f"Trading Report for {date_str} | Daily P/L: {total_pnl:,.2f}"
            body_content = f"<h3>Today's Trades:</h3>" + today_trades.to_html(index=False)
        
        full_html_content = f"<html><body>{summary_html}{body_content}</body></html>"

        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = email_conf['sender_email'], email_conf['receiver_email'], subject
        msg.attach(MIMEText(full_html_content, 'html'))
        
        with smtplib.SMTP(email_conf['smtp_server'], email_conf['smtp_port']) as server:
            server.starttls(); server.login(email_conf['sender_email'], email_conf['sender_password'])
            server.send_message(msg)
        logging.info("Successfully sent daily email report.")

    except Exception as e:
        logging.error(f"Failed to send daily email report: {e}", exc_info=True)


def send_monthly_report(config, date_str):
    """
    Generates and sends a summary report for the entire month's performance.
    """
    email_conf = config.get('email_settings', {})
    if not email_conf.get('send_daily_report', False): return

    logging.info("Generating monthly report...")
    today = pd.to_datetime(date_str).date()
    report_month_str = today.strftime("%B %Y")

    try:
        df = pd.read_excel(LOG_FILE)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        monthly_trades = df[(df['Timestamp'].dt.year == today.year) & (df['Timestamp'].dt.month == today.month)]

        if monthly_trades.empty:
            body = f"<p>No trades were executed during the month of {report_month_str}.</p>"
        else:
            total_pnl = monthly_trades['ProfitLoss'].sum()
            monthly_wins = int((monthly_trades['ProfitLoss'] > 0).sum())
            monthly_losses = int((monthly_trades['ProfitLoss'] <= 0).sum())
            win_rate = (monthly_wins / (monthly_wins + monthly_losses) * 100) if (monthly_wins + monthly_losses) > 0 else 0

            body = f"""
            <h3>Monthly Performance Summary for {report_month_str}</h3>
            <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 400px;">
                <tr style="background-color: #f2f2f2;"><td><strong>Metric</strong></td><td><strong>Value</strong></td></tr>
                <tr><td>Total P/L</td><td>{total_pnl:,.2f}</td></tr>
                <tr><td>Total Winning Trades</td><td>{monthly_wins}</td></tr>
                <tr><td>Total Losing Trades</td><td>{monthly_losses}</td></tr>
                <tr><td><strong>Monthly Win Rate</strong></td><td><strong>{win_rate:.2f}%</strong></td></tr>
            </table>
            <hr>
            <h3>All Trades for the Month:</h3>
            {monthly_trades.to_html(index=False)}
            """
        
        subject = f"Monthly Trading Summary: {report_month_str}"
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = email_conf['sender_email'], email_conf['receiver_email'], subject
        msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html'))
        
        with smtplib.SMTP(email_conf['smtp_server'], email_conf['smtp_port']) as server:
            server.starttls(); server.login(email_conf['sender_email'], email_conf['sender_password'])
            server.send_message(msg)
        logging.info(f"Successfully sent monthly report for {report_month_str}.")

    except Exception as e:
        logging.error(f"Failed to send monthly report: {e}", exc_info=True)
