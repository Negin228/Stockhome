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

def fetch_puts(symbol):
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = dt_pacific.replace(tzinfo=None)  # match old behavior
        all_exps = getattr(ticker, "options", []) or []
        valid_dates = []
        for d in all_exps:
            try:
                if (parse(d) - today).days <= 49 and (parse(d) - today).days > 0:
                    valid_dates.append(d)
            except Exception:
                continue

        if not valid_dates:
            return []

        avail = option_availability(valid_dates)

        for exp in valid_dates:
            exp_type = option_expiration_type(exp)
            dte = (parse(exp).date() - today.date()).days

            chain = ticker.option_chain(exp)
            if chain.puts.empty:
                continue

            # underlying close (same idea as old)
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
            puts = chain.puts.copy()

            # distance to spot (old logic)
            puts["distance"] = (puts["strike"] - under_price).abs()

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
                    "dte": dte,
                    "premium": float(premium) if premium is not None and pd.notna(premium) else None,
                    "weekly_available": avail["weekly_available"],
                    "monthly_available": avail["monthly_available"],
                    "stock_price": float(under_price) if pd.notna(under_price) else None
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
            # exactly like old
            p["custom_metric"] = ((price - strike) + premium / 100) / price * 100 if strike else None
            p["delta_percent"] = ((price - strike) / price) * 100 if strike else None
            p["premium_percent"] = premium / price * 100 if premium else None
        except Exception:
            p["custom_metric"] = None
    return puts

def default_put_obj():
    return {
        "strike": None,
        "expiration": None,
        "premium": None,
        "delta_percent": None,
        "premium_percent": None,
        "metric_sum": None,
        "weekly_available": True,
        "monthly_available": True
    }

# ---------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------
def clamp(x, lo, hi): return max(lo, min(hi, x))

def scalar(x):
    if isinstance(x, pd.Series):
        return float(x.iloc[-1])  # safest for time series
    if hasattr(x, "iloc"):
        return float(x.iloc[0])   # for 1-cell objects
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

    # 1) Try cache
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            for c in ["Open","High","Low","Close","Adj Close","Volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            # Use cache if it looks usable
            if not df.empty and len(df) >= 200:
                return df
        except Exception as e:
            logger.warning(f"Cache read failed for {symbol}: {e}")

    # 2) Download fallback
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
    df["dma50"]  = close.rolling(50).mean()

    # MACD (same)
    macd = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["signal_line"] = macd.macd_signal()
    df["hist"] = macd.macd_diff()

    # ADX + DI (THIS is what you were missing vs old)
    dmi = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
    df["adx"] = dmi.adx()
    df["plus_di"] = dmi.adx_pos()
    df["minus_di"] = dmi.adx_neg()

    # Spread indicators (BB + KC)
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df["bb_low"] = bb.bollinger_lband()
    df["bb_high"] = bb.bollinger_hband()

    kc = ta.volatility.KeltnerChannel(high=high, low=low, close=close, window=20)
    df["kc_low"] = kc.keltner_channel_lband()
    df["kc_high"] = kc.keltner_channel_hband()

    return df


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
# MAIN JOB LOOP (SEQUENTIAL)
# ---------------------------------------------------------
def job(tickers):
    all_rows = []
    buy_rows = []
    spreads_rows = []

    for symbol in tickers:
        df = fetch_cached_history(symbol)
        if df.empty or len(df) < 200:
            continue

        df = calculate_indicators(df)
        row = df.iloc[-1]

        sig, sig_reason = generate_signal(df)

        spread = get_spread_strategy(row)
        strategy = spread["strategy"] if spread else None
        is_squeeze = spread["is_squeeze"] if spread else False

        company_name = fetch_company_name_cached(symbol)

        close_price = scalar(row["Close"])
        price = get_live_price(symbol, close_price)

        # trend label (DI-based)
        plus_di  = scalar(df["plus_di"].iloc[-1])
        minus_di = scalar(df["minus_di"].iloc[-1])
        adx_val  = scalar(df["adx"].iloc[-1])

        trend_direction = "Bullish" if plus_di > minus_di else "Bearish"
        trend_strength  = "Strong" if adx_val > 25 else "Weak/Sideways"
        trend_rationale = f"{trend_strength} {trend_direction} Trend (ADX: {adx_val:.1f})"
        trend_dir_val   = trend_direction.lower()

        # scoring stays same as you already have
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
            "signal": sig,  # IMPORTANT: restore
            "score": float(final_score),
            "why": why_str,
            "price": round(float(price), 2),
            "price_str": f"{price:.2f}",
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
            "market_cap": float(market_cap) if market_cap is not None else None,
            "market_cap_str": format_market_cap(market_cap),
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
        }

        all_rows.append(base_obj)

        # ONLY BUY rows get options (old behavior)
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

            buy_obj = dict(base_obj)
            buy_obj["put"] = put_obj
            buy_rows.append(buy_obj)

        # spreads.json should exclude squeeze (you wanted this only for spreads.html)
        if spread and not is_squeeze:
            spreads_rows.append({
                "ticker": symbol,
                "company": company_name,
                "strategy": spread["strategy"],
                "type": spread["type"],
                "is_squeeze": is_squeeze,
                "price": round(float(price), 2),
                "mcap": market_cap,
            })

    return buy_rows, all_rows, spreads_rows


# ---------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers")
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else config.tickers

    logger.info(f"Starting run for {len(tickers)} tickers")

    buy_rows, all_rows, spreads_rows = job(tickers)

    payload = {
        "generated_at_pt": dt_pacific.strftime("%m-%d-%Y %H:%M"),
        "buys": buy_rows,          # ✅ only RSI < oversold
        "sells": [],               # optional: keep for app.js safety
        "all": all_rows,
    }

# write signals.json + spreads.json like before


    for path in ["data/signals.json", "artifacts/data/signals.json"]:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    for path in ["data/spreads.json", "artifacts/data/spreads.json"]:
        with open(path, "w") as f:
            json.dump(spreads_rows, f, indent=2)


    logger.info("Signal generation completed cleanly.")

if __name__ == "__main__":
    main()
