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
import numpy as np
from typing import Optional
from functools import wraps
from dateutil.parser import parse

# Setup logging
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

API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

tickers = config.tickers
finnhub_client = finnhub.Client(api_key=API_KEY)

MAX_RETRIES = 5
INITIAL_WAIT = 60  # seconds

def retry_on_rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        wait_time = INITIAL_WAIT
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                msg = str(e).lower()
                if any(term in msg for term in ["rate limit", "too many requests", "429"]):
                    logger.warning(f"Rate limit hit on attempt {attempt+1}/{MAX_RETRIES} for {func.__name__}: {e}")
                    logger.info(f"Waiting {wait_time} seconds before retry")
                    time.sleep(wait_time)
                    wait_time *= 2  # Exponential backoff
                else:
                    raise
        logger.error(f"Max retries exceeded for {func.__name__} with args {args} kwargs {kwargs}")
        raise Exception(f"Max retries exceeded for {func.__name__}")
    return wrapper

@retry_on_rate_limit
def fetch_history(symbol: str, period="2y", interval="1d") -> pd.DataFrame:
    df = None
    force_full = False
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    if os.path.exists(file_path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(file_path))).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            logger.info("%s cache too old (%d days) → full refresh", symbol, age_days)
            force_full = True
        else:
            try:
                column_names = ['Date', 'Price', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
                df = pd.read_csv(file_path, skiprows=3, names=column_names)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df.set_index('Date', inplace=True)
                if df.index.hasnans:
                    logger.warning("Date parsing failed in cached data for %s, forcing full refresh", symbol)
                    force_full = True
            except Exception as e:
                logger.warning(f"Error reading cache for {symbol}: {e}")
                df = None
    if df is None or df.empty or force_full:
        logger.info(f"Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df.to_csv(file_path)
    else:
        # Attempt incremental update
        try:
            last_date = df.index[-1]
            if not isinstance(last_date, pd.Timestamp):
                last_date = pd.to_datetime(last_date)
            start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logger.info(f"Updating {symbol} from {start}")
            new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
                df.to_csv(file_path)
        except Exception as e:
            logger.warning(f"Incremental update failed for {symbol}: {e}")
    return df

@retry_on_rate_limit
def fetch_quote(symbol: str) -> Optional[float]:
    quote = finnhub_client.quote(symbol)
    price = quote.get("c", None)
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return None
    return price

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    return df

def generate_signal(df: pd.DataFrame):
    last = df.iloc[-1]
    rsi = last.get("rsi", np.nan)
    price = last.get("Close", np.nan)
    if pd.isna(rsi) or pd.isna(price):
        return None, ""
    if rsi < config.RSI_OVERSOLD:
        return "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
    elif rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    else:
        return None, ""

def fetch_fundamentals_safe(symbol: str):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning(f"Error fetching fundamentals for {symbol}: {e}")
        return None, None

def fetch_option_chain_with_cache(symbol: str, lookback_days=52):
    puts_list = []
    try:
        ticker = yf.Ticker(symbol)
        all_dates = ticker.options
        today = datetime.datetime.now()
        valid_dates = [d for d in all_dates if (parse(d) - today).days <= 49]
        for exp_date in valid_dates:
            chain = ticker.option_chain(exp_date)
            puts = chain.puts
            if puts.empty:
                continue
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
            puts["distance"] = abs(puts["strike"] - under_price)
            atm_put = puts.loc[puts["distance"].idxmin()]
            puts_list.append({
                "expiration": exp_date,
                "strike": atm_put["strike"],
                "premium": atm_put["lastPrice"],
                "stock_price": under_price
            })
    except Exception as e:
        logger.warning(f"Failed fetching options for {symbol}: {e}")
    return puts_list

def calculate_custom_metrics(puts_list, stock_price):
    if stock_price is None or stock_price <= 0 or np.isnan(stock_price):
        return puts_list
    for put in puts_list:
        strike = put.get("strike", None)
        premium = put.get("premium", 0)
        try:
            premium_val = float(premium) if premium is not None else 0.0
            metric = ((stock_price - strike) + (premium_val / 100)) / stock_price * 100 if strike else None
            delta_p = ((stock_price - strike) / stock_price) * 100 if strike else None
            premium_p = (premium_val / stock_price) * 100 if premium_val else None
            put["custom_metric"] = metric
            put["delta_percent"] = delta_p
            put["premium_percent"] = premium_p
        except Exception as e:
            logger.warning(f"Error computing metrics for put: {e}")
            put["custom_metric"] = None
            put["delta_percent"] = None
            put["premium_percent"] = None
    return puts_list

def format_market_cap(mcap):
    if not mcap:
        return "N/A"
    if mcap >= 1e9:
        return f"{mcap/1e9:.1f}B"
    if mcap >= 1e6:
        return f"{mcap/1e6:.1f}M"
    return str(mcap)

def send_email(subject: str, body: str):
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        logger.error("Email settings missing")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

def log_alert(alert):
    csv_file = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    write_header = not os.path.exists(csv_file)
    df.to_csv(csv_file, mode='a', header=write_header, index=False)

def format_email_body(buys, sells, version="4"):
    email_body = f"📊 StockHome Trading Signals v{version}\nGenerated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    email_body += "="*60 + "\n\n"
    if buys:
        email_body += "🟢 BUY SIGNALS\n\n"
        for alert in buys:
            lines = alert.split('\n')
            header = lines[0]
            email_body += f"📈 {header}\n"
            puts_lines = [l for l in lines[1:] if 'expiration=' in l]
            if puts_lines:
                email_body += " 📋 Recommended Puts:\n"
                for put_line in puts_lines:
                    try:
                        parts = put_line.split(', ')
                        fields = {}
                        for p in parts:
                            key, val = p.split('=', 1)
                            fields[key.strip()] = val.strip()
                        email_body += (" - Exp: {expiration}, Strike: ${strike}, Premium: ${premium}, Stock: ${stock_price}, "
                                       "Metric: {custom_metric}, Delta%: {delta_percent}, Premium%: {premium_percent}\n").format(**fields)
                    except Exception:
                        email_body += f" - {put_line}\n"
            email_body += "\n"
    if sells:
        email_body += "🔴 SELL SIGNALS\n\n"
        for s in sells:
            email_body += f"{s}\n\n"
    return email_body

def job(tickers_to_run):
    buys = []
    sells = []
    buy_symbols = []
    prices = {}
    failed = []
    total, skipped = 0, 0
    for symbol in tickers_to_run:
        total += 1
        try:
            hist = fetch_history(symbol)
            if hist.empty:
                logger.info(f"No historical data for {symbol}, skipping")
                skipped +=1
                continue
        except Exception as e:
            msg = str(e).lower()
            if "possibly delisted" in msg or "no price data" in msg:
                logger.info(f"{symbol} delisted or no data, skipping")
                skipped +=1
                continue
            elif "rate limit" in msg or "too many requests" in msg:
                logger.warning(f"Rate limit error for {symbol}, retry triggered")
                time.sleep(60)
                continue 
            else:
                logger.error(f"Error fetching history for {symbol}: {e}")
                skipped +=1
                continue
        hist = calculate_indicators(hist)
        sig, reason = generate_signal(hist)
        if not sig:
            continue

        # Fetch price with retry logic
        try:
            rt_price = fetch_quote(symbol)
        except Exception as e:
            msg = str(e).lower()
            if "rate limit" in msg or "too many requests" in msg:
                logger.warning(f"Rate limited fetching quote for {symbol}, wait and retry")
                time.sleep(60)
                try:
                    rt_price = fetch_quote(symbol)
                except Exception as e2:
                    logger.error(f"Failed second quote attempt for {symbol}: {e2}")
                    rt_price = None
            else:
                logger.error(f"Failed fetching quote for {symbol}: {e}")
                rt_price = None

        if rt_price is None or rt_price != rt_price:  # check NaN
            # fallback to last close
            if hist.empty:
                logger.warning(f"No fallback price for {symbol}, skipping")
                skipped +=1
                continue
            rt_price = hist["Close"].iloc[-1]

        if rt_price != rt_price or rt_price is None or rt_price <= 0:
            logger.warning(f"Invalid price for {symbol}, skipping: {rt_price}")
            skipped +=1
            continue

        pe, mcap = fetch_fundamentals_safe(symbol)
        iv_hist = fetch_option_chain_with_cache(symbol)
        iv_rank, iv_pct = None, None
        if iv_hist:
            iv_rank, iv_pct = calc_iv_rank_percentile(pd.Series([put["premium"] for put in iv_hist]))

        line_parts = [
            f"{symbol}: {sig} at ${rt_price:.2f}",
            f"{reason}",
            f"PE={pe:.1f}" if pe else "PE=N/A",
            f"MarketCap={format_market_cap(mcap)}"
        ]
        if iv_rank is not None:
            line_parts.append(f"IV Rank={iv_rank:.2f}")
        if iv_pct is not None:
            line_parts.append(f"IV Percentile={iv_pct:.2f}")
        line = ", ".join(line_parts)

        # Logging alert data
        alert_dict = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": symbol,
            "signal": sig,
            "price": rt_price,
            "rsi": hist["rsi"].iloc[-1],
            "pe_ratio": pe,
            "market_cap": mcap,
            "iv_rank": iv_rank,
            "iv_percentile": iv_pct,
        }
        log_alert(alert_dict)

        if sig == "BUY":
            buys.append(line)
            buy_symbols.append(symbol)
            prices[symbol] = rt_price
        else:
            sells.append(line)

    logger.info(f"Completed processing: {total} total, {skipped} skipped, {len(buy_symbols)} buys")

    # Process options for buys
    puts_dir = "puts_data"
    os.makedirs(puts_dir, exist_ok=True)

    for sym in buy_symbols:
        puts = fetch_option_chain_with_cache(sym)
        price = prices.get(sym)
        puts = calculate_custom_metrics(puts, price)

        # Filter puts
        filtered_puts = [p for p in puts if p.get("strike", 0) < price and p.get("custom_metric") and p["custom_metric"] >= 10]

        # Group by expiration and select one put per expiration closest to metric=10
        puts_by_exp = defaultdict(list)
        for p in filtered_puts:
            exp = p.get("expiration")
            if exp:
                puts_by_exp[exp].append(p)

        selected_puts = []
        for exp, group in puts_by_exp.items():
            sel = min(group, key=lambda x: abs(x.get("custom_metric", 0) - 10))
            selected_puts.append(sel)

        # Generate put info string for alerts
        put_lines = []
        for put in selected_puts:
            strike = put.get("strike", "N/A")
            premium = put.get("premium", "N/A")
            cm = put.get("custom_metric", "N/A")
            delta = put.get("delta_percent", "N/A")
            prem_pct = put.get("premium_percent", "N/A")
            if isinstance(strike, float):
                strike = f"{strike:.1f}"
            if isinstance(premium, float):
                premium = f"{premium:.2f}"
            if isinstance(cm, float):
                cm = f"{cm:.1f}%"
            if isinstance(delta, float):
                delta = f"{delta:.1f}%"
            if isinstance(prem_pct, float):
                prem_pct = f"{prem_pct:.1f}%"
            line = f"expiration={put['expiration']}, strike={strike}, premium={premium}, stock_price={price:.2f}, custom_metric={cm}, delta%={delta}, premium%={prem_pct}"
            put_lines.append(line)

        put_info = "\n" + "\n--------------------\n".join(put_lines)

        # Append puts info to buy alerts
        for i, val in enumerate(buys):
            if val.startswith(sym + ":"):
                buys[i] = val + " " + put_info
                break

        # Save puts details json per symbol
        try:
            with open(os.path.join(puts_dir, f"{sym}_puts_7weeks.json"), "w") as f_json:
                json.dump(selected_puts, f_json, indent=2)
            logger.info(f"Saved puts data for {sym}")
        except Exception as e:
            logger.error(f"Error saving puts data for {sym}: {e}")

    return buy_symbols, buys, sells, []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers list")
    parser.add_argument("--email-type", type=str, choices=["first", "second", "hourly"], default="hourly", help="Email type")
    args = parser.parse_args()

    selected_tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else tickers

    prev_buys = load_previous_buys(args.email_type)

    retry_counts = defaultdict(int)
    MAX_RETRY = 5
    to_process = selected_tickers[:]
    all_buys, all_sells, all_buys_symbols = [], [], []

    while to_process:
        logger.info(f"Running job on {len(to_process)} tickers")
        buys, buy_alerts, sells, fails = job(to_process)
        all_buys.extend(buy_alerts)
        all_sells.extend(sells)
        all_buys_symbols.extend(buys)
        for f in fails:
            retry_counts[f] += 1
        to_process = [f for f in fails if retry_counts[f] < MAX_RETRY]
        if to_process:
            wait_sec = 60
            logger.info(f"Waiting {wait_sec} seconds before retrying {len(to_process)} tickers")
            time.sleep(wait_sec)

    unique_buys = set(all_buys_symbols)
    new_buys = unique_buys - prev_buys

    if new_buys or all_sells:
        email_body = format_email_body(all_buys, all_sells)
        logger.info(f"Sending email with {len(new_buys)} new buys")
        print(email_body)
        send_email(f"StockHome Alerts - {datetime.datetime.now().strftime('%Y-%m-%d')}", email_body)
        save_previous(args.email_type, prev_buys.union(new_buys))
    else:
        logger.info("No new buys or sells to send")

if __name__ == "__main__":
    main()
