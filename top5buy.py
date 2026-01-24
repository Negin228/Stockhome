import json
import os
import math
import alpaca_trade_api as tradeapi

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
ALPACA_API_KEY = os.getenv("ALPACA_SCORE_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SCORE_SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"

# Trading Parameters
POSITION_PCT = 0.05       # 5% of equity per ticker
TAKE_PROFIT_PCT = 0.03    
STOP_LOSS_PCT = 0.10      # Kept at 10% (0.10) per your swing trade preference
MAX_POSITIONS = 5         
SIGNALS_FILE = "data/signals.json"

def cancel_stale_buys(api):
    """Cancels any existing BUY orders so we start fresh."""
    print("--- CLEANUP: Checking for stale BUY orders ---")
    try:
        open_orders = api.list_orders(status='open')
        buy_orders = [o for o in open_orders if o.side == 'buy']

        if not buy_orders:
            print("No stale buy orders found.")
            return

        for order in buy_orders:
            print(f"Cancelling stale BUY: {order.symbol} (ID: {order.id})")
            api.cancel_order(order.id)
        
        print(f"Cleanup Complete: Cancelled {len(buy_orders)} orders.\n")
    except Exception as e:
        print(f"Error during cleanup: {e}\n")

def main():
    # 1. Initialize Alpaca
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("Error: Alpaca credentials missing.")
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, BASE_URL, api_version='v2')

    # 2. RUN CLEANUP FIRST
    cancel_stale_buys(api)

    # 3. Get Account Info
    try:
        account = api.get_account()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        print(f"Account Equity: ${equity:.2f} | Buying Power: ${buying_power:.2f}")
    except Exception as e:
        print(f"Error fetching account info: {e}")
        return

    # 4. Load Signals
    if not os.path.exists(SIGNALS_FILE):
        print(f"Error: {SIGNALS_FILE} not found.")
        return

    print(f"Loading signals from {SIGNALS_FILE}...")
    with open(SIGNALS_FILE, "r") as f:
        data = json.load(f)

    # 5. Filter & Sort Buys
    buy_signals = data.get("buys", [])
    
    # FILTER: Score > 50
    valid_signals = [x for x in buy_signals if x.get("score", 0) > 50]

    if not valid_signals:
        print("No signals found above score threshold (50).")
        return

    # Sort by score (descending) and take top 5
    top_picks = sorted(valid_signals, key=lambda x: x.get("score", 0), reverse=True)[:MAX_POSITIONS]
    print(f"Top {len(top_picks)} Picks (>50 score): {[p['ticker'] for p in top_picks]}")

    # 6. Execute Orders
    for stock in top_picks:
        symbol = stock["ticker"]

        try:
            # --- CASH CHECK START ---
            # We re-fetch account data inside the loop to get updated buying power after every trade
            account = api.get_account()
            current_buying_power = float(account.buying_power)
            
            # Calculate Target Size (Based on Equity so positions are equal size)
            target_position_size = equity * POSITION_PCT

            # Check if we have enough cash
            if current_buying_power < target_position_size:
                print(f"⚠️ Insufficient Cash for {symbol}! Need ${target_position_size:.2f}, have ${current_buying_power:.2f}")
                print("Stopping order
