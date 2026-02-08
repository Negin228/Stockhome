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
import config

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
W_TREND = 40
W_RSI = 25
W_MACD = 25
W_DISTANCE = 10

CACHE_FUNDAMENTALS_HOURS = 24
CACHE_OPTIONS_AVAIL_HOURS = 24

pacific = pytz.timezone("US/Pacific")
dt_pacific = datetime.datetime.now(pacific)

DATA_DIR = config.DATA_DIR
LOG_DIR = config.LOG_DIR
FUND_DIR = "data/fundamentals"
COMPANY_CACHE_DIR = "data/company_names"
OPTIONS_CACHE_DIR = "data/options_availability"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FUND_DIR, exist_ok=True)
os.makedirs(COMPANY_CACHE_DIR, exist_ok=True)
os.makedirs(OPTIONS_CACHE_DIR, exist_ok=True)
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
# BASIC HELPERS
# ---------------------------------------------------------
def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def scalar(x):
    if isinstance(x, pd.Series):
        return float(x.iloc[-1])
    if hasattr(x, "iloc"):
        return float(x.iloc[0])
    return float(x)

def normalize_tickers(x):
    """
    Accepts: list/tuple/set tickers OR comma-separated string.
    Returns: cleaned, unique, uppercase list.
    """
    if x is None:
        return []
    if isinstance(x, str):
        parts = x.split(",")
    else:
        parts = list(x)

    cleaned = []
    seen = set()
    for t in parts:
        t = str(t).strip().upper()
        if not t:
            continue
        if t not in seen:
            cleaned.append(t)
            seen.add(t)
    return cleaned

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
    return float(m)

def format_market_cap(mcap):
    try:
        if mcap is None:
            return ""
        m = float(mcap)
        if np.isnan(m) or m <= 0:
            return ""

        units = [
            (1e12, "T", 2),
            (1e9,  "B", 2),
            (1e6,  "M", 1),
            (1e3,  "K", 0),
        ]
        for div, suffix, decimals in units:
            if m >= div:
                return f"{m/div:,.{decimals}f}{suffix}"
        return f"{m:,.0f}"
    except Exception:
        return ""


# ---------------------------------------------------------
# OPTIONS HELPERS
# ---------------------------------------------------------
def option_expiration_type(expiration_str: str) -> str:
    try:
        d = parse(expiration_str).date()
        # If Saturday, treat as Friday
        if d.weekday() == 5:
            d = d - datetime.timedelta(days=1)
        # Monthly: 3rd Friday (15-21)
        if d.weekday() == 4 and 15 <= d.day <= 21:
            return "MONTHLY"
        return "WEEKLY"
    except Exception:
        return "UNKNOWN"

def option_availability(expiration_list):
    types = [option_expiration_type(e) for e in expiration_list]
    return {
        "weekly_available": any(t == "WEEKLY" for t in types),
        "monthly_available": any(t == "MONTHLY" for t in types),
    }

def fetch_options_availability_cached(symbol):
    """
    Cheap "does it have weekly/monthly expirations?" check for ANY ticker (including spreads).
    Cached for CACHE_OPTIONS_AVAIL_HOURS hours.
    """
    path = os.path.join(OPTIONS_CACHE_DIR, f"{symbol}.json")

    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < CACHE_OPTIONS_AVAIL_HOURS * 3600:
            try:
                with open(path, "r") as f:
                    d = json.load(f)
                    return {
                        "weekly_available": bool(d.get("weekly_available", False)),
                        "monthly_available": bool(d.get("monthly_available", False)),
                    }
            except Exception:
                pass

    out = {"weekly_available": False, "monthly_available": False}
    try:
        exps = yf.Ticker(symbol).options or []
        if exps:
            avail = option_availability(exps)
            out = {
                "weekly_available": bool(avail.get("weekly_available")),
                "monthly_available": bool(avail.get("monthly_available")),
            }
    except Exception as e:
        logger.warning(f"Options availability error for {symbol}: {e}")

    try:
        with open(path, "w") as f:
            json.dump(out, f)
    except Exception:
        pass

    return out

def default_put_obj():
    return {
        "strike": None,
        "expiration": None,
        "premium": None,
        "delta_percent": None,
        "premium_percent": None,
        "metric_sum": None,
        "weekly_available": True,
        "monthly_available": True,
        "exp_type": None,
    }

