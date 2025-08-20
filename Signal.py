import os
import datetime
import json

import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import logging
from logging.handlers import RotatingFileHandler

import config

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Logging setup: file + console with rotation
os.makedirs(config.LOG_DIR, exist_ok=True)
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)

logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(log_path, maxBytes=config.LOG_MAX_BYTES, backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8")
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# Secrets from environment vars
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)
tickers = config.tickers

# Fetch historical data with cache
def fetch_cached_history(symbol, period="2y", interval="1d"):
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df, force_full = None, False

    if os.path.exists(file_path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(file_path))).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            logger.info("%s cache too old (%d days) → full refresh", symbol, age_days)
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=False)
                df.index = pd.to_datetime(df.index, format="%m/%d/%Y", errors='coerce')
                if df.index.isnull().any():
                    logger.warning("Date parsing failed in cached data for %s, forcing full refresh", symbol)
                    force_full = True
            except Exception:
                df = None

    if df is None or df.empty or force_full:
        try:
            logger.info("⬇️ Downloading full history: %s", symbol)
            df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        except Exception as e:
            logger.error("Download error %s: %s", symbol, e)
            return pd.DataFrame()
    else:
        last_date = df.index[-1]
        if not isinstance(last_date, pd.Timestamp):
            last_date = pd.to_datetime(last_date)
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        logger.info("🔄 Updating %s from %s", symbol, start)
        try:
            new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning("Update error %s: %s", symbol, e)

    try:
        df.to_csv(file_path)
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", symbol, e)

    return df

# Calculate indicators
def calculate_indicators(df):
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    return df

def generate_rsi_signal(df):
    last = df.iloc[-1]
    rsi, price = last["rsi"], last["Close"]
    if isinstance(rsi, (pd.Series, pd.DataFrame)):
        rsi = float(rsi.squeeze())
    if isinstance(price, (pd.Series, pd.DataFrame)):
        price = float(price.squeeze())
    signal, reason = None, ""
    if pd.notna(rsi):
        if rsi < config.RSI_OVERSOLD:
            signal, reason = "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
        elif rsi > config.RSI_OVERBOUGHT:
            signal, reason = "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return signal, reason, rsi, price

# Fetch fundamentals
def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning("Fundamentals error %s: %s", symbol, e)
        return None, None

def fetch_option_iv_history(symbol, lookback_days=52):
    iv_data = []
    try:
        ticker = yf.Ticker(symbol)
        for date in ticker.options[-lookback_days:]:
            chain = ticker.option_chain(date)
            if chain.calls.empty:
                continue
            under = ticker.history(period="1d")["Close"].iloc[-1]
            chain.calls["distance"] = abs(chain.calls["strike"] - under)
            atm = chain.calls.loc[chain.calls["distance"].idxmin()]
            iv_data.append({"date": date, "IV": atm["impliedVolatility"]})
    except Exception as e:
        logger.warning("IV history error %s: %s", symbol, e)
    return pd.DataFrame(iv_data)

def calc_iv_rank_percentile(iv_series):
    s = pd.Series(iv_series).dropna()
    if len(s) < 5:
        return None, None
    cur, hi, lo = s.iloc[-1], s.max(), s.min()
    iv_rank = 100 * (cur - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (s < cur).mean()
    return (round(iv_rank, 2) if iv_rank else None, round(iv_pct, 2) if iv_pct else None)

# Fetch calls for next 7 weeks
def fetch_calls_for_7_weeks(symbol):
    from dateutil.parser import parse
    calls_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        valid_dates = [d for d in ticker.options if (parse(d) - today).days <= 49]
        for exp_date in valid_dates:
            chain = ticker.option_chain(exp_date)
            if chain.calls.empty:
                continue
            for _, call in chain.calls.iterrows():
                strike = call["strike"]
                last_price = call.get("lastPrice", None)
                bid = call.get("bid", None)
                ask = call.get("ask", None)
                if last_price is not None and last_price > 0:
                    premium = last_price
                elif bid is not None and ask is not None:
                    premium = (bid + ask) / 2
                else:
                    premium = 0.0
                calls_data.append({
                    "expiration": exp_date,
                    "strike": strike,
                    "premium": premium
                })
    except Exception as e:
        logger.warning(f"Failed to fetch 7 weeks calls for {symbol}: {e}")
    return calls_data

# Calculate custom metric for option calls
def calculate_custom_metric(calls_data, stock_price):
    if stock_price is None or stock_price == 0:
        return calls_data
    for call in calls_data:
        strike = call.get("strike", None)
        premium = call.get("premium", 0.0)
        try:
            metric = ((stock_price - strike) + premium) / stock_price
            call["custom_metric"] = metric
        except Exception as e:
            logger.warning(f"Error computing custom metric for call: {call}, error: {e}")
            call["custom_metric"] = None
    return calls_data

# Send email
def send_email(subject, body):
    if not EMAIL_SENDER or not EMAIL_RECEIVER or not EMAIL_PASSWORD:
        logger.error("Email environment variables are not properly set.")
        return
    try:
        msg = MIMEMultipart()
        msg["From"], msg["To"], msg["Subject"] = EMAIL_SENDER, EMAIL_RECEIVER, subject
        msg.attach(MIMEText(body, "plain"))
        s = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        s.starttls()
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.send_message(msg)
        s.quit()
        logger.info("✉️ Email sent.")
    except Exception as e:
        logger.error("Email failed: %s", e)

# Log alerts to CSV
def log_alert(alert):
    csv_path = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode="a", header=header, index=False)

