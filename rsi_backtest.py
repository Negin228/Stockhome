import pandas as pd
import datetime
import config
from Signal_filter import fetch_cached_history, calculate_indicators

initial_cash = 300_000
max_positions = 5
rsi_threshold = 30
sell_target = 1.2  # Sell when price rises 20% above buy
cash = initial_cash
holdings = {}  # {ticker: {'buy_price':..., 'buy_date':...}}
trade_log = []

start_date = datetime.datetime.now() - datetime.timedelta(days=2*365)
end_date = datetime.datetime.now()

for t in config.tickers:
    hist = fetch_cached_history(t, period="2y", interval="1d")
    if hist.empty or "Close" not in hist.columns:
        continue
    hist = calculate_indicators(hist)
    # Ensure 'rsi' was computed
    if 'rsi' not in hist.columns:
        print(f"Skipping {t}: No RSI data.")
        continue
    # Drop rows with missing RSI
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

# Liquidate any remaining holdings at final price
for t in holdings:
    # Try to get most recent price, else skip
    recent_price = None
    try:
        df_recent = fetch_cached_history(t, period="5d", interval="1d")
        if not df_recent.empty and "Close" in df_recent.columns:
            recent_price = float(df_recent["Close"].iloc[-1])
    except Exception:
        recent_price = None
    if recent_price:
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

# Output results to an Excel file
df_trades = pd.DataFrame(trade_log)
df_trades.to_excel("stock_backtest_PNL.xlsx", index=False)
print(f"Final value: ${cash:,.2f}")
