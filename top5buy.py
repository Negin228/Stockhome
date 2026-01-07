import json
import os
import math
import alpaca_trade_api as tradeapi

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
ALPACA_API_KEY = os.getenv("ALPACA_SCORE_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SCORE_SECRET_KEY")
# Use paper-api for testing. Switch to "https://api.alpaca.markets" for real money.
BASE_URL = "https://paper-api.alpaca.markets"

# Trading Parameters
POSITION_SIZE_USD = 500   # How much to spend per stock
TAKE_PROFIT_PCT = 0.03    # Sell when up 3%
MAX_POSITIONS = 5         # Limit to top 5 stocks
SIGNALS_FILE = "data/signals.json"

def main():
    # 1. Initialize Alpaca
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("Error: Alpaca credentials missing.")
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, BASE_URL, api_version='v2')

    # 2. Load Signals
    if not os.path.exists(SIGNALS_FILE):
        print(f"Error: {SIGNALS_FILE} not found. Ensure analysis ran first.")
        return

    print(f"Loading signals from {SIGNALS_FILE}...")
    with open(SIGNALS_FILE, "r") as f:
        data = json.load(f)

    # 3. Filter & Sort Buys
    # Get 'buys' list -> Sort by 'score' descending -> Take top 5
    buy_signals = data.get("buys", [])
    if not buy_signals:
        print("No BUY signals found.")
        return

    top_picks = sorted(buy_signals, key=lambda x: x.get("score", 0), reverse=True)[:MAX_POSITIONS]
    print(f"Top {len(top_picks)} Picks: {[p['ticker'] for p in top_picks]}")

    # 4. Execute Orders
    for stock in top_picks:
        symbol = stock["ticker"]

        try:
            # A. Check Existing Position
            # We don't want to buy if we already hold it
            try:
                pos = api.get_position(symbol)
                if float(pos.qty) != 0:
                    print(f"Skipping {symbol}: Position already exists.")
                    continue
            except Exception:
                pass # No position found, safe to proceed

            # B. Get Real-Time Price
            # Do not trust the JSON price, it is old. Get the live trade.
            quote = api.get_latest_trade(symbol)
            current_price = float(quote.price)

            # C. Calculate Shares
            qty = math.floor(POSITION_SIZE_USD / current_price)
            if qty < 1:
                print(f"Skipping {symbol}: Price ${current_price} is higher than position size ${POSITION_SIZE_USD}")
                continue

            # D. Calculate Take Profit Price
            take_profit_price = round(current_price * (1 + TAKE_PROFIT_PCT), 2)

            print(f"Placing Order: {symbol} | Buy {qty} @ ${current_price} | Target Sell @ ${take_profit_price}")

            # E. Submit Bracket Order (OTO)
            # - Limit Buy: Valid ONLY for today (Day)
            # - Limit Sell: Created if Buy fills, valid forever (GTC)
            api.submit_order(
                symbol=symbol,
                qty=qty,
                side='buy',
                type='limit',
                limit_price=current_price,
                time_in_force='day',     # <--- Buy order expires at market close
                order_class='oto',       # <--- One-Triggers-Other
                take_profit={
                    'limit_price': take_profit_price
                    # Exit legs in Alpaca OTO default to GTC (Good Till Cancelled)
                }
            )
            print(f"✅ SUCCESS: Order submitted for {symbol}")

        except Exception as e:
            print(f"❌ ERROR: Could not trade {symbol}: {e}")

if __name__ == "__main__":
    main()
