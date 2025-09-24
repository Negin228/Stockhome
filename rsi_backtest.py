import config
from signal_filter import fetch_cached_history, calculate_indicators

import pandas as pd
import datetime
import config
from signal_filter import fetch_cached_history, calculate_indicators

initial_cash = 300_000
max_positions = 5
rsi_threshold = 30
sell_target = 1.2

cash = initial_cash
holdings = {}    # {ticker: {'buy_price':..., 'buy_date':...}}
log = []

for t in config.tickers:
    hist = fetch_cached_history(t, period="2y", interval="1d")
    if hist.empty or "Close" not in hist.columns:
        continue
    hist = calculate_indicators(hist)
    hist = hist.dropna(subset=['rsi'])
    for date, row in hist.iterrows():
        price = float(row['Close'])
        rsi = float(row['rsi'])
        already_holding = t in holdings
        # BUY logic
        if rsi < rsi_threshold and len(holdings) < max_positions and not already_holding:
            holdings[t] = {'buy_price': price, 'buy_date': date}
            cash -= price
            log.append({'ticker': t, 'action': 'BUY', 'date': date, 'price': price, 'cash': cash})
        # SELL logic
        elif already_holding and price >= holdings[t]['buy_price'] * sell_target:
            pnl = price - holdings[t]['buy_price']
            cash += price
            log.append({'ticker': t, 'action': 'SELL', 'date': date, 'price': price, 'pnl': pnl, 'cash': cash})
            del holdings[t]
# Liquidate any leftovers
for t in holdings:
    price = float(hist['Close'].iloc[-1])
    pnl = price - holdings[t]['buy_price']
    cash += price
    log.append({'ticker': t, 'action': 'LIQUIDATE', 'date': hist.index[-1], 'price': price, 'pnl': pnl, 'cash': cash})

# Write to Excel
pd.DataFrame(log).to_excel("stock_backtest_PNL.xlsx", index=False)
print(f"Final value: {cash:,.2f}")
