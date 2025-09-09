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
import argparse
import config
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
import time

# === Logging setup: file + console with rotation ===
os.makedirs(config.LOG_DIR, exist_ok=True)
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(
    log_path, maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8"
)
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# === Secrets from environment vars ===
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

def load_previous_buys(email_type):
    file_path = f"sent_buys_{email_type}.json"
    if os.path.exists(file_path):
        try:
            with open(file_path) as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Could not load previous buys for {email_type}: {e}")
    return set()

def save_buys(email_type, buy_tickers):
    file_path = f"sent_buys_{email_type}.json"
    try:
        with open(file_path, "w") as f:
            json.dump(list(buy_tickers), f)
    except Exception as e:
        logger.warning(f"Could not save buys for {email_type}: {e}")

def is_temporary_failure(error: Exception) -> bool:
    msg = str(error).lower()
    # Keywords to identify temporary limitation errors
    temp_errors = ["rate limit", "too many requests", "timed out", "timeout", "503", "429"]
    # Keywords to identify permanent failures - ticker delisted, no price data etc.
    perm_errors = ["delisted", "no price data", "not found", "404"]
    if any(term in msg for term in temp_errors):
        return True
    if any(term in msg for term in perm_errors):
        return False
    # Default to temporary for unknown errors to be safe or customize
    return True

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
            # Decide if failure is temporary or permanent
            if is_temporary_failure(e):
                raise  # Let caller decide to retry
            else:
                logger.info(f"Permanent failure for {symbol}: {e}")
                return pd.DataFrame()
    else:
        try:
            last_date = df.index[-1]
            if not isinstance(last_date, pd.Timestamp):
                last_date = pd.to_datetime(last_date)
            start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logger.info("🔄 Updating %s from %s", symbol, start)
            new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning("Update error %s: %s", symbol, e)
            if not is_temporary_failure(e):
                return pd.DataFrame()
            # else: continue with cached data
    try:
        df.to_csv(file_path)
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", symbol, e)
    return df

# Other functions (calculate_indicators, generate_rsi_signal, fetch_fundamentals, etc.)
# same as before ...

def job(tickers_to_run):
    buy_alerts = []
    sell_alerts = []
    buy_tickers = []
    buy_prices = {}
    failed_tickers = []
    total, skipped = 0, 0

    for symbol in tickers_to_run:
        total += 1
        try:
            hist = fetch_cached_history(symbol)
            if hist.empty:
                logger.info(f"No historical data found for {symbol}; skipping.")
                failed_tickers.append(symbol)
                skipped += 1
                continue
        except Exception as e:
            if is_temporary_failure(e):
                logger.warning(f"Temporary failure fetching data for {symbol}: {e}")
                failed_tickers.append(symbol)
                skipped += 1
                continue
            else:
                logger.info(f"Permanent failure fetching data for {symbol}: {e}")
                skipped += 1
                continue

        hist = calculate_indicators(hist)
        sig, reason, rsi, price = generate_rsi_signal(hist)
        try:
            rt_price = finnhub_client.quote(symbol).get("c", price)
            if isinstance(rt_price, (pd.Series, pd.DataFrame)):
                rt_price = float(rt_price.squeeze())
        except Exception:
            rt_price = price
        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"])
        if sig:
            mcap_million = f"{(mcap / 1_000_000):,.2f}M" if mcap else "N/A"
            line_parts = [
                f"{symbol}: {sig} at ${rt_price:.2f}",
                reason,
                f"PE={pe if pe else 'N/A'}",
                f"MarketCap={mcap_million}"
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
                buy_prices[symbol] = rt_price
                logger.info(f"Added buy ticker: {symbol}")
            else:
                sell_alerts.append(line)

    # Process puts data as before...

    return buy_tickers, buy_alerts, sell_alerts, failed_tickers

def format_email_body(buy_alerts, sell_alerts, version="4"):
    email_body = f"This is Signal version {version}\n\n"
    if buy_alerts:
        email_body += f"🔹 Buy Signals:\n"
        email_body += "\n\n".join(f" - {alert}" for alert in buy_alerts) + "\n\n"
    if sell_alerts:
        email_body += f"🔸 Sell Signals:\n"
        email_body += "\n\n".join(f" - {alert}" for alert in sell_alerts) + "\n\n"
    return email_body

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated tickers to run Signal.py on")
    parser.add_argument("--email-type", type=str, choices=["first", "second", "hourly"], default="hourly",
                        help="Type of email to send")
    args = parser.parse_args()

    if args.tickers:
        tickers_to_run = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers_to_run = config.tickers

    previous_buys = load_previous_buys(args.email_type)

    all_failed_tickers = tickers_to_run.copy()
    all_buy_alerts = []
    all_sell_alerts = []
    all_buy_tickers = []
    retry_count = 0
    max_retries = 10  # Safety cap

    while all_failed_tickers and (retry_count < max_retries):
        logger.info(f"Attempt {retry_count+1}: Running job on {len(all_failed_tickers)} tickers")
        buy_tickers, buy_alerts, sell_alerts, failed_tickers = job(all_failed_tickers)

        all_buy_alerts.extend(buy_alerts)
        all_sell_alerts.extend(sell_alerts)
        all_buy_tickers.extend(buy_tickers)

        all_failed_tickers = failed_tickers

        if all_failed_tickers:
            logger.info(f"Waiting before retrying {len(all_failed_tickers)} failed tickers...")
            time.sleep(60)  # Delay before retry
        retry_count += 1

    all_buy_tickers = list(set(all_buy_tickers))
    new_buys = set(all_buy_tickers) - previous_buys

    if new_buys or all_sell_alerts:
        email_body = format_email_body(all_buy_alerts, all_sell_alerts)
        logger.info(f"Sending email with {len(new_buys)} new buys after {retry_count} attempts")
        print(email_body)
        send_email(f"StockHome Trading Alerts (after {retry_count} attempts)", email_body)
        save_buys(args.email_type, previous_buys.union(new_buys))
    else:
        logger.info("No new buys/sells to send after retry attempts.")

if __name__ == "__main__":
    main()
