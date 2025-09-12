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

# ANSI bold escape codes for most terminals (works in many modern consoles and best effort in plain text emails)
def bold(text):
    return f"\033[1m{text}\033[0m"

# Setup logging
os.makedirs(config.LOG_DIR, exist_ok=True)
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
    if os.path.exists(path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age_days > config.MAX_CACHE_DAYS:
            force_full = True
            logger.info(f"Cache for {symbol} is stale ({age_days} days), refreshing")
        else:
            try:
                cols = ['Date', 'Price', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
                df = pd.read_csv(path, skiprows=3, names=cols)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df.set_index('Date', inplace=True)
                if df.index.hasnans:
                    logger.warning(f"Cache date parsing failed for {symbol}, refreshing cache")
                    force_full = True
            except Exception as e:
                logger.warning(f"Failed reading cache for {symbol}: {e}")
                df = None
    if df is None or df.empty or force_full:
        logger.info(f"Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df.to_csv(path)
    else:
        try:
            last = df.index[-1]
            if not isinstance(last, pd.Timestamp):
                last = pd.to_datetime(last)
            start_date = (last - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logger.info(f"Updating {symbol} from {start_date}")
            new_df = yf.download(symbol, start=start_date, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
                df.to_csv(path)
        except Exception as e:
            logger.warning(f"Incremental update failed for {symbol}: {e}")
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
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    return df

def generate_signal(df):
    if df.empty or "rsi" not in df.columns:
        return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None, ""
    price = df["Close"].iloc[-1] if "Close" in df.columns else np.nan
    if rsi < config.RSI_OVERSOLD:
        return "BUY", f"RSI={rsi:.1f}"
    if rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f}"
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

def calculate_custom_metrics(puts, price):
    if price is None or price <= 0 or np.isnan(price):
        return puts
    for p in puts:
        strike = p.get("strike")
        premium = p.get("premium") or 0.0
        try:
            premium_val = float(premium)
            delta_percent = ((price - strike) / price) * 100 if strike else 0
            premium_percent = (premium_val / price) * 100 if premium_val else 0
            p["delta_percent"] = delta_percent
            p["premium_percent"] = premium_percent
            p["custom_metric"] = delta_percent + premium_percent if strike else None
        except Exception as e:
            logger.warning(f"Error computing metrics for put {p}: {e}")
            p["custom_metric"] = p["delta_percent"] = p["premium_percent"] = None
    return puts

def format_market_cap(mcap):
    if not mcap:
        return "N/A"
    if mcap >= 1e9:
        return f"${mcap / 1e9:.1f}B"
    if mcap >= 1e6:
        return f"${mcap / 1e6:.1f}M"
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

def format_email_body(buy_alerts, sell_alerts, version="4"):
    lines = [
        f"📊 StockHome Trading Signals v{version}",
        f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "="*60,
        ""
    ]
    if buy_alerts:
        lines.append("🟢 BUY SIGNALS")
        for alert in buy_alerts:
            lines.append(f"📈 {alert}")
    if sell_alerts:
        lines.append("🔴 SELL SIGNALS")
        lines.extend(f"📉 {alert}" for alert in sell_alerts)
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
        cap_str = format_market_cap(mcap)
        pe_str = f"{pe:.1f}" if pe is not None else "N/A"

        option_text = ""
        puts_dir = "puts_data"
        os.makedirs(puts_dir, exist_ok=True)
        puts_list = fetch_puts(symbol)
        price = rt_price
        puts_list = calculate_custom_metrics(puts_list, price)
        filtered_puts = [
            p for p in puts_list
            if p.get("strike") is not None and price
            and p["strike"] < price
            and p.get("custom_metric") and p["custom_metric"] >= 10
        ]
        best_put = None
        if filtered_puts:
            best_put = max(filtered_puts, key=lambda x: x.get('premium_percent', 0) or x.get('premium', 0))
            strike = f"{best_put['strike']:.1f}" if isinstance(best_put['strike'], (int, float)) else "N/A"
            premium = f"{best_put['premium']:.2f}" if isinstance(best_put['premium'], (int, float)) else "N/A"
            delta = best_put.get('delta_percent', 0)
            prem_pct = best_put.get('premium_percent', 0)
            metric_sum = delta + prem_pct
            exp = best_put['expiration']
            option_text = (
                f"Recommended Put Option: Exp date: {exp}, Strike price: ${strike}, Premium: ${premium}, "
                f"[Δ%: {delta:.1f} + 💎%: {prem_pct:.1f}] = {metric_sum:.1f}%"
            )
            puts_json_path = os.path.join(puts_dir, f"{symbol}_puts_7weeks.json")
            try:
                with open(puts_json_path, "w") as fp:
                    json.dump([best_put], fp, indent=2)
                logger.info(f"Saved puts data for {symbol}")
            except Exception as e:
                logger.error(f"Failed to save puts json for {symbol}: {e}")

        alert_line = (
            f"{bold(symbol)}: BUY at ${rt_price:.2f}, RSI={hist['rsi'].iloc[-1]:.1f}, "
            f"PE={pe_str}, Market Cap={cap_str}, {option_text}"
        )
        alert_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": symbol,
            "signal": sig,
            "price": rt_price,
            "rsi": hist["rsi"].iloc[-1] if "rsi" in hist.columns else None,
            "pe_ratio": pe,
            "market_cap": mcap,
        }
        log_alert(alert_data)
        if sig == "BUY":
            buy_alerts.append(alert_line)
            buy_symbols.append(symbol)
            prices[symbol] = rt_price
            logger.info(f"Buy signal: {symbol}")
        else:
            sell_alerts.append(alert_line)
            logger.info(f"Sell signal: {symbol}")
    return buy_symbols, buy_alerts, sell_alerts, failed

def load_previous_buys(email_type):
    return set()

def save_buys(email_type, buys_set):
    pass

def calc_iv_rank_percentile(series):
    if series.empty:
        return None, None
    iv_rank = (series.iloc[-1] - series.min()) / (series.max() - series.min()) * 100 if (series.max() - series.min()) != 0 else 0
    iv_pct = series.rank(pct=True).iloc[-1] * 100
    return iv_rank, iv_pct

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
        send_email("Stock Home Trading Alerts", body)
        save_buys(args.email_type, prev_buys.union(new_buys))
    else:
        logger.info("No new buys or sells to report.")

if __name__ == "__main__":
    main()
