import os
import datetime
import json
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import argparse
import time
import numpy as np
from dateutil.parser import parse
import config

# Setup logging
puts_dir = "puts_data"
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)
os.makedirs(puts_dir, exist_ok=True)
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(log_path, maxBytes=config.LOG_MAX_BYTES, backupCount=config.LOG_BACKUP_COUNT, encoding='utf-8')
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
tickers = config.tickers
finnhub_client = finnhub.Client(api_key=API_KEY)

MAX_API_RETRIES = 5
API_RETRY_INITIAL_WAIT = 60
MAX_TICKER_RETRIES = 100
TICKER_RETRY_WAIT = 60


def retry_on_rate_limit(func):
    def wrapper(*args, **kwargs):
        wait = API_RETRY_INITIAL_WAIT
        for attempt in range(MAX_API_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                e_str = str(e).lower()
                if any(term in e_str for term in ["rate limit", "too many requests", "429"]):
                    logger.warning(f"Rate limit hit on {func.__name__}, attempt {attempt + 1}/{MAX_API_RETRIES}: {e}")
                    logger.info(f"Sleeping for {wait} seconds before retry")
                    time.sleep(wait)
                    wait *= 2
                    continue
                raise
        logger.error(f"Exceeded max retries for {func.__name__} with args {args}, kwargs {kwargs}")
        raise
    return wrapper

@retry_on_rate_limit
def fetch_history(symbol, period="2y", interval="1d"):
    path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df = None
    force_full = False
    # Always log the directory state at start
    logger.info(f"mydata contents: {os.listdir(config.DATA_DIR)}")
    
    if os.path.exists(path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age_days > config.MAX_CACHE_DAYS:
            force_full = True
            logger.info(f"Cache for {symbol} is stale ({age_days} days), refreshing")
        else:
            try:
                df = pd.read_csv(path, index_col=0, parse_dates=True)  # Automatically match what to_csv writes
                df = df.loc[:, ~df.columns.duplicated()]
                # Keep canonical columns only
                df = df[[c for c in df.columns if c in ['Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']]]
                # Ensure "Close" is Series for TA-Lib
                df.index = pd.to_datetime(df.index, errors='coerce')
                logger.info(f"Read cache for {symbol}, {df.shape} rows, columns: {df.columns.tolist()}")
                logger.info(f"CMG columns: {df.columns.tolist()}")
                logger.info(f"Head:\n{df.head().to_string()}")

            except Exception as e:
                logger.warning(f"Failed reading cache for {symbol}: {e}")
                df = None
    if df is None or df.empty or force_full:
        logger.info(f"Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            logger.warning(f"{symbol}: yf.download returned EMPTY dataframe! No CSV will be saved.")
            return pd.DataFrame()
        df.to_csv(path)
        logger.info(f"Saved CSV for {symbol} to {path}, {df.shape} rows")
    else:
        try:
            last = df.index[-1]
            if not isinstance(last, pd.Timestamp):
                last = pd.to_datetime(last)
            start_date = (last - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logger.info(f"Updating {symbol} from {start_date}")
            new_df = yf.download(symbol, start=start_date, interval=interval, auto_adjust=False)
            if not new_df.empty:
                new_df.index = pd.to_datetime(new_df.index, errors='coerce')
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
                df.index = pd.to_datetime(df.index, errors='coerce')
                df.to_csv(path)
                logger.info(f"Updated and saved CSV for {symbol}, now {df.shape} rows")
        except Exception as e:
            logger.warning(f"Incremental update failed for {symbol}: {e}")
    # Log the folder again at end
    logger.info(f"mydata updated: {os.listdir(config.DATA_DIR)}")
    return df

@retry_on_rate_limit
def fetch_quote(symbol):
    quote = finnhub_client.quote(symbol)
    price = quote.get("c", None)
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return None
    return price

def calculate_indicators(df):
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:,0]
    else:
        close = pd.Series(close)
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    #df["dma200"] = close.rolling(200).mean()
    return df

def generate_signal(df):
    if df.empty or "rsi" not in df.columns:
        return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None, ""
    price = df["Close"].iloc[-1] if "Close" in df.columns else np.nan
    if rsi < config.RSI_OVERSOLD:
        return "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
    if rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return None, ""

def fetch_fundamentals_safe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning(f"Failed to fetch fundamentals for {symbol}: {e}")
        return None, None

def fetch_puts(symbol):
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        valid_dates = [d for d in ticker.options if (parse(d) - today).days <= 49]
        for exp in valid_dates:
            chain = ticker.option_chain(exp)
            if chain.puts.empty:
                continue
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
            chain.puts["distance"] = abs(chain.puts["strike"] - under_price)
            for _, put in chain.puts.iterrows():
                strike = put["strike"]
                premium = put.get("lastPrice") or ((put.get("bid") + put.get("ask")) / 2 if (put.get("bid") is not None and put.get("ask") is not None) else None)
                puts_data.append({
                    "expiration": exp,
                    "strike": strike,
                    "premium": premium,
                    "stock_price": under_price
                })
    except Exception as e:
        logger.warning(f"Failed to fetch puts for {symbol}: {e}")
    return puts_data

def format_buy_alert_line(ticker, price, rsi, pe, mcap, strike, expiration, premium, delta_percent, premium_percent):
    price_str = f"{price:.2f}" if price is not None else "N/A"
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    pe_str = f"{pe:.1f}" if pe is not None else "N/A"
    strike_str = f"{strike:.1f}" if strike is not None else "N/A"
    premium_str = f"{premium:.2f}" if premium is not None else "N/A"
    dp = f"{delta_percent:.1f}%" if delta_percent is not None else "N/A"
    pp = f"{premium_percent:.1f}%" if premium_percent is not None else "N/A"
    metric_sum = None
    if (delta_percent is not None) and (premium_percent is not None):
        metric_sum = delta_percent + premium_percent
    metric_sum_str = f"{metric_sum:.1f}%" if metric_sum is not None else "N/A"
    return (
        f"{ticker} (${price_str}): "
        f"RSI={rsi_str}, "
        f"P/E={pe_str}, "
        f"Market Cap=${mcap}, "
        f"${strike_str}+"
        f"${premium_str} premium on {expiration},"
        f"[𝚫 {dp} + 💎 {pp}] = {metric_sum_str}"
    )

def format_sell_alert_line(ticker, price, rsi, pe, mcap):
    return f"{ticker} (${price:.2f}): RSI={rsi:.1f}, P/E={pe:.1f}, Market Cap=${mcap}"

def calculate_custom_metrics(puts, price):
    if price is None or price <= 0 or np.isnan(price):
        return puts
    for p in puts:
        strike = p.get("strike")
        premium = p.get("premium") or 0.0
        try:
            premium_val = float(premium)
            p["custom_metric"] = ((price - strike) + premium_val / 100) / price * 100 if strike else None
            p["delta_percent"] = ((price - strike) / price) * 100 if strike else None
            p["premium_percent"] = premium_val / price * 100 if premium_val else None
        except Exception as e:
            logger.warning(f"Error computing metrics for put {p}: {e}")
            p["custom_metric"] = p["delta_percent"] = p["premium_percent"] = None
    return puts

def format_market_cap(mcap):
    if not mcap:
        return "N/A"
    if mcap >= 1e9:
        return f"{mcap / 1e9:.1f}B"
    if mcap >= 1e6:
        return f"{mcap / 1e6:.1f}M"
    return str(mcap)

def send_email(subject, body):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        logger.error("Email credentials not set!")
        return
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as s:
            s.starttls()
            s.login(EMAIL_SENDER, EMAIL_PASSWORD)
            s.send_message(msg)
        logger.info("Email sent")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

def log_alert(alert):
    csv_path = config.ALERTS_CSV
    exists = os.path.exists(csv_path)
    df_new = pd.DataFrame([alert])
    df_new.to_csv(csv_path, mode='a', header=not exists, index=False)

def format_email_body(buy_alerts, sell_alerts):
    lines = [
        f"📊 StockHome Trading Signals",
        f"Generated: {(datetime.datetime.now() - datetime.timedelta(hours=7)):%Y-%m-%d %H:%M:%S} PT",
        ""]
    if buy_alerts:
        lines.append("🟢 BUY SIGNALS")
        for alert in buy_alerts:
            lines.append(f"📈 {alert}")
    if sell_alerts:
        lines.append("🔴 SELL SIGNALS")
        for alert in sell_alerts:
            lines.append(f"📉 {alert}")
    return "\n".join(lines)

def job(tickers):
    buy_alerts, sell_alerts = [], []
    buy_symbols = []
    prices = {}
    failed = []
    total = skipped = 0
    for symbol in tickers:
        total += 1
        try:
            hist = fetch_history(symbol)
            if hist.empty:
                logger.info(f"No historical data for {symbol}, skipping.")
                skipped += 1
                continue
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limited on fetching history for {symbol}, retry delayed.")
                failed.append(symbol)
                continue
            if any(k in msg for k in ["delisted", "no data", "not found"]):
                logger.info(f"{symbol} delisted or no data, skipping.")
                skipped += 1
                continue
            logger.error(f"Error fetching history for {symbol}: {e}")
            skipped += 1
            continue
        hist = calculate_indicators(hist)
        sig, reason = generate_signal(hist)
        if not sig:
            continue
        try:
            rt_price = fetch_quote(symbol)
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limit on price for {symbol}, waiting then retrying.")
                time.sleep(TICKER_RETRY_WAIT)
                try:
                    rt_price = fetch_quote(symbol)
                except Exception as e2:
                    logger.error(f"Failed second price fetch for {symbol}: {e2}")
                    rt_price = None
            else:
                logger.error(f"Error fetching price for {symbol}: {e}")
                rt_price = None
        if rt_price is None or rt_price != rt_price or rt_price <= 0:
            rt_price = hist["Close"].iloc[-1] if not hist.empty else None
        if rt_price is None or rt_price != rt_price or rt_price <= 0:
            logger.warning(f"Invalid price for {symbol}, skipping.")
            skipped += 1
            continue
        pe, mcap = fetch_fundamentals_safe(symbol)
        #iv_hist = fetch_puts(symbol)
        #iv_rank = iv_pct = None
        #if iv_hist:
            #iv_rank, iv_pct = calc_iv_rank_percentile(pd.Series([p["premium"] for p in iv_hist if p.get("premium") is not None]))
        cap_str = format_market_cap(mcap)
        rsi_val = hist["rsi"].iloc[-1] if "rsi" in hist.columns else None
        pe_str = f"{pe:.1f}" if pe else "N/A"
        parts = [
            f"{symbol}: {sig} at ${rt_price:.2f}",
            reason,
            f"PE={pe_str}",
            f"Market Cap={cap_str}",
        ]
        #if iv_rank is not None:
            #parts.append(f"IV Rank={iv_rank:.2f}")
        #if iv_pct is not None:
            #parts.append(f"IV Percentile={iv_pct:.2f}")
        alert_line = ", ".join(parts)
        alert_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": symbol,
            "signal": sig,
            "price": rt_price,
            "rsi": hist["rsi"].iloc[-1] if "rsi" in hist.columns else None,
            "pe_ratio": pe,
            "market_cap": mcap,
            #"iv_rank": iv_rank,
            #"iv_percentile": iv_pct,
        }
        log_alert(alert_data)
        if sig == "BUY":
            buy_symbols.append(symbol)
            prices[symbol] = rt_price
        else:
            sell_alert_line = format_sell_alert_line(
                        ticker=symbol,
                        price=rt_price,
                        rsi=rsi_val,
                        pe=pe,
                        mcap=cap_str)
            sell_alerts.append(sell_alert_line)
            
    # Only one best recommended put per ticker, by highest premium_percent

    for sym in buy_symbols:
        price = prices.get(sym)
        pe, mcap = fetch_fundamentals_safe(sym)
        cap_str = format_market_cap(mcap)
        hist = fetch_history(sym)
        rsi_val = hist["rsi"].iloc[-1] if "rsi" in hist.columns else None
        puts_list = fetch_puts(sym)
        puts_list = calculate_custom_metrics(puts_list, price)
        filtered_puts = [
            p for p in puts_list
            if p.get("strike") is not None and price
            and p["strike"] < price
            and p.get("custom_metric") and p["custom_metric"] >= 10
        ]
        if not filtered_puts:
            continue
        best_put = max(filtered_puts, key=lambda x: x.get('premium_percent', 0) or x.get('premium', 0))
        expiration_fmt = datetime.datetime.strptime(best_put['expiration'], "%Y-%m-%d").strftime("%b %d, %Y") if best_put.get('expiration') else "N/A"
        buy_alert_line = format_buy_alert_line(
                ticker=sym,
                price=price if price is not None else 0.0,
                rsi=rsi_val if rsi_val is not None else 0.0,
                pe=pe if pe is not None else 0.0,
                mcap=cap_str if cap_str is not None else "N/A",
                strike=float(best_put['strike']) if best_put.get('strike') is not None else 0.0,
                expiration=expiration_fmt if expiration_fmt else "N/A",
                premium=float(best_put['premium']) if best_put.get('premium') is not None else 0.0,
                delta_percent=float(best_put['delta_percent']) if best_put.get('delta_percent') is not None else 0.0,
                premium_percent=float(best_put['premium_percent']) if best_put.get('premium_percent') is not None else 0.0
        )
        buy_alerts.append(buy_alert_line)
        # Save JSON for recordkeeping/other uses
        puts_json_path = os.path.join(puts_dir, f"{sym}_puts_7weeks.json")
        try:
                with open(puts_json_path, "w") as fp:
                        json.dump([best_put], fp, indent=2)
                logger.info(f"Saved puts data for {sym}")
        except Exception as e:
                logger.error(f"Failed to save puts json for {sym}: {e}")
    return buy_symbols, buy_alerts, sell_alerts, failed

def load_previous_buys(email_type):
    return set()
def save_buys(email_type, buys_set):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    parser.add_argument("--email-type", type=str, choices=["first","second","hourly"], default="hourly", help="Email type")
    args = parser.parse_args()
    selected = [t.strip() for t in args.tickers.split(",")] if args.tickers else tickers
    prev_buys = load_previous_buys(args.email_type)
    retry_counts = defaultdict(int)
    to_process = selected[:]
    all_buy_alerts = []
    all_sell_alerts = []
    all_buy_symbols = []
    while to_process and any(retry_counts[t] < MAX_TICKER_RETRIES for t in to_process):
        logger.info(f"Processing {len(to_process)} tickers...")
        buys, buy_alerts, sells, fails = job(to_process)
        all_buy_alerts.extend(buy_alerts)
        all_sell_alerts.extend(sells)
        all_buy_symbols.extend(buys)
        for f in fails:
            retry_counts[f] += 1
        to_process = [f for f in fails if retry_counts[f] < MAX_TICKER_RETRIES]
        if to_process:
            logger.info(f"Rate limited. Waiting {TICKER_RETRY_WAIT} seconds before retrying {len(to_process)} tickers...")
            time.sleep(TICKER_RETRY_WAIT)
    unique_buys = set(all_buy_symbols)
    new_buys = unique_buys.difference(prev_buys)
    if new_buys or all_sell_alerts:
        body = format_email_body(all_buy_alerts, all_sell_alerts)
        logger.info(f"Sending email with {len(new_buys)} new buys")
        print(body)
        send_email("StockHome Trading Alerts", body)
        save_buys(args.email_type, prev_buys.union(new_buys))
    else:
        logger.info("No new buys or sells to report.")

if __name__ == "__main__":
    main()