# ---------------------------------------------------------
# PRICE FETCH (PRIORITY ORDER)
# ---------------------------------------------------------
def get_live_price(symbol, fallback_close, retries=2, wait=1):
    # 1) Finnhub quote
    for attempt in range(retries):
        try:
            q = finnhub_client.quote(symbol)
            price = q.get("c")
            if price and price > 0:
                return float(price)
        except Exception:
            if attempt < retries - 1:
                time.sleep(wait)

    # 2) yfinance fast_info
    try:
        price = yf.Ticker(symbol).fast_info.get("lastPrice")
        if price and price > 0:
            return float(price)
    except Exception:
        pass

    # 3) fallback close
    try:
        return float(fallback_close)
    except Exception:
        return None


# ---------------------------------------------------------
# COMPANY NAME (CACHED)
# ---------------------------------------------------------
def fetch_company_name_cached(symbol):
    path = os.path.join(COMPANY_CACHE_DIR, f"{symbol}.json")

    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < 24 * 3600:
            try:
                with open(path, "r") as f:
                    return json.load(f).get("name", "")
            except Exception:
                pass

    try:
        info = yf.Ticker(symbol).info
        name = info.get("shortName") or info.get("longName") or info.get("displayName") or ""
        with open(path, "w") as f:
            json.dump({"name": name}, f)
        return name
    except Exception:
        return ""

# ---------------------------------------------------------
# FUNDAMENTALS (CACHED)
# ---------------------------------------------------------
def fetch_fundamentals_cached(symbol):
    path = os.path.join(FUND_DIR, f"{symbol}.json")

    # 1) Try to read cache
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < CACHE_FUNDAMENTALS_HOURS * 3600:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    # VALIDATION: Only return cache if it actually has data.
                    # If market_cap is missing/0, consider cache 'stale' and re-fetch.
                    if data.get("market_cap"): 
                        return data
            except Exception:
                pass

    # --- FETCH DATA ---
    trailing_pe = None
    forward_pe = None
    earnings_growth = None
    debt_to_equity = None
    market_cap = None

    # 1) yfinance (Try fast_info first for Market Cap - it is more reliable than .info)
    try:
        ticker = yf.Ticker(symbol)
        
        # Try fast_info for market cap (doesn't require full scrape)
        if hasattr(ticker, 'fast_info'):
            market_cap = ticker.fast_info.get('market_cap')
        
        # Try .info for the rest
        info = ticker.info or {}
        if not market_cap:
             market_cap = info.get("marketCap")
             
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        earnings_growth = info.get("earningsQuarterlyGrowth")
        debt_to_equity = info.get("debtToEquity")
        
    except Exception as e:
        logger.warning(f"Fundamentals error for {symbol}: {e}")

    # 2) Finnhub fallback
    if (market_cap is None or market_cap == 0) and FINNHUB_KEY:
        try:
            prof = finnhub_client.company_profile2(symbol=symbol) or {}
            mc_millions = prof.get("marketCapitalization")
            if mc_millions and mc_millions > 0:
                market_cap = float(mc_millions) * 1_000_000
        except Exception as e:
            logger.warning(f"Finnhub fallback error for {symbol}: {e}")

    data = {
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "earnings_growth": earnings_growth,
        "debt_to_equity": debt_to_equity,
        "market_cap": market_cap,
    }

    # Only save to cache if we actually got a market cap
    if market_cap and market_cap > 0:
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    return data
# ---------------------------------------------------------
# HISTORY CACHE
# ---------------------------------------------------------
def fetch_cached_history(symbol, period="2y"):
    path = os.path.join(DATA_DIR, f"{symbol}.csv")

    # 1) cache
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if not df.empty and len(df) >= 200:
                return df
        except Exception as e:
            logger.warning(f"Cache read failed for {symbol}: {e}")

    # 2) download
    df = yf.download(symbol, period=period, progress=False)
    if not df.empty:
        try:
            df.to_csv(path)
        except Exception:
            pass
    return df

# ---------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------
def calculate_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
        high = df["High"].iloc[:, 0]
        low  = df["Low"].iloc[:, 0]
    else:
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]

    close = close.astype(float)
    high  = high.astype(float)
    low   = low.astype(float)

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # MAs
    df["dma200"] = close.rolling(200).mean()
    df["dma50"] = close.rolling(50).mean()

    # MACD
    macd = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["signal_line"] = macd.macd_signal()
    df["hist"] = macd.macd_diff()

    # ADX + DI
    dmi = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
    df["adx"] = dmi.adx()
    df["plus_di"] = dmi.adx_pos()
    df["minus_di"] = dmi.adx_neg()

    # BB + KC (squeeze)
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df["bb_low"] = bb.bollinger_lband()
    df["bb_high"] = bb.bollinger_hband()

    kc = ta.volatility.KeltnerChannel(high=high, low=low, close=close, window=20)
    df["kc_low"] = kc.keltner_channel_lband()
    df["kc_high"] = kc.keltner_channel_hband()

    return df

