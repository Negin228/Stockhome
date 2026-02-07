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
import math
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
    if hasattr(x, "iloc"):
        return float(x.iloc[-1])
    return float(x)



# ---------------------------------------------------------
# PRICE FETCH (PRIORITY ORDER)
# ---------------------------------------------------------
def get_live_price(symbol, fallback_close, retries=2, wait=1):
    for attempt in range(retries):
        try:
            q = finnhub_client.quote(symbol)
            price = q.get("c")
            if price and price > 0:
                return float(price)
        except Exception:
            if attempt < retries - 1:
                time.sleep(wait)
                continue

    # fallback
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
COMPANY_CACHE_DIR = "data/company_names"
os.makedirs(COMPANY_CACHE_DIR, exist_ok=True)

def fetch_company_name_cached(symbol):
    path = os.path.join(COMPANY_CACHE_DIR, f"{symbol}.json")

    # Use cached value if < 24h old
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < 24 * 3600:
            with open(path, "r") as f:
                return json.load(f).get("name", "")

    try:
        info = yf.Ticker(symbol).info
        name = (
            info.get("shortName")
            or info.get("longName")
            or info.get("displayName")
            or ""
        )
        with open(path, "w") as f:
            json.dump({"name": name}, f)
        return name
    except Exception:
        return ""

def pct(a, b):
    if b == 0 or pd.isna(b) or pd.isna(a):
        return np.nan
    return (a - b) / b

def slope(series, lookback=10):
    s = series.dropna()
    if len(s) < lookback:
        return 0.0
    y = s.iloc[-lookback:].values
    x = np.arange(lookback)
    m = np.polyfit(x, y, 1)[0]
    return m

def score_trend(last_close, sma_fast_v, sma_slow_v, sma_slow_slope):
    reasons = []
    score = 0.0
    if last_close > sma_slow_v:
        score += 0.55; reasons.append("Above slow SMA")
    else:
        reasons.append("Below slow SMA")
    if last_close > sma_fast_v:
        score += 0.25; reasons.append("Above fast SMA")
    if sma_slow_slope > 0:
        score += 0.20; reasons.append("Uptrending")
    return clamp(score, 0, 1), reasons

def score_rsi(last_rsi):
    reasons = []
    score = 0.0
    if last_rsi >= 50:
        score += 0.60
    else:
        score += 0.35

    if last_rsi >= config.RSI_OVERBOUGHT:
        score -= 0.15; reasons.append("Overbought")
    elif last_rsi <= config.RSI_OVERSOLD:
        score += 0.15; reasons.append("Oversold")
    else:
        reasons.append(f"RSI {last_rsi:.0f}")
    return clamp(score, 0, 1), reasons

def score_macd(macd_val, signal_val, hist_series):
    reasons = []
    score = 0.0
    if macd_val > signal_val:
        score += 0.60; reasons.append("Bullish MACD")
    else:
        score += 0.35; reasons.append("Bearish MACD")

    h = hist_series.dropna()
    if len(h) >= 3:
        h0, h1, h2 = h.iloc[-1], h.iloc[-2], h.iloc[-3]
        if h0 > h1 > h2:
            score += 0.15; reasons.append("Mom. Rising")
        elif h0 < h1 < h2:
            score -= 0.10; reasons.append("Mom. Falling")
    return clamp(score, 0, 1), reasons

def score_distance(last_close, sma_slow_v):
    reasons = []
    d = pct(last_close, sma_slow_v)
    if pd.isna(d):
        return 0.5, []

    if -0.03 <= d <= 0.05:
        score = 0.85; reasons.append("Near Support")
    elif d > 0.05:
        score = 0.60; reasons.append(f"Extended (+{d*100:.0f}%)")
    else:
        score = 0.45
    return score, reasons

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
def fetch_cached_history(symbol, period="2y"):
    path = os.path.join(DATA_DIR, f"{symbol}.csv")

    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if len(df) >= 200:
            return df

    df = yf.download(symbol, period=period, progress=False)
    if not df.empty:
        df.to_csv(path)
    return df

def format_market_cap(mcap):
    if not mcap:
        return "N/A"
    if mcap >= 1e12:
        return f"{mcap/1e12:.2f}T"
    if mcap >= 1e9:
        return f"{mcap/1e9:.1f}B"
    if mcap >= 1e6:
        return f"{mcap/1e6:.1f}M"
    return str(mcap)

# ---------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------
def calculate_indicators(df):
    # --- Normalize columns to 1D Series ---
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
        high = df["High"].iloc[:, 0]
        low = df["Low"].iloc[:, 0]
    else:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]

    close = close.astype(float)
    high = high.astype(float)
    low = low.astype(float)

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # Moving averages
    df["dma200"] = close.rolling(200).mean()
    df["dma50"] = close.rolling(50).mean()

    # MACD
    macd = ta.trend.MACD(close=close)
    df["macd"] = macd.macd()
    df["signal_line"] = macd.macd_signal()
    df["hist"] = macd.macd_diff()

    # ADX
    adx = ta.trend.ADXIndicator(high=high, low=low, close=close)
    df["adx"] = adx.adx()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close=close)
    df["bb_low"] = bb.bollinger_lband()
    df["bb_high"] = bb.bollinger_hband()

    # Keltner Channels
    kc = ta.volatility.KeltnerChannel(high=high, low=low, close=close)
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
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_put_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Black-Scholes put delta (no dividends). Returns negative number (e.g., -0.25).
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return float("nan")
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1.0

