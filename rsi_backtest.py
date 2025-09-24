import os
import datetime
import pandas as pd
import yfinance as yf
import numpy as np
from ta.momentum import RSIIndicator
from dateutil.parser import parse

# Configurable parameters
DATA_DIR = "stock_cache"
os.makedirs(DATA_DIR, exist_ok=True)

initial_cash = 300_000
max_positions = 5
rsi_threshold = 30
sell_target = 1.2  # Sell when price rises 20% above buy
days_back = 730  # 2 years

# You can use a custom list or fetch tickers from a file
tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA"]

def fetch_cached_history(symbol, period="2y", interval="1d", max_cache_days=7):
    path = os.path.join(DATA_DIR, f"{symbol}.csv")
    df = None
    force_full = False
    # Load from cache if fresh
    if os.path.exists(path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age_days > max_cache_days:
            force_full = True
        else:
            try:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                if df.empty or "Close" not in df.columns:
                    force_full = True
            except Exception:
                df = None
    # If no cache, or cache is stale
    if df is None or df.empty or force_full:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if not df.empty:
            df.to_csv(path)
    # Make sure date index is datetime
    if not df.empty:
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, errors='coerce')
    return df


def calculate_indicators(df):
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    return df

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
    if 'rsi' not in hist.columns or hist['rsi'].isnull().all():
        print(f"  No RSI for {t}, skipping.")
        continue
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
for t in holdings:
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
    except Exception:
        print(f"  Could not liquidate {t}")

# Output results to Excel
df_trades = pd.DataFrame(trade_log)
df_trades.to_excel("stock_backtest_PNL.xlsx", index=False)
print(f"Final value: ${cash:,.2f}")
