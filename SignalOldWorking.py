import os
import datetime
import json
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
from news_fetcher import fetch_news_ticker
import re
import pytz

# ---------------------------------------------------------
# SCORING CONFIGURATION
# ---------------------------------------------------------
W_TREND = 40
W_RSI = 25
W_MACD = 25
W_DISTANCE = 10

# ---------------------------------------------------------
# SETUP & LOGGING
# ---------------------------------------------------------
pacific = pytz.timezone('US/Pacific')
dt_pacific = datetime.datetime.now(pacific)

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
tickers = config.tickers
finnhub_client = finnhub.Client(api_key=API_KEY)

MAX_API_RETRIES = 5
API_RETRY_INITIAL_WAIT = 60
MAX_TICKER_RETRIES = 100
TICKER_RETRY_WAIT = 60

# ---------------------------------------------------------
# HELPER FUNCTIONS (MATH & SCORING)
# ---------------------------------------------------------
def clamp(x, lo, hi):
    return max(lo, min(hi, x))

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

def scalar(x):
    if hasattr(x, "iloc"):
        return float(x.iloc[0])
    return float(x)

# --- SCORING LOGIC ---
def score_trend(last_close, sma_fast_v, sma_slow_v, sma_slow_slope):
    reasons = []
    score = 0.0
    # Above Slow SMA
    if last_close > sma_slow_v:
        score += 0.55; reasons.append("Above slow SMA")
    else: 
        reasons.append("Below slow SMA")
    
    # Above Fast SMA
    if last_close > sma_fast_v:
        score += 0.25; reasons.append("Above fast SMA")
    
    # Slope
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

def score_macd(macd_val, signal_val, hist):
    reasons = []
    score = 0.0
    if macd_val > signal_val:
        score += 0.60; reasons.append("Bullish MACD")
    else:
        score += 0.35; reasons.append("Bearish MACD")
        
    h = hist.dropna()
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
    if pd.isna(d): return 0.5, []
    
    if -0.03 <= d <= 0.05:
        score = 0.85; reasons.append("Near Support")
    elif d > 0.05:
        score = 0.60; reasons.append(f"Extended (+{d*100:.0f}%)")
    else:
        score = 0.45
        
    return score, reasons

# ---------------------------------------------------------
# CORE FUNCTIONS
# ---------------------------------------------------------

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

def has_weekly_options(expirations):
    types = [option_expiration_type(e) for e in expirations]
    return any(t == "WEEKLY" for t in types)

def option_availability(expiration_list):
    types = [option_expiration_type(e) for e in expiration_list]
    return {
        "weekly_available": any(t == "WEEKLY" for t in types),
        "monthly_available": any(t == "MONTHLY" for t in types),
    }

def force_float(val):
    if isinstance(val, (pd.Series, np.ndarray)):
        return float(val.iloc[-1]) if hasattr(val, "iloc") and not val.empty else None
    if isinstance(val, pd.DataFrame):
        return float(val.values[-1][0])
    return float(val) if val is not None else None

def option_expiration_type(expiration_str: str) -> str:
    try:
        d = parse(expiration_str).date()
        if d.weekday() == 5: d = d - datetime.timedelta(days=1)
        if d.weekday() == 4 and 15 <= d.day <= 21: return "MONTHLY"
        return "WEEKLY"
    except Exception:
        return "UNKNOWN"

def ensure_sentence_completion(text):
    text = text.strip()
    if not text: return ""
    if not re.search(r'[.!?]$', text): text += "."
    return text