def pick_expiration(expirations, min_dte=7, max_dte=45):
    """
    Choose the nearest expiration within [min_dte, max_dte] days.
    Falls back to the nearest future expiration if none in range.
    """
    if not expirations:
        return None

    today = dt_pacific.date()
    parsed = []
    for e in expirations:
        try:
            d = datetime.date.fromisoformat(e)
            dte = (d - today).days
            if dte > 0:
                parsed.append((dte, e))
        except Exception:
            continue

    if not parsed:
        return None

    # prefer within window
    in_window = [x for x in parsed if min_dte <= x[0] <= max_dte]
    if in_window:
        return sorted(in_window, key=lambda x: x[0])[0][1]

    # else nearest future
    return sorted(parsed, key=lambda x: x[0])[0][1]

def fetch_best_put_to_sell(symbol: str, spot: float,
                           target_delta_abs=0.25,
                           min_otm_pct=0.03,
                           r=0.05):
    """
    Returns a dict with strike/expiration/premium/delta%/premium%/metric_sum.
    Picks an OTM put below spot, near target delta, maximizing metric_sum.
    """
    try:
        t = yf.Ticker(symbol)
        exps = getattr(t, "options", None) or []
        exp = pick_expiration(exps, min_dte=7, max_dte=45)
        if not exp:
            return None

        chain = t.option_chain(exp)
        puts = chain.puts.copy()
        if puts.empty:
            return None

        # filter: OTM puts at least min_otm_pct below spot
        max_strike = spot * (1.0 - min_otm_pct)
        puts = puts[puts["strike"] <= max_strike].copy()
        if puts.empty:
            return None

        # premium: use mid if possible, else lastPrice
        bid = puts.get("bid")
        ask = puts.get("ask")
        if bid is not None and ask is not None:
            puts["premium"] = (puts["bid"].fillna(0) + puts["ask"].fillna(0)) / 2.0
            # if mid is 0 (missing bid/ask), fall back to lastPrice
            puts.loc[puts["premium"] <= 0, "premium"] = puts.loc[puts["premium"] <= 0, "lastPrice"].fillna(0)
        else:
            puts["premium"] = puts["lastPrice"].fillna(0)

        puts = puts[puts["premium"] > 0].copy()
        if puts.empty:
            return None

        # IV
        puts["iv"] = puts.get("impliedVolatility", np.nan).astype(float)

        # time to expiry in years
        exp_date = datetime.date.fromisoformat(exp)
        dte = (exp_date - dt_pacific.date()).days
        T = max(dte, 1) / 365.0

        # approximate delta
        deltas = []
        for _, row in puts.iterrows():
            K = float(row["strike"])
            sigma = float(row["iv"]) if not pd.isna(row["iv"]) else float("nan")
            d = bs_put_delta(spot, K, T, r, sigma) if not pd.isna(sigma) else float("nan")
            deltas.append(d)
        puts["delta"] = deltas

        # delta_abs: if delta is nan, drop it
        puts = puts.dropna(subset=["delta"]).copy()
        if puts.empty:
            return None

        puts["delta_abs"] = puts["delta"].abs()

        # metrics
        puts["delta_percent"] = puts["delta_abs"] * 100.0
        puts["premium_percent"] = (puts["premium"] / puts["strike"]) * 100.0

        # score: closer to target delta + higher premium%
        puts["delta_closeness"] = 1.0 - (puts["delta_abs"] - target_delta_abs).abs() / max(target_delta_abs, 1e-6)
        puts["delta_closeness"] = puts["delta_closeness"].clip(lower=0)

        puts["metric_sum"] = puts["premium_percent"] + puts["delta_percent"]

        # pick best: prioritize delta closeness then metric_sum
        puts = puts.sort_values(["delta_closeness", "metric_sum"], ascending=[False, False])

        best = puts.iloc[0]
        strike = float(best["strike"])
        premium = float(best["premium"])
        delta_percent = float(best["delta_percent"])
        premium_percent = float(best["premium_percent"])
        metric_sum = float(best["metric_sum"])

        # crude weekly/monthly flags (you can refine later)
        weekly_available = (dte <= 9)
        monthly_available = True

        return {
            "strike": round(strike, 2),
            "expiration": exp,
            "premium": round(premium, 2),
            "delta_percent": round(delta_percent, 1),
            "premium_percent": round(premium_percent, 1),
            "metric_sum": round(metric_sum, 1),
            "weekly_available": weekly_available,
            "monthly_available": monthly_available,
        }

    except Exception as e:
        logger.warning(f"Options fetch failed for {symbol}: {e}")
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
        strategy = spread["strategy"] if spread else None
        is_squeeze = spread["is_squeeze"] if spread else False

        company_name = fetch_company_name_cached(symbol)

        close_price = scalar(row["Close"])
        price = get_live_price(symbol, close_price)

        put_pick = fetch_best_put_to_sell(symbol, float(price))
        if put_pick is None:
            put_pick = {
                "strike": None,
                "expiration": None,
                "premium": None,
                "delta_percent": None,
                "premium_percent": None,
                "metric_sum": None,
                "weekly_available": True,
                "monthly_available": True,
            }


        "put": put_pick,

        # --- FUNDAMENTALS ---
        funds = fetch_fundamentals_cached(symbol) or {}
        trailing_pe = funds.get("trailing_pe")
        forward_pe = funds.get("forward_pe")
        earnings_growth = funds.get("earnings_growth")
        debt_to_equity = funds.get("debt_to_equity")
        market_cap = funds.get("market_cap")

        pe_pass = bool(trailing_pe and forward_pe and trailing_pe > forward_pe)
        growth_pass = bool((earnings_growth or 0) > 0)
        debt_pass = bool((debt_to_equity or 999) < 100)

        # --- INDICATOR SCALARS ---
        rsi_val = scalar(row["rsi"])
        dma50_val = scalar(row["dma50"])
        dma200_val = scalar(row["dma200"])

        macd_val = scalar(row["macd"])
        sig_val = scalar(row["signal_line"])  # requires calculate_indicators to write signal_line
        sma_slope = slope(df["dma200"], lookback=10)

        # --- SCORE (same logic as earlier code) ---
        s_trend, r_trend = score_trend(close_price, dma50_val, dma200_val, sma_slope)
        s_rsi, r_rsi = score_rsi(rsi_val)
        s_macd, r_macd = score_macd(macd_val, sig_val, df["hist"])
        s_dist, r_dist = score_distance(close_price, dma200_val)

        final_score = (W_TREND * s_trend) + (W_RSI * s_rsi) + (W_MACD * s_macd) + (W_DISTANCE * s_dist)
        final_score = clamp(final_score, 0, 100)
        if pd.isna(final_score):
            final_score = 0.0


        reasons = r_trend[:1] + r_rsi[:1] + r_macd[:1] + r_dist[:1]
        why_str = " • ".join(reasons) if reasons else "N/A"

        # --- PCT DROP (same idea as earlier code) ---
        prev_close = scalar(df.iloc[-2]["Close"]) if len(df) > 1 else None
        pct_drop = None
        if prev_close and price:
            pct_drop = (-(price - prev_close) / prev_close * 100)

        if pct_drop is not None and (pd.isna(pct_drop) or np.isinf(pct_drop)):
            pct_drop = None


        # IMPORTANT for filters.html:
        # score and price must be numeric (NOT tuples), and pe/market_cap should be numeric-safe for JS comparisons
        stock_data.append({
            "ticker": symbol,
            "company": company_name,

            "score": float(final_score),
            "why": why_str,

            "price": round(float(price), 2),
            "price_str": f"{price:.2f}",

            "rsi": round(float(rsi_val), 1),
            "rsi_str": f"{rsi_val:.1f}",

            # UI currently uses *_str for DMA values
            "dma50_str": f"{dma50_val:.1f}",
            "dma200_str": f"{dma200_val:.1f}",
            "dma50": float(dma50_val) if dma50_val is not None else None,
            "dma200": float(dma200_val) if dma200_val is not None else None,

            "trend_dir": "bullish" if macd_val > sig_val else "bearish",
            "trend_rationale": f"{'Strong' if scalar(row['adx']) > 25 else 'Weak/Sideways'} "
                               f"{'Bullish' if macd_val > sig_val else 'Bearish'} Trend (ADX: {scalar(row['adx']):.1f})",

                "put": {
                    "strike": None,
                    "expiration": None,
                    "premium": None,
                    "delta_percent": None,
                    "premium_percent": None,
                    "metric_sum": None,
                    "weekly_available": True,
                    "monthly_available": True,},


            # JS filter uses pe <= peLimit, so avoid null by defaulting high when missing
            "pe": float(trailing_pe) if trailing_pe is not None else 9999,
            "pe_str": f"{trailing_pe:.1f}" if trailing_pe is not None else "N/A",

            # JS filter uses market_cap >= cap, so avoid null by defaulting 0 when missing
            "market_cap": float(market_cap) if market_cap is not None else 0,
            "market_cap_str": format_market_cap(market_cap),

            "pct_drop": float(pct_drop) if pct_drop is not None else None,

            "strategy": strategy, 

            # replicate earlier extra fields
            "pe_check": bool(pe_pass),
            "growth_check": bool(growth_pass),
            "debt_check": bool(debt_pass),

            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "earnings_growth": earnings_growth,
            "earnings_growth_str": f"{(earnings_growth or 0) * 100:.1f}%",
            "debt_to_equity": debt_to_equity,
            "debt_to_equity_str": str(debt_to_equity) if debt_to_equity is not None else "N/A",
        })

        if spread and not is_squeeze:
            spreads.append({
                "ticker": symbol,
                "company": company_name,
                "strategy": spread["strategy"],
                "price": round(float(price), 2),
                "mcap": market_cap,
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
        "buys": stock_data,
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