# ---------------------------------------------------------
# SIGNAL + SCORING
# ---------------------------------------------------------
def generate_signal(df):
    if df.empty or "rsi" not in df.columns:
        return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None, ""
    if rsi < config.RSI_OVERSOLD:
        return "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
    if rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return None, ""

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
    score += 0.60 if last_rsi >= 50 else 0.35

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

# ---------------------------------------------------------
# SPREAD STRATEGY DETECTION
# ---------------------------------------------------------
def get_spread_strategy(row):
    p  = scalar(row["Close"])
    r  = scalar(row["rsi"])
    a  = scalar(row["adx"])
    bl = scalar(row["bb_low"])
    bu = scalar(row["bb_high"])
    kl = scalar(row["kc_low"])
    ku = scalar(row["kc_high"])

    # squeeze: BB inside KC
    is_sqz = not (bl < kl or bu > ku)

    # bullish mean reversion
    if p <= bl and r < 40 and a < 35:
        strat = "Bull Call (Debit)" if r < 30 else "Bull Put (Credit)"
        return {"strategy": strat, "type": "bullish", "is_squeeze": is_sqz}

    # bearish mean reversion
    if p >= bu and r > 60 and a < 35:
        strat = "Bear Put (Debit)" if r > 70 else "Bear Call (Credit)"
        return {"strategy": strat, "type": "bearish", "is_squeeze": is_sqz}

    return None

# ---------------------------------------------------------
# PUTS (ONLY FOR BUY SIGNALS)
# ---------------------------------------------------------
def fetch_puts(symbol):
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = dt_pacific.replace(tzinfo=None)  # match old behavior

        all_exps = getattr(ticker, "options", []) or []
        valid_dates = []
        for d in all_exps:
            try:
                days = (parse(d) - today).days
                if 0 < days <= 49:
                    valid_dates.append(d)
            except Exception:
                continue

        if not valid_dates:
            return []

        avail = option_availability(valid_dates)

        # underlying close once per symbol
        try:
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
        except Exception:
            under_price = None

        for exp in valid_dates:
            exp_type = option_expiration_type(exp)
            dte = (parse(exp).date() - today.date()).days

            chain = ticker.option_chain(exp)
            if chain.puts.empty:
                continue

            puts = chain.puts.copy()

            if under_price is not None and pd.notna(under_price):
                puts["distance"] = (puts["strike"] - under_price).abs()
            else:
                puts["distance"] = np.nan

            for _, put in puts.iterrows():
                strike = put.get("strike")
                bid = put.get("bid")
                ask = put.get("ask")
                last = put.get("lastPrice")

                premium = None
                try:
                    if pd.notna(bid) and pd.notna(ask) and (bid + ask) > 0:
                        premium = (bid + ask) / 2
                    else:
                        premium = last
                except Exception:
                    premium = last

                puts_data.append({
                    "expiration": exp,
                    "strike": float(strike) if pd.notna(strike) else None,
                    "exp_type": exp_type,
                    "dte": int(dte),
                    "premium": float(premium) if premium is not None and pd.notna(premium) else None,
                    "weekly_available": bool(avail["weekly_available"]),
                    "monthly_available": bool(avail["monthly_available"]),
                    "stock_price": float(under_price) if under_price is not None and pd.notna(under_price) else None
                })
    except Exception as e:
        logger.warning(f"Failed to fetch puts for {symbol}: {e}")
    return puts_data

def calculate_custom_metrics(puts, price):
    if not price or price <= 0:
        return puts
    for p in puts:
        strike = p.get("strike")
        premium = p.get("premium") or 0.0
        try:
            p["custom_metric"] = ((price - strike) + premium / 100) / price * 100 if strike else None
            p["delta_percent"] = ((price - strike) / price) * 100 if strike else None
            p["premium_percent"] = premium / price * 100 if premium else None
        except Exception:
            p["custom_metric"] = None
            p["delta_percent"] = None
            p["premium_percent"] = None
    return puts

