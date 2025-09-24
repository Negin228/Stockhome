import os
import datetime
import pandas as pd
import yfinance as yf
import numpy as np
import ta
from ta.momentum import RSIIndicator
from dateutil.parser import parse
import finnhub
import logging
import time
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
LOG_FILE = "stockhome.log"
LOG_MAX_BYTES = 10_000_000
LOG_BACKUP_COUNT = 5

os.makedirs(LOG_DIR, exist_ok=True)
log_path = os.path.join(LOG_DIR, LOG_FILE)

logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


initial_cash = 300_000
max_positions = 5
rsi_threshold = 30
sell_target = 1.2  # Sell when price rises 20% above buy
days_back = 730  # 2 years
MAX_CACHE_DAYS = 7



API_KEY = os.getenv("API_KEY")
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
def fetch_cached_history(symbol, period="2y", interval="1d"):
    path = os.path.join(LOG_DIR, f"{symbol}.csv")
    df = None
    force_full = False
    if os.path.exists(path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age_days > MAX_CACHE_DAYS:
            force_full = True
            logger.info(f"Cache for {symbol} is stale ({age_days} days), refreshing")
        else:
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
    if "Close" not in df.columns:
        return df
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    if close.empty or close.isnull().all():
        return df
    df["rsi"] = RSIIndicator(close, window=14).rsi()
    return df


def generate_signal(df):
    if df.empty or "rsi" not in df.columns:
        return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None, ""
    price = df["Close"].iloc[-1] if "Close" in df.columns else np.nan
    return None, ""


def fetch_fundamentals_safe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning(f"Failed to fetch fundamentals for {symbol}: {e}")
        return None, None

# You can use a custom list or fetch tickers from a file
tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA"]





cash = initial_cash
holdings = {}  # {ticker: {'buy_price':..., 'buy_date':...}}
trade_log = []

start_date = datetime.datetime.now() - datetime.timedelta(days=days_back)
end_date = datetime.datetime.now()

for t in tickers:
    print(f"Processing {t}...")
    hist = fetch_cached_history(t, period="2y", interval="1d")
    if hist.empty or "Close" not in hist.columns:
        print(f"  No data for {t}, skipping.")
        continue
    hist = calculate_indicators(hist)
    if 'rsi' not in hist.columns:
        print(f"  'rsi' column not present for {t} after indicator calc, skipping.")
        continue  # Skip to next ticker if missing
    hist = hist.dropna(subset=['rsi'])

    for date, row in hist.iterrows():
        price = float(row['Close'])
        rsi = float(row['rsi'])
        already_holding = t in holdings
        # BUY: RSI < 30, not already holding, max 5 positions
        if rsi < rsi_threshold and len(holdings) < max_positions and not already_holding:
            holdings[t] = {'buy_price': price, 'buy_date': date}
            cash -= price
            trade_log.append({
                'ticker': t,
                'action': 'BUY',
                'date': date,
                'price': price,
                'cash': cash
            })
        # SELL: Already holding, price >= buy_price * 1.2
        elif already_holding and price >= holdings[t]['buy_price'] * sell_target:
            pnl = price - holdings[t]['buy_price']
            cash += price
            trade_log.append({
                'ticker': t,
                'action': 'SELL',
                'date': date,
                'price': price,
                'pnl': pnl,
                'cash': cash
            })
            del holdings[t]

# Liquidate any remaining holdings at the most recent price
for t in list(holdings):  # convert to list to safely mutate holdings
    try:
        df_recent = fetch_cached_history(t, period="5d", interval="1d")
        if not df_recent.empty and "Close" in df_recent.columns:
            recent_price = float(df_recent["Close"].iloc[-1])
            buy_price = holdings[t]['buy_price']
            pnl = recent_price - buy_price
            cash += recent_price
            trade_log.append({
                'ticker': t,
                'action': 'LIQUIDATE',
                'date': end_date,
                'price': recent_price,
                'pnl': pnl,
                'cash': cash
            })
            del holdings[t]
    except Exception:
        print(f"  Could not liquidate {t}")

# Output results to Excel
df_trades = pd.DataFrame(trade_log)
df_trades.to_excel("stock_backtest_PNL.xlsx", index=False)
print(f"Final value: ${cash:,.2f}")