@retry_on_rate_limit
def fetch_cached_history(symbol, period="2y", interval="1d"):
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
                cols = ['Date', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
                df = pd.read_csv(path, skiprows=3, names=cols)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df.set_index('Date', inplace=True)
                if df.index.hasnans: force_full = True
            except Exception as e:
                df = None
    
    if df is None or df.empty or force_full:
        logger.info(f"Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty: return pd.DataFrame()
        df.to_csv(path)
    else:
        try:
            last = pd.to_datetime(df.index[-1])
            start_date = (last - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
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
    if price is None or (isinstance(price, float) and np.isnan(price)): return None
    return price

def fetch_company_name(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("shortName") or info.get("longName") or ""
    except Exception: return ""

def calculate_indicators(df):
    if df is None or df.empty or len(df) < 14:
        logger.warning("Not enough data to calculate indicators.")
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
        high = df["High"].iloc[:, 0]
        low = df["Low"].iloc[:, 0]
    else:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]

    close = pd.Series(close).dropna()
    high = pd.Series(high).dropna()
    low = pd.Series(low).dropna()

    # RSI & Moving Averages
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    df["dma50"] = close.rolling(50).mean()

    # ADX
    dmi_orig = ta.trend.ADXIndicator(high, low, close, window=14)
    df["adx"] = dmi_orig.adx()
    df["plus_di"] = dmi_orig.adx_pos()
    df["minus_di"] = dmi_orig.adx_neg()

    # --- MACD CALCULATION (Missing Piece) ---
    macd_ind = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd_ind.macd()
    df["signal_line"] = macd_ind.macd_signal()
    df["hist"] = macd_ind.macd_diff()  # This creates the missing 'hist' column

    return df
    
def calculate_spread_indicators(df):
    """Calculates Bollinger Bands and Keltner Channels for Mean Reversion."""
    close = df["Close"].squeeze()
    
    # Bollinger Bands (20, 2)
    indicator_bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df["bb_high"] = indicator_bb.bollinger_hband()
    df["bb_low"] = indicator_bb.bollinger_lband()
    df["bb_mid"] = indicator_bb.bollinger_mavg()
    
    # Keltner Channels (20, 2) - Using ATR for the bands
    indicator_kc = ta.volatility.KeltnerChannel(high=df["High"].squeeze(), low=df["Low"].squeeze(), close=close, window=20)
    df["kc_high"] = indicator_kc.keltner_channel_hband()
    df["kc_low"] = indicator_kc.keltner_channel_lband()
    
    return df

def get_spread_strategy(row):
    """Determines the strategy and rationale based on Nishant Pant's rules."""
    # Ensure we are using scalar (single) values to avoid the 'ambiguous Series' error
    p = scalar(row['Close'])
    r = scalar(row['rsi'])
    a = scalar(row['adx'])
    bl = scalar(row['bb_low'])
    bu = scalar(row['bb_high'])
    kl = scalar(row['kc_low'])
    ku = scalar(row['kc_high'])
    
    # Squeeze Check: Bollinger Bands are inside Keltner Channels
    is_sqz = not (bl < kl or bu > ku)
    
    # Conditions: Price touch, RSI exhaustion, and Weak Trend (ADX < 35)
    if p <= bl and r < 40 and a < 35:
        strat = "Bull Call (Debit)" if r < 30 else "Bull Put (Credit)"
        return {"strategy": strat, "type": "bullish", "is_squeeze": is_sqz}
    
    elif p >= bu and r > 60 and a < 35:
        strat = "Bear Put (Debit)" if r > 70 else "Bear Call (Credit)"
        return {"strategy": strat, "type": "bearish", "is_squeeze": is_sqz}
    
    return None

def generate_signal(df):
    if df.empty or "rsi" not in df.columns: return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi): return None, ""
    
    if rsi < config.RSI_OVERSOLD:
        return "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
    if rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return None, ""

def fetch_fundamentals_safe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception: return None, None

def fetch_fundamentals_extended(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # 1. P/E vs Historical: We get Trailing P/E and estimate the 5y Avg
        trailing_pe = info.get("trailingPE", None)
        # Note: yfinance doesn't provide 5y avg directly; common proxy is price / 5y avg EPS
        # For simplicity in a dashboard, comparing Trailing vs Forward P/E is often used.
        forward_pe = info.get("forwardPE", None)

        # 2. Earnings Growth (Quarterly yoy)
        earnings_growth = info.get("earningsQuarterlyGrowth", None) # Expressed as a decimal (e.g., 0.15 = 15%)

        # 3. Debt-to-Equity Ratio
        debt_to_equity = info.get("debtToEquity", None) # Expressed as a percentage (e.g., 50.0 = 50%)

        return {
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "earnings_growth": earnings_growth,
            "debt_to_equity": debt_to_equity,
            "market_cap": info.get("marketCap", None)
        }
    except Exception as e:
        logger.error(f"Error fetching extended fundamentals for {symbol}: {e}")
        return None

def default_put_obj():
    return { "strike": None, "expiration": None, "premium": None, "delta_percent": None, "premium_percent": None, "metric_sum": None, "weekly_available": True, "monthly_available": True }

def fetch_puts(symbol):
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        valid_dates = [d for d in getattr(ticker, 'options', []) if (parse(d) - today).days <= 49]
        avail = option_availability(valid_dates)

        for exp in valid_dates:
            exp_type = option_expiration_type(exp)
            dte = (parse(exp).date() - today.date()).days
            chain = ticker.option_chain(exp)
            if chain.puts.empty: continue
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
            chain.puts["distance"] = abs(chain.puts["strike"] - under_price)
            for _, put in chain.puts.iterrows():
                strike = put["strike"]
                premium = put.get("lastPrice") or ((put.get("bid") + put.get("ask")) / 2)
                puts_data.append({
                    "expiration": exp, "strike": strike, "exp_type": exp_type, "dte": dte, "premium": premium,
                    "weekly_available": avail["weekly_available"], "monthly_available": avail["monthly_available"],
                    "stock_price": under_price
                })
    except Exception as e:
        logger.warning(f"Failed to fetch puts for {symbol}: {e}")
    return puts_data

def format_buy_alert_line(ticker, company_name, price, rsi, pe, mcap, strike, expiration, premium, delta_percent, premium_percent, dma200, dma50):
    price_str = f"{price:.2f}" if price is not None else "N/A"
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    pe_str = f"{pe:.1f}" if pe is not None else "N/A"
    dma200_str = f"{dma200:.1f}" if dma200 is not None else "N/A"
    dma50_str = f"{dma50:.1f}" if dma50 is not None else "N/A"
    strike_str = f"{strike:.1f}" if strike is not None else "N/A"
    premium_str = f"{premium:.2f}" if premium is not None else "N/A"
    dp = f"{delta_percent:.1f}%" if delta_percent is not None else "N/A"
    pp = f"{premium_percent:.1f}%" if premium_percent is not None else "N/A"
    metric_sum = (delta_percent + premium_percent) if (delta_percent and premium_percent) else None
    metric_sum_str = f"{metric_sum:.1f}%" if metric_sum else "N/A"
    return f"{ticker} ({company_name}) (${price_str}) | RSI={rsi_str} P/E={pe_str} Market Cap=${mcap}<br>DMA 200={dma200_str} DMA 50={dma50_str}<br>Sell a ${strike_str} put option with {expiration} expiration for a premium of ${premium_str}<br>[𝚫 {dp} + 💎 {pp}] = {metric_sum_str}"

def format_sell_alert_line(ticker, price, rsi, pe, mcap):
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    pe_str = f"{pe:.1f}" if pe is not None else "N/A"
    return f"RSI={rsi_str}, P/E={pe_str}, Market Cap=${mcap}"

def calculate_custom_metrics(puts, price):
    if not price or price <= 0: return puts
    for p in puts:
        strike = p.get("strike")
        premium = p.get("premium") or 0.0
        try:
            p["custom_metric"] = ((price - strike) + premium / 100) / price * 100 if strike else None
            p["delta_percent"] = ((price - strike) / price) * 100 if strike else None
            p["premium_percent"] = premium / price * 100 if premium else None
        except Exception:
            p["custom_metric"] = None
    return puts

def format_market_cap(mcap):
    if not mcap: return "N/A"
    if mcap >= 1e9: return f"{mcap / 1e9:.1f}B"
    if mcap >= 1e6: return f"{mcap / 1e6:.1f}M"
    return str(mcap)

def log_alert(alert):
    csv_path = config.ALERTS_CSV
    exists = os.path.exists(csv_path)
    df_new = pd.DataFrame([alert])
    df_new.to_csv(csv_path, mode='a', header=not exists, index=False)

def job(tickers):
    sell_alerts = []
    all_sell_alerts = []
    buy_symbols = []
    buy_alerts_web = []
    prices = {}
    rsi_vals = {}
    failed = []
    total = skipped = 0
    stock_data_list = []
    spread_results = []

    for symbol in tickers:
        total += 1
        try:
            hist = fetch_cached_history(symbol)
            # Ensure we have at least 200 rows to calculate the DMA 200 accurately
            if hist.empty or "Close" not in hist.columns or len(hist) < 200:
                logger.info(f"Insufficient history for {symbol} (need 200+ days), skipping.")
                skipped += 1; continue
        except Exception as e:
            failed.append(symbol); continue
            
        # 1. Indicators
        hist = calculate_indicators(hist)
        hist = calculate_spread_indicators(hist) 
        
        # 2. Basic Signal (Buy/Sell) for Puts logic
        sig, reason = generate_signal(hist)

        # 3. ADVANCED SCORING & TREND (Consolidated Logic)
        trend_rationale = "Trend data unavailable"
        trend_dir_val = "neutral"
        final_score = 0.0
        why_str = "N/A"

        try:
            # Extract scalar values for scoring
            last_close = scalar(hist["Close"].iloc[-1])
            last_rsi = scalar(hist["rsi"].iloc[-1])
            last_sma_slow = scalar(hist["dma200"].iloc[-1]) if "dma200" in hist.columns else np.nan
            last_sma_fast = scalar(hist["dma50"].iloc[-1]) if "dma50" in hist.columns else np.nan
            last_macd = scalar(hist["macd"].iloc[-1]) if "macd" in hist.columns else 0
            last_sig = scalar(hist["signal_line"].iloc[-1]) if "signal_line" in hist.columns else 0
            last_adx = scalar(hist["adx"].iloc[-1]) if "adx" in hist.columns else 0
            sma_slope = slope(hist["dma200"], lookback=10)

            # Trend Direction and Strength logic using pre-calculated DI lines
            plus_di = scalar(hist["plus_di"].iloc[-1])
            minus_di = scalar(hist["minus_di"].iloc[-1])
    
            trend_direction = "Bullish" if plus_di > minus_di else "Bearish"
            trend_strength = "Strong" if last_adx > 25 else "Weak/Sideways"
            trend_rationale = f"{trend_strength} {trend_direction} Trend (ADX: {last_adx:.1f})"
            trend_dir_val = trend_direction.lower()

            # Sub-scores
            s_trend, r_trend = score_trend(last_close, last_sma_fast, last_sma_slow, sma_slope)
            s_rsi, r_rsi = score_rsi(last_rsi)
            s_macd, r_macd = score_macd(last_macd, last_sig, hist["hist"])
            s_dist, r_dist = score_distance(last_close, last_sma_slow)
            
            # Final Score (0-100)
            final_score = (W_TREND * s_trend) + (W_RSI * s_rsi) + (W_MACD * s_macd) + (W_DISTANCE * s_dist)
            final_score = clamp(final_score, 0, 100)
            
            # Why String
            reasons = r_trend[:1] + r_rsi[:1] + r_macd[:1] + r_dist[:1]
            why_str = " • ".join(reasons)
        except Exception as e:
            logger.error(f"Scoring/Trend error for {symbol}: {e}")

        # 4. Price & Fundamentals
        try:
            # Try the primary Live API
            rt_price = fetch_quote(symbol)
            rt_price = force_float(rt_price)
            
            # Fallback 1: Use yfinance fast_info (Live market data)
            if rt_price is None or (isinstance(rt_price, float) and (np.isnan(rt_price) or rt_price <= 0)):
                rt_price = yf.Ticker(symbol).fast_info['lastPrice']
        except Exception as e:
            # Fallback 2: Final safety check using the last close from your history CSV
            logger.warning(f"Live price failed for {symbol}, using CSV fallback: {e}")
            rt_price = force_float(hist["Close"].iloc[-1])

        # Final Critical Safety Check: If still None, skip this ticker to avoid math errors
        if rt_price is None or rt_price <= 0:
            logger.error(f"Skipping {symbol}: No valid price found after all fallbacks.")
            failed.append(symbol)
            continue


        funds = fetch_fundamentals_extended(symbol)
        if not funds:
             funds = {
                 "trailing_pe": None, "forward_pe": None, 
                 "earnings_growth": None, "debt_to_equity": None, 
                 "market_cap": None
             }
        pe = funds['trailing_pe']
        mcap = funds['market_cap']

        company_name = fetch_company_name(symbol)
        cap_str = format_market_cap(mcap)
        rsi_val = hist["rsi"].iloc[-1]
        
        dma200_val = hist["dma200"].iloc[-1]
        dma50_val = hist["dma50"].iloc[-1]
        prev_close_val = hist["Close"].iloc[-2].item() if len(hist) > 1 else None


        
        pct_drop = None
        if prev_close_val and rt_price:
            pct_drop = (-(rt_price - prev_close_val) / prev_close_val * 100)

        try:
            stock_row = next((s for s in stock_data_list if s["ticker"] == symbol), None)
            current_row = hist.iloc[-1]
            spread_data = get_spread_strategy(current_row)
            
            # 1. Only proceed if we have a strategy AND it's not a squeeze
            if spread_data and not spread_data['is_squeeze']:
                r = scalar(current_row['rsi'])
                a = scalar(current_row['adx'])
                bl = scalar(current_row['bb_low'])
                bu = scalar(current_row['bb_high'])
                
                band_type = "BBL" if spread_data['type'] == 'bullish' else "BBU"
                band_val = bl if spread_data['type'] == 'bullish' else bu
                rationale = "Extreme: Buying Delta for sharp snap-back." if spread_data['strategy'].endswith("(Debit)") else "Moderate: Selling Theta."
                
                full_reasoning = f"Det: Price {'<' if spread_data['type'] == 'bullish' else '>'} {band_type}({band_val:.2f}) | ADX: {a:.1f} | RSI {r:.1f} ({rationale})"
                
                spread_results.append({
                    'ticker': symbol, 
                    'company': company_name,
                    'mcap': round((mcap / 1e9), 2) if mcap else 0,
                    'strategy': spread_data['strategy'], 
                    'price': round(float(rt_price), 2),
                    'rsi': round(float(rsi_val), 1), 
                    'adx': round(float(a), 1),
                    'health': funds['debt_to_equity'],                    
                    'type': spread_data['type'], 
                    'is_squeeze': spread_data['is_squeeze'],
                    'reasoning': full_reasoning,

                })
            
            # 2. Log the ignored tickers so you know the script is working
            elif spread_data and spread_data['is_squeeze']:
                logger.info(f"Skipping {symbol}: Bollinger Bands squeezed inside Keltner Channels.")
                
        except Exception as e:
            logger.error(f"Spread calculation error for {symbol}: {e}")

        pe_pass = False
        growth_pass = False
        debt_pass = False
        if funds.get('trailing_pe') and funds.get('forward_pe'):
            pe_pass = funds['trailing_pe'] > funds['forward_pe']
            growth_pass = (funds.get('earnings_growth') or 0) > 0
            debt_pass = (funds.get('debt_to_equity') or 999) < 100

            # 2. Earnings Growth (Checking for positive YoY growth)
            growth_pass = (funds['earnings_growth'] or 0) > 0

            # 3. Debt-to-Equity (Using your < 1% or 100 threshold)
            # Note: info.get("debtToEquity") returns values like 50.0 for 50%. 
            # For < 1%, the value would be < 1.0.
            debt_pass = (funds['debt_to_equity'] or 999) < 100
    

        # 5. Build Stock Object
        stock_data_list.append({
            'ticker': symbol, 'company': company_name, 'signal' : sig,
            'score': final_score, 'why': why_str,
            'price': float(rt_price) if rt_price is not None else None,
            'price_str': f"{rt_price:.2f}" if rt_price is not None else "N/A",
            'rsi': float(rsi_val) if rsi_val is not None else None,
            'pe': float(pe) if pe is not None else None,
            'market_cap': float(mcap) if mcap is not None else None,
            'pct_drop': float(pct_drop) if pct_drop is not None else None,
            'rsi_str': f"{rsi_val:.1f}" if rsi_val is not None else "N/A",
            'pe_str': f"{pe:.1f}" if pe is not None else "N/A",
            'market_cap_str': cap_str,
            'dma200': float(dma200_val) if dma200_val is not None else None,
            'dma50': float(dma50_val) if dma50_val is not None else None,
            'dma200_str': f"{dma200_val:.1f}" if dma200_val is not None else "N/A",
            'dma50_str': f"{dma50_val:.1f}" if dma50_val is not None else "N/A",
            'trend_rationale': trend_rationale, 
            'trend_dir': trend_dir_val,
            'pe_check': pe_pass,
            'growth_check': growth_pass,
            'debt_check': debt_pass,
            'trailing_pe': funds['trailing_pe'],
            'earnings_growth': f"{(funds['earnings_growth'] or 0)*100:.1f}%",
            'debt_to_equity': funds['debt_to_equity']
        })

        if not sig: continue

        log_alert({
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": symbol, "signal": sig, "company": company_name, "price": rt_price,
            "rsi": rsi_val, "pe_ratio": pe, "market_cap": mcap
        })

        if sig == "BUY":
            buy_symbols.append(symbol)
            prices[symbol] = rt_price
            rsi_vals[symbol] = rsi_val
            for s in stock_data_list:
                if s["ticker"] == symbol: s["put"] = default_put_obj(); break
        else:
            sell_alert_line = format_sell_alert_line(ticker=symbol, price=rt_price, rsi=rsi_val, pe=pe, mcap=cap_str)
            all_sell_alerts.append(f"""<div class="main-info"><div><span class="ticker-alert">{symbol}</span></div><div class="price-details"><div class="current-price price-down">{rt_price:.2f}</div></div></div><p class="news-summary">{sell_alert_line}</p>""")

    # Options section (only for BUY signals)
    for sym in buy_symbols:
        price = prices.get(sym)
        pe, mcap = fetch_fundamentals_safe(sym)
        cap_str = format_market_cap(mcap)
        rsi_val = rsi_vals.get(sym, None)
        puts_list = fetch_puts(sym)
        puts_list = calculate_custom_metrics(puts_list, price)
        filtered_puts = [p for p in puts_list if p.get("strike") and price and p["strike"] < price and p.get("custom_metric",0) >= 10]
        
        if not filtered_puts: continue
        best_put = max(filtered_puts, key=lambda x: x.get('premium_percent', 0) or x.get('premium', 0))
        expiration_fmt = datetime.datetime.strptime(best_put['expiration'], "%Y-%m-%d").strftime("%b %d, %Y") if best_put.get('expiration') else "N/A"
        stock_row = next((s for s in stock_data_list if s["ticker"] == sym), None)

        put_obj = {
            "strike": float(best_put['strike']), "expiration": expiration_fmt,
            "exp_type": best_put.get("exp_type", "UNKNOWN"),
            "weekly_available": bool(best_put.get("weekly_available")),
            "monthly_available": bool(best_put.get("monthly_available")),
            "premium": float(best_put['premium']), "delta_percent": float(best_put['delta_percent']),
            "premium_percent": float(best_put['premium_percent']),
            "metric_sum": (float(best_put['delta_percent'] or 0) + float(best_put['premium_percent'] or 0))
        }
        for s in stock_data_list:
            if s['ticker'] == sym: s['put'] = put_obj; break

        buy_alert_line = format_buy_alert_line(
            ticker=sym, company_name=fetch_company_name(sym), price=price, rsi=rsi_val, pe=pe, mcap=cap_str,
            dma200=stock_row.get("dma200"), dma50=stock_row.get("dma50"), strike=float(best_put['strike']), 
            expiration=expiration_fmt, premium=float(best_put['premium']), 
            delta_percent=float(best_put['delta_percent']), premium_percent=float(best_put['premium_percent'])
        )
        
        news_items = fetch_news_ticker(sym)
        summary_sentence = "No recent reason found."
        if news_items and 'error' not in news_items[0]:
            use_news = next((n for n in news_items if float(n.get('sentiment',0)) < 0), news_items[0])
            summary_sentence = ensure_sentence_completion(use_news.get('summary') or use_news.get('headline') or "No summary.")

        top_news = sorted([n for n in news_items if 'sentiment' in n and abs(float(n['sentiment'])) > 0.2], key=lambda x: -float(x['sentiment']))[:4]
        news_html = '<ul class="news-list">' + "".join([f"<li>{'🟢' if float(n['sentiment'])>0.2 else '🔴'} <a href='{n['url']}'>{n['headline']}</a></li>" for n in top_news]) + '</ul>'

        for s in stock_data_list:
            if s['ticker'] == sym: s['news_summary'] = summary_sentence; s['news'] = news_items; break

        buy_alerts_web.append(f"""<div class="main-info"><div><span class="ticker-alert">{sym}</span></div><div class="price-details"><div class="current-price price-up">{price:.2f}</div></div></div><p class="news-summary">{buy_alert_line}</p><p class="news-summary">{summary_sentence}..</p>{news_html}""")
        
        try:
            with open(os.path.join(puts_dir, f"{sym}_puts_7weeks.json"), "w") as fp:
                json.dump([best_put], fp, indent=2)
        except Exception: pass

    return buy_symbols, buy_alerts_web, all_sell_alerts, failed, stock_data_list, spread_results
    
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    args = parser.parse_args()
    selected = [t.strip() for t in args.tickers.split(",")] if args.tickers else tickers
    retry_counts = defaultdict(int)
    to_process = selected[:]

    prev_tickers = set()
    spreads_path = "data/spreads.json"
    if os.path.exists(spreads_path):
        try:
            with open(spreads_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                # Handle cases where data might be a list or a dict with a "data" key
                if isinstance(old_data, dict):
                    old_data = old_data.get("data", [])
                if isinstance(old_data, list):
                    prev_tickers = {item.get('ticker') for item in old_data if item.get('ticker')}
            logger.info(f"Loaded {len(prev_tickers)} previous tickers for 'Newness' check.")
        except Exception as e:
            logger.warning(f"Could not load previous spreads for comparison: {e}")
            
    
    all_buy_symbols = []
    all_buy_alerts_web = []
    all_sell_alerts = []
    all_stock_data = []
    all_spreads = []

    while to_process and any(retry_counts[t] < MAX_TICKER_RETRIES for t in to_process):
        logger.info(f"Processing {len(to_process)} tickers...")
        buys, buy_alerts_web, sells, fails, stock_data_list, spread_results = job(to_process)
        
        all_buy_alerts_web.extend(buy_alerts_web)
        all_sell_alerts.extend(sells)
        all_buy_symbols.extend(buys)
        all_stock_data.extend(stock_data_list)
        all_spreads.extend(spread_results)
        
        for f in fails: retry_counts[f] += 1
        to_process = [f for f in fails if retry_counts[f] < MAX_TICKER_RETRIES]
        if to_process:
            logger.info(f"Rate limited. Waiting {TICKER_RETRY_WAIT} seconds...")
            time.sleep(TICKER_RETRY_WAIT)

    # Dedup logic
    all_buy_alerts_web = list(set(all_buy_alerts_web))
    all_sell_alerts = list(set(all_sell_alerts))
    unique_stock_data = list({s['ticker']: s for s in all_stock_data}.values())

    payload = {
        "generated_at_pt": dt_pacific.strftime("%m-%d-%Y %H:%M"),
        "buys": [s for s in unique_stock_data if s.get('signal') == 'BUY'],
        "sells": [s for s in unique_stock_data if s.get('signal') == 'SELL'],
        "all": unique_stock_data
    }
    put_map = {s["ticker"]: s.get("put", {}) for s in unique_stock_data}

    for sp in all_spreads:
        p = put_map.get(sp["ticker"], {}) or {}
        sp["weekly_available"] = p.get("weekly_available", None)
        sp["monthly_available"] = p.get("monthly_available", None)
        sp["exp_type"] = p.get("exp_type", None)
        sp["is_new"] = sp["ticker"] not in prev_tickers
    
    # Save to both locations to be safe
    with open("artifacts/data/signals.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    
    # Also save to data/signals.json where your frontend likely looks
    with open("data/signals.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    all_spreads.sort(key=lambda x: (not x.get('is_new', False), -1 * (x.get('mcap') or 0)))
    logger.info(f"DEBUG: Generated {len(all_spreads)} total spread signals for JSON.")
    for spread in all_spreads[:3]: # Log the first 3 for confirmation
        logger.info(f"DEBUG: Sample Signal -> {spread['ticker']}: {spread['strategy']}")
    
    with open("artifacts/data/spreads.json", "w", encoding="utf-8") as f:
        json.dump(all_spreads, f, ensure_ascii=False, indent=2)

    with open("data/spreads.json", "w", encoding="utf-8") as f:
        json.dump(all_spreads, f, ensure_ascii=False, indent=2)

    logger.info(f"Successfully updated spreads.json in data/ and artifacts/ with {len(all_spreads)} signals.")
    logger.info("Written signals.json to data/ and artifacts/data/")

if __name__ == "__main__":
    main()