# ---------------------------------------------------------
# MAIN JOB LOOP
# ---------------------------------------------------------
def job(tickers, prev_tickers=None):
    all_rows = []
    buy_rows = []
    spreads_rows = []

    for symbol in tickers:
        symbol = str(symbol).strip().upper()
        if not symbol:
            continue

        logger.info(f"Processing {symbol}...")

        try:
            df = fetch_cached_history(symbol)
            if df.empty or len(df) < 200:
                logger.warning(f"Skipping {symbol}: insufficient history (rows={len(df)})")
                continue

            df = calculate_indicators(df)
            row = df.iloc[-1]

            sig, _sig_reason = generate_signal(df)

            spread = get_spread_strategy(row)
            strategy = spread["strategy"] if spread else None
            is_squeeze = spread["is_squeeze"] if spread else False

            company_name = fetch_company_name_cached(symbol)

            close_price = scalar(row["Close"])
            price = get_live_price(symbol, close_price)

            # options availability (for ALL, including spreads)
            opts_avail = fetch_options_availability_cached(symbol)
            weekly_avail = bool(opts_avail.get("weekly_available"))
            monthly_avail = bool(opts_avail.get("monthly_available"))

            # DI-based trend label
            plus_di  = scalar(df["plus_di"].iloc[-1])
            minus_di = scalar(df["minus_di"].iloc[-1])
            adx_val  = scalar(df["adx"].iloc[-1])

            trend_direction = "Bullish" if plus_di > minus_di else "Bearish"
            trend_strength  = "Strong" if adx_val > 25 else "Weak/Sideways"
            trend_rationale = f"{trend_strength} {trend_direction} Trend (ADX: {adx_val:.1f})"
            trend_dir_val   = trend_direction.lower()

            # scoring
            rsi_val = scalar(row["rsi"])
            dma50_val = scalar(row["dma50"])
            dma200_val = scalar(row["dma200"])
            macd_val = scalar(row["macd"])
            sig_val = scalar(row["signal_line"])
            sma_slope = slope(df["dma200"], lookback=10)

            s_trend, r_trend = score_trend(close_price, dma50_val, dma200_val, sma_slope)
            s_rsi, r_rsi = score_rsi(rsi_val)
            s_macd, r_macd = score_macd(macd_val, sig_val, df["hist"])
            s_dist, r_dist = score_distance(close_price, dma200_val)

            final_score = clamp((W_TREND*s_trend) + (W_RSI*s_rsi) + (W_MACD*s_macd) + (W_DISTANCE*s_dist), 0, 100)
            reasons = r_trend[:1] + r_rsi[:1] + r_macd[:1] + r_dist[:1]
            why_str = " • ".join(reasons) if reasons else "N/A"

            # fundamentals
            funds = fetch_fundamentals_cached(symbol) or {}
            trailing_pe = funds.get("trailing_pe")
            forward_pe  = funds.get("forward_pe")
            earnings_growth = funds.get("earnings_growth")
            debt_to_equity  = funds.get("debt_to_equity")
            market_cap      = funds.get("market_cap")

            pe_pass = bool(trailing_pe and forward_pe and trailing_pe > forward_pe)
            growth_pass = bool((earnings_growth or 0) > 0)
            debt_pass = bool((debt_to_equity or 999) < 100)

            base_obj = {
                "ticker": symbol,
                "company": company_name,
                "signal": sig,
                "score": float(final_score),
                "why": why_str,
                "price": round(float(price), 2),
                "price_str": f"{price:.2f}" if price is not None else "N/A",
                "rsi": round(float(rsi_val), 1),
                "rsi_str": f"{rsi_val:.1f}",
                "dma50": float(dma50_val),
                "dma200": float(dma200_val),
                "dma50_str": f"{dma50_val:.1f}",
                "dma200_str": f"{dma200_val:.1f}",
                "trend_dir": trend_dir_val,
                "trend_rationale": trend_rationale,
                "pe": float(trailing_pe) if trailing_pe is not None else None,
                "pe_str": f"{trailing_pe:.1f}" if trailing_pe is not None else "N/A",
                "market_cap": float(market_cap) if market_cap is not None else 0.0,
                "market_cap_str": (format_market_cap(market_cap) or "0"),
                "strategy": strategy,
                "pe_check": bool(pe_pass),
                "growth_check": bool(growth_pass),
                "debt_check": bool(debt_pass),
                "trailing_pe": trailing_pe,
                "forward_pe": forward_pe,
                "earnings_growth": earnings_growth,
                "earnings_growth_str": f"{(earnings_growth or 0) * 100:.1f}%",
                "debt_to_equity": debt_to_equity,
                "debt_to_equity_str": str(debt_to_equity) if debt_to_equity is not None else "N/A",
                # NEW: options flags everywhere
                "weekly_available": weekly_avail,
                "monthly_available": monthly_avail,
            }

            all_rows.append(base_obj)

            # BUY: compute best put suggestion
            if sig == "BUY":
                puts_list = fetch_puts(symbol)
                puts_list = calculate_custom_metrics(puts_list, float(price))

                filtered = [
                    p for p in puts_list
                    if p.get("strike") and price and p["strike"] < price and (p.get("custom_metric") or 0) >= 10
                ]

                if filtered:
                    best_put = max(filtered, key=lambda x: (x.get("premium_percent") or 0, x.get("premium") or 0))
                    expiration_fmt = datetime.datetime.strptime(best_put["expiration"], "%Y-%m-%d").strftime("%b %d, %Y")
                    put_obj = {
                        "strike": float(best_put["strike"]),
                        "expiration": expiration_fmt,
                        "exp_type": best_put.get("exp_type", "UNKNOWN"),
                        "weekly_available": bool(best_put.get("weekly_available")),
                        "monthly_available": bool(best_put.get("monthly_available")),
                        "premium": float(best_put["premium"]),
                        "delta_percent": float(best_put["delta_percent"]),
                        "premium_percent": float(best_put["premium_percent"]),
                        "metric_sum": float(best_put["delta_percent"] or 0) + float(best_put["premium_percent"] or 0),
                    }
                else:
                    put_obj = default_put_obj()
                    put_obj["weekly_available"] = weekly_avail
                    put_obj["monthly_available"] = monthly_avail

                buy_obj = dict(base_obj)
                buy_obj["put"] = put_obj
                buy_rows.append(buy_obj)

            # spreads.json excludes squeeze (per your rule)
            if spread and not is_squeeze:
                if prev_tickers is None:
                    prev_tickers = set()
                spreads_rows.append({
                    "ticker": symbol,
                    "company": company_name,
                    "strategy": spread["strategy"],
                    "type": spread["type"],
                    "is_squeeze": is_squeeze,
                    "price": round(float(price), 2),
                    "market_cap": float(market_cap) if market_cap is not None else 0.0,
                    "market_cap_str": (format_market_cap(market_cap) or "0"),
        
                    "pe_check": bool(pe_pass),
                    "growth_check": bool(growth_pass),
                    "debt_check": bool(debt_pass),
                    "trailing_pe": trailing_pe,
                    "forward_pe": forward_pe,
                    "earnings_growth": earnings_growth,
                    "debt_to_equity": debt_to_equity,

                    "weekly_available": weekly_avail,
                    "monthly_available": monthly_avail,
                    "is_new": symbol not in prev_tickers,})
                spreads_rows.append({
                    "ticker": symbol,
                    "company": company_name,
                    "strategy": spread["strategy"],
                    "type": spread["type"],
                    "is_squeeze": is_squeeze,
                    "price": round(float(price), 2),
                    "market_cap": float(market_cap) if market_cap is not None else 0.0,
                    "market_cap_str": (format_market_cap(market_cap) or "0"),

                    # NEW: show options flags on spread stocks
                    "weekly_available": weekly_avail,
                    "monthly_available": monthly_avail,
                })

        except Exception as e:
            logger.exception(f"Error processing {symbol}: {e}")
            continue

    logger.info(f"Finished loop. all={len(all_rows)} buys={len(buy_rows)} spreads={len(spreads_rows)}")
    return buy_rows, all_rows, spreads_rows