# Main job execution
def job():
    buy_alerts = []
    sell_alerts = []
    buy_tickers = []
    total, skipped = 0, 0

    for symbol in tickers:
        total += 1
        hist = fetch_cached_history(symbol)
        if hist.empty:
            skipped += 1
            continue

        hist = calculate_indicators(hist)
        sig, reason, rsi, price = generate_rsi_signal(hist)

        try:
            rt_price = finnhub_client.quote(symbol).get("c", price)
        except Exception:
            rt_price = price

        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"])

        if sig:
            line_parts = [
                f"{symbol}: {sig} at ${rt_price:.2f}",
                reason,
                f"PE={pe if pe else 'N/A'}",
                f"MarketCap={mcap if mcap else 'N/A'}"
            ]
            if iv_rank is not None:
                line_parts.append(f"IV Rank={iv_rank}")
                line_parts.append(f"IV Percentile={iv_pct}")

            line = ", ".join(line_parts)

            alert_entry = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": symbol,
                "signal": sig,
                "price": rt_price,
                "rsi": round(rsi, 2) if rsi else None,
                "pe_ratio": pe,
                "market_cap": mcap,
                "iv_rank": iv_rank,
                "iv_percentile": iv_pct,
            }
            log_alert(alert_entry)

            if sig == "BUY":
                buy_alerts.append(line)
                buy_tickers.append(symbol)
                logger.info(f"Added buy ticker: {symbol}")
            else:
                sell_alerts.append(line)

    logger.info(f"Total buy tickers collected: {len(buy_tickers)}")
    print("DEBUG buy_tickers:", buy_tickers)

    if buy_tickers:
        buy_file_path = "buy_signals.txt"
        try:
            with open(buy_file_path, "w", encoding="utf-8") as file:
                for ticker in buy_tickers:
                    file.write(ticker + "\n")
            logger.info(f"Saved buy tickers to {buy_file_path}")
        except Exception as e:
            logger.error(f"Failed to save buy_signals.txt: {e}")

        try:
            with open(buy_file_path, "r", encoding="utf-8") as check:
                content = check.read()
            logger.info("buy_signals.txt contents after write:\n" + content)
            print("=== BUY SIGNALS FILE CONTENTS ===")
            print(content)
        except Exception as e:
            logger.error(f"Failed to read back buy_signals.txt: {e}")
    else:
        logger.info("No buy tickers found to save.")
        print("No buy tickers found to save.")

    calls_dir = "calls_data"
    os.makedirs(calls_dir, exist_ok=True)

    for buy_symbol in buy_tickers:
        calls_7weeks = fetch_calls_for_7_weeks(buy_symbol)
        try:
            stock_price = finnhub_client.quote(buy_symbol).get("c", None)
        except Exception:
            stock_price = None

        if stock_price is None or stock_price == 0:
            hist = fetch_cached_history(buy_symbol)
            if not hist.empty:
                stock_price = hist["Close"].iloc[-1]
                logger.info(f"Using fallback historical close price for {buy_symbol}: {stock_price}")
            else:
                logger.warning(f"No spot or fallback price for {buy_symbol}")

        calls_7weeks = calculate_custom_metric(calls_7weeks, stock_price)

        for call in calls_7weeks:
            logger.info(f"{buy_symbol} strike={call['strike']}, premium={call['premium']}, custom_metric={call.get('custom_metric')}")

        if calls_7weeks:
            calls_file = os.path.join(calls_dir, f"{buy_symbol}_calls_7weeks.json")
            try:
                with open(calls_file, "w", encoding="utf-8") as f:
                    json.dump(calls_7weeks, f, indent=2)
                logger.info(f"Saved 7-week call option data with metrics to {calls_file}")
            except Exception as e:
                logger.error(f"Failed to save call data for {buy_symbol}: {e}")

    if not buy_alerts and not sell_alerts:
        logger.info("No alerts. Processed=%d, Skipped=%d, Alerts=0", total, skipped)
        print("No alerts found.")
        return

    email_body = "RSI Alerts Summary:\n\n"
    if buy_alerts:
        email_body += f"🔹 Buy Signals (RSI < {config.RSI_OVERSOLD}):\n"
        email_body += "\n".join(f" - {alert}" for alert in buy_alerts) + "\n\n"
    if sell_alerts:
        email_body += f"🔸 Sell Signals (RSI > {config.RSI_OVERBOUGHT}):\n"
        email_body += "\n".join(f" - {alert}" for alert in sell_alerts) + "\n"

    logger.info(
        "SUMMARY: Processed=%d, Skipped=%d, Alerts=%d",
        total, skipped, len(buy_alerts) + len(sell_alerts),
    )
    print(email_body)
    send_email("StockHome Trading Alerts", email_body)

if __name__ == "__main__":
    job()
