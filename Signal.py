import os
import json
import datetime
import time
import yfinance as yf
import finnhub
import pandas as pd
import ta
import numpy as np
import pytz
import logging
from logging.handlers import RotatingFileHandler
from dateutil.parser import parse
import argparse
import re

import config
from news_fetcher import fetch_news_ticker

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
W_TREND = 40
W_RSI = 25
W_MACD = 25
W_DISTANCE = 10

CACHE_FUNDAMENTALS_HOURS = 24
FETCH_NEWS = True   # News fetched ONLY for BUY signals

pacific = pytz.timezone("US/Pacific")
dt_pacific = datetime.datetime.now(pacific)

DATA_DIR = config.DATA_DIR
LOG_DIR = config.LOG_DIR
FUND_DIR = "data/fundamentals"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FUND_DIR, exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("artifacts/data", exist_ok=True)

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
log_path = os.path.join(LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)

if not logger.handlers:
    fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)

# ---------------------------------------------------------
# API CLIENTS
# ---------------------------------------------------------
FINNHUB_KEY = os.getenv("API_KEY")
finnhub_client = finnhub.Client(api_key=FINNHUB_KEY)

# ---------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------
def clamp(x, lo, hi): return max(lo, min(hi, x))

def scalar(x):
    if hasattr(x, "iloc"): return float(x.iloc[-1])
    return float(x)

# ---------------------------------------------------------
# PRICE FETCH (PRIORITY ORDER)
# ---------------------------------------------------------
def get_live_price(symbol, fallback_close):
    """Finnhub → yfinance → CSV"""
    try:
        q = finnhub_client.quote(symbol)
        price = q.get("c")
        if price and price > 0:
            return float(price)
    except Exception:
        pass

    try:
        price = yf.Ticker(symbol).fast_info.get("lastPrice")
        if price and price > 0:
            return float(price)
    except Exception:
        pass

    return fallback_close

# ---------------------------------------------------------
# FUNDAMENTALS (CACHED)
# ---------------------------------------------------------
def fetch_fundamentals_cached(symbol):
    path = os.path.join(FUND_DIR, f"{symbol}.json")

    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < CACHE_FUNDAMENTALS_HOURS * 3600:
            with open(path, "r") as f:
                return json.load(f)

    try:
        info = yf.Ticker(symbol).info
        data = {
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "earnings_growth": info.get("earningsQuarterlyGrowth"),
            "debt_to_equity": info.get("debtToEquity"),
            "market_cap": info.get("marketCap"),
        }
        with open(path, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        logger.warning(f"Fundamentals error for {symbol}: {e}")
        return {}

# ---------------------------------------------------------
# HISTORY CACHE
# ---------------------------------------------------------
def fetch_cached_history(symbol, period="1y"):
    path = os.path.join(DATA_DIR, f"{symbol}.csv")

    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if len(df) >= 200:
            return df

    df = yf.download(symbol, period=period, progress=False)
    if not df.empty:
        df.to_csv(path)
    return df

# ---------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------
def calculate_indicators(df):
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    df["rsi"] = ta.momentum.RSIIndicator(close, 14).rsi()
    df["dma200"] = close.rolling(200).mean()
    df["dma50"] = close.rolling(50).mean()

    macd = ta.trend.MACD(close)
    df["macd"] = macd.macd()
    df["signal"] = macd.macd_signal()
    df["hist"] = macd.macd_diff()

    adx = ta.trend.ADXIndicator(high, low, close)
    df["adx"] = adx.adx()

    bb = ta.volatility.BollingerBands(close)
    df["bb_low"] = bb.bollinger_lband()
    df["bb_high"] = bb.bollinger_hband()

    kc = ta.volatility.KeltnerChannel(high, low, close)
    df["kc_low"] = kc.keltner_channel_lband()
    df["kc_high"] = kc.keltner_channel_hband()

    return df

# ---------------------------------------------------------
# SPREAD STRATEGY DETECTION
# ---------------------------------------------------------
def get_spread_strategy(row):
    p = scalar(row["Close"])
    r = scalar(row["rsi"])
    a = scalar(row["adx"])

    bl, bu = scalar(row["bb_low"]), scalar(row["bb_high"])
    kl, ku = scalar(row["kc_low"]), scalar(row["kc_high"])

    is_squeeze = not (bl < kl or bu > ku)

    if p <= bl and r < 40 and a < 35:
        return {"strategy": "Call Debit Spread (Bullish)", "type": "bullish", "is_squeeze": is_squeeze}

    return None

# ---------------------------------------------------------
# MAIN JOB LOOP (SEQUENTIAL)
# ---------------------------------------------------------
def job(tickers):
    stock_data = []
    spreads = []

    for symbol in tickers:
        logger.info(f"Processing {symbol}")

        df = fetch_cached_history(symbol)
        if df.empty or len(df) < 200:
            continue

        df = calculate_indicators(df)
        row = df.iloc[-1]

        spread = get_spread_strategy(row)
        if not spread or spread["is_squeeze"]:
            continue

        close_price = scalar(row["Close"])
        price = get_live_price(symbol, close_price)

        funds = fetch_fundamentals_cached(symbol)

        pe_pass = funds.get("trailing_pe") and funds.get("forward_pe") and funds["trailing_pe"] > funds["forward_pe"]
        growth_pass = (funds.get("earnings_growth") or 0) > 0
        debt_pass = (funds.get("debt_to_equity") or 999) < 100

        stock_data.append({
            "ticker": symbol,
            "price": round(price, 2),
            "strategy": spread["strategy"],
            "pe_check": pe_pass,
            "growth_check": growth_pass,
            "debt_check": debt_pass,
        })

        spreads.append({
            "ticker": symbol,
            "strategy": spread["strategy"],
            "price": round(price, 2),
            "mcap": funds.get("market_cap"),
        })

    return stock_data, spreads

# ---------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers")
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else config.tickers

    logger.info(f"Starting run for {len(tickers)} tickers")

    stock_data, spreads = job(tickers)

    payload = {
        "generated_at_pt": dt_pacific.strftime("%m-%d-%Y %H:%M"),
        "all": stock_data,
    }

    for path in ["data/signals.json", "artifacts/data/signals.json"]:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    for path in ["data/spreads.json", "artifacts/data/spreads.json"]:
        with open(path, "w") as f:
            json.dump(spreads, f, indent=2)

    logger.info("Signal generation completed cleanly.")

if __name__ == "__main__":
    main()