# ---------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. AAPL,MSFT,TSLA")
    args = parser.parse_args()

    raw = args.tickers if args.tickers else config.tickers
    tickers = normalize_tickers(raw)
    logger.info(f"Starting run for {len(tickers)} tickers: {tickers[:10]}{'...' if len(tickers) > 10 else ''}")

    prev_tickers = set()
    spreads_path = "data/spreads.json"
    if os.path.exists(spreads_path):
        try:
            with open(spreads_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                if isinstance(old_data, list):
                    prev_tickers = {item.get('ticker') for item in old_data if item.get('ticker')}
            logger.info(f"Loaded {len(prev_tickers)} previous tickers for 'NEW' badge check.")
        except Exception as e:
            logger.warning(f"Could not load previous spreads for comparison: {e}")

    buy_rows, all_rows, spreads_rows = job(tickers)

    logger.info(f"Starting run for {len(tickers)} tickers: {tickers[:10]}{'...' if len(tickers) > 10 else ''}")

    buy_rows, all_rows, spreads_rows = job(tickers, prev_tickers)
    
    payload = {
        "generated_at_pt": dt_pacific.strftime("%m-%d-%Y %H:%M"),
        "buys": buy_rows,
        "sells": [],
        "all": all_rows,
    }

    for path in ["data/signals.json", "artifacts/data/signals.json"]:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    for path in ["data/spreads.json", "artifacts/data/spreads.json"]:
        with open(path, "w") as f:
            json.dump(spreads_rows, f, indent=2)

    logger.info("Signal generation completed cleanly.")

if __name__ == "__main__":
    main()
