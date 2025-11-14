import os
import datetime
import yfinance as yf
import finnhub
import pandas as pd
import ta
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import argparse
import time
import numpy as np
from dateutil.parser import parse
import config
import re

puts_dir = "puts_data"
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)
os.makedirs(puts_dir, exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("artifacts/data", exist_ok=True)


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
tickers = ['NDX','SPXU','SPY','SQQQ','TQQQ','UPRO']
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


def force_float(val):
    if isinstance(val, (pd.Series, np.ndarray)):
        return float(val.iloc[-1]) if hasattr(val, "iloc") and not val.empty else None
    if isinstance(val, pd.DataFrame):
        return float(val.values[-1][0])
    return float(val) if val is not None else None


@retry_on_rate_limit
def fetch_cached_history(symbol, period="40y", interval="1d"):
    path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df = None
    force_full = False
    if os.path.exists(path):
            try:
                cols = ['Date', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
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
        df = yf.download(symbol, period="max", interval=interval, auto_adjust=False)
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
    df["dma50"] = close.rolling(50).mean()
    return df

def fetch_fundamentals_safe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning(f"Failed to fetch fundamentals for {symbol}: {e}")
        return None, None


def log_alert(alert):
    csv_path = config.ALERTS_CSV
    exists = os.path.exists(csv_path)
    df_new = pd.DataFrame([alert])
    df_new.to_csv(csv_path, mode='a', header=not exists, index=False)


def job(tickers):
    prices = {}
    rsi_vals = {}
    failed = []
    total = skipped = 0
    stock_data_list = []

    for symbol in tickers:
        total += 1
        try:
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

        try:
            rt_price = fetch_quote(symbol)
            rt_price = force_float(rt_price)   

        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limit on price for {symbol}, waiting then retrying.")
                time.sleep(TICKER_RETRY_WAIT)
                try:
                    rt_price = fetch_quote(symbol)
                    rt_price = force_float(rt_price)
                except Exception as e2:
                    logger.error(f"Failed second price fetch for {symbol}: {e2}")
                    rt_price = None
            else:
                logger.error(f"Error fetching price for {symbol}: {e}")
                rt_price = None
         
        if rt_price is None or (isinstance(rt_price, float) and (np.isnan(rt_price) or rt_price <= 0)):
            rt_price = force_float(hist["Close"].iloc[-1] if not hist.empty else None)
        if rt_price is None or (isinstance(rt_price, float) and (np.isnan(rt_price) or rt_price <= 0)):
            logger.warning(f"Invalid price for {symbol}, skipping.")
            skipped += 1
            continue
        rsi_val = hist["rsi"].iloc[-1] if "rsi" in hist.columns else None
        dma200_val = hist["dma200"].iloc[-1] if "dma200" in hist.columns else None
        dma50_val = hist["dma50"].iloc[-1] if "dma50" in hist.columns else None

        last_close = hist["Close"].iloc[-1].item() if not hist.empty else None
        prev_close = hist["Close"].iloc[-2].item() if len(hist) > 1 else None
        
        rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
        pe_str_filter = f"{pe:.1f}" if pe is not None else "N/A"
        
        stock_data_list.append({
        'ticker': symbol,
        'signal' : sig,
        'price': float(rt_price) if rt_price is not None else None,
        'price_str': f"{rt_price:.2f}" if rt_price is not None else "N/A",
        'rsi': float(rsi_val) if rsi_val is not None else None,
        'rsi_str': f"{rsi_val:.1f}" if rsi_val is not None else "N/A",
        'dma200': float(dma200_val) if dma200_val is not None else None,
        'dma50': float(dma50_val) if dma50_val is not None else None,
        'dma200_str': f"{dma200_val:.1f}" if dma200_val is not None else "N/A",
        'dma50_str': f"{dma50_val:.1f}" if dma50_val is not None else "N/A",
        })
        if not sig:
            continue
        
             
    for sym in stock_data_list:
        price = prices.get(sym)
        rsi_val = rsi_vals.get(sym, None)
        dma200_val = hist["dma200"].iloc[-1] if "dma200" in hist.columns else None
        dma50_val = hist["dma50"].iloc[-1] if "dma50" in hist.columns else None
        price_str = f"{price:.2f}" if price is not None else "N/A"
        rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"

        
    return failed, stock_data_list


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    args = parser.parse_args()
    selected = [t.strip() for t in args.tickers.split(",")] if args.tickers else tickers
    retry_counts = defaultdict(int)
    to_process = selected[:]
    all_stock_data = []

    while to_process and any(retry_counts[t] < MAX_TICKER_RETRIES for t in to_process):
        logger.info(f"Processing {len(to_process)} tickers...")
        buys, buy_alerts_web, sells, fails, stock_data_list = job(to_process)
        all_buy_alerts_web.extend(buy_alerts_web)
        all_sell_alerts.extend(sells)
        all_buy_symbols.extend(buys)
        all_stock_data.extend(stock_data_list)  

        for f in fails:
            retry_counts[f] += 1
        to_process = [f for f in fails if retry_counts[f] < MAX_TICKER_RETRIES]
        if to_process:
            logger.info(f"Rate limited. Waiting {TICKER_RETRY_WAIT} seconds before retrying {len(to_process)} tickers...")
            time.sleep(TICKER_RETRY_WAIT)


if __name__ == "__main__":
    main()
