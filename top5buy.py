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
POSITION_PCT = 0.05       # <--- CHANGED: 5% of equity per ticker
TAKE_PROFIT_PCT = 0.03    
STOP_LOSS_PCT = 0.10      
MAX_POSITIONS = 5         
SIGNALS_FILE = "data/signals.json"

def main():
    # 1. Initialize Alpaca
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("Error: Alpaca credentials missing.")
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, BASE_URL, api_version='v2')

    # <--- NEW: Get Account Equity
    try:
        account = api.get_account()
        equity = float(account.equity)
        print(f"Account Equity: ${equity:.2f}")
    except Exception as e:
        print(f"Error fetching account info: {e}")
        return

    # 2. Load Signals
    if not os.path.exists(SIGNALS_FILE):
        print(f"Error: {SIGNALS_FILE} not found. Please ensure it is committed to the repo.")
        return

    print(f"Loading signals from {SIGNALS_FILE}...")
    with open(SIGNALS_FILE, "r") as f:
        data = json.load(f)

    # 3. Filter & Sort Buys
    buy_signals = data.get("buys", [])
    if not buy_signals:
        print("No BUY signals found.")
        return

    # Sort by score (descending) and take top 5
    top_picks = sorted(buy_signals, key=lambda x: x.get("score", 0), reverse=True)[:MAX_POSITIONS]
    print(f"Top {len(top_picks)} Picks: {[p['ticker'] for p in top_picks]}")

    # 4. Execute Orders
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

            # C. Calculate Shares (Based on Equity %)
            target_position_size = equity * POSITION_PCT # <--- CHANGED: Calculate dynamic size
            qty = math.floor(target_position_size / current_price)
            
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
                time_in_force='day',       
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
            print(f"❌ ERROR: Could not trade {symbol}: {e}")

if __name__ == "__main__":
    main()
