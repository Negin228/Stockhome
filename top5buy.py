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
STOP_LOSS_PCT = 0.03      
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

    # 3. Get Account Equity
    try:
        account = api.get_account()
        buying_power = float(account.buying_power)

    # 4. Load Signals
    if not os.path.exists(SIGNALS_FILE):
        print(f"Error: {SIGNALS_FILE} not found. Please ensure it is committed to the repo.")
        return

    print(f"Loading signals from {SIGNALS_FILE}...")
    with open(SIGNALS_FILE, "r") as f:
        data = json.load(f)

    # 5. Filter & Sort Buys
    buy_signals = data.get("buys", [])
    valid_signals = [x for x in buy_signals if x.get("score", 0) > 50]

    if not valid_signals:
        print("No signals found above score threshold (50).")
        return
        
    if not buy_signals:
        print("No BUY signals found.")
        return

    # Sort by score (descending) and take top 5
    top_picks = sorted(valid_signals, key=lambda x: x.get("score", 0), reverse=True)[:MAX_POSITIONS]
    print(f"Top {len(top_picks)} Picks (>50 score): {[p['ticker'] for p in top_picks]}")

    # 6. Execute Orders
    account = api.get_account()
    buying_power = float(account.buying_power)
    target_position_size = equity * POSITION_PCT

    # If we don't have enough cash for this trade, stop everything
    if buying_power < target_position_size:
        print(f"⚠️ Insufficient Cash! Need ${target_position_size:.2f}, have ${buying_power:.2f}")
        break  # Stops the loop completely for the day
    for stock in top_picks:
        symbol = stock["ticker"]

        try:
            # A. Check Existing Position
            try:
                pos = api.get_position(symbol)
                if float(pos.qty) != 0:
                    print(f"Skipping {symbol}: Position already exists.")
                    continue
            except Exception:
                pass # No position found

            # B. Get Real-Time Price
            quote = api.get_latest_trade(symbol)
            current_price = float(quote.price)

            # C. Calculate Shares (Forced integer cast)
            target_position_size = buying_power * POSITION_PCT 
            qty = int(math.ceil(target_position_size / current_price)) # <--- FIXED: Explicit int()
            
            if qty < 1:
                print(f"Skipping {symbol}: Price ${current_price} > Position Size ${target_position_size:.2f}")
                continue

            # D. Calculate Prices
            take_profit_price = round(current_price * (1 + TAKE_PROFIT_PCT), 2)
            stop_loss_price = round(current_price * (1 - STOP_LOSS_PCT), 2)

            print(f"Placing Bracket: {symbol} | Buy @ ${current_price} | TP: ${take_profit_price} | SL: ${stop_loss_price}")

            # E. Submit Bracket Order
            api.submit_order(
                symbol=symbol,
                qty=qty,
                side='buy',
                type='limit',
                limit_price=current_price,
                time_in_force='gtc',       # <--- FIXED: Changed to 'gtc' so sells don't expire
                order_class='bracket',     
                take_profit={
                    'limit_price': take_profit_price
                },
                stop_loss={
                    'stop_price': stop_loss_price
                }
            )
            print(f"✅ SUCCESS: Bracket order sent for {symbol}")

        except Exception as e:
            print(f"❌ ERROR processing {symbol}: {e}")

if __name__ == "__main__":
    main()
