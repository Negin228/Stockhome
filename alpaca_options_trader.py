import os
import json
import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 1. SETUP ALPACA
API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
PAPER = True  # Always True for safety/testing

client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)

def get_occ_symbol(ticker, expiration_str, strike, option_type='P'):
    """
    Converts readable data into OCC Option Symbol format.
    Example: AAPL, 2025-01-17, 150 -> AAPL250117P00150000
    """
    # Parse date (Assuming YYYY-MM-DD from your JSON)
    try:
        exp_date = datetime.datetime.strptime(expiration_str, "%b %d, %Y")
    except ValueError:
        try:
            # Fallback for "YYYY-MM-DD" if some signals use that format
            exp_date = datetime.datetime.strptime(expiration_str, "%Y-%m-%d")
        except ValueError:
            print(f"Skipping {ticker}: Invalid date format {expiration_str}")
            return None
        

    # Format Date: YYMMDD
    yymmdd = exp_date.strftime("%y%m%d")

    # Format Strike: Multiply by 1000 and pad with zeros to 8 digits
    strike_int = int(float(strike) * 1000)
    strike_str = f"{strike_int:08d}"

    # Combine: ROOT + YYMMDD + TYPE + STRIKE
    # Ticker must be padded to 6 chars if needed, but modern API often handles raw ticker
    # Standard OCC is Ticker (upto 6 chars)
    return f"{ticker:<6}{yymmdd}{option_type}{strike_str}".replace(" ", "")

def run_trader():
    # 2. LOAD SIGNALS
    # The workflow copies the new signal to data/signals.json before this runs
    signal_path = "data/signals.json" 
    
    if not os.path.exists(signal_path):
        print("No signals.json found. Exiting.")
        return

    with open(signal_path, "r") as f:
        data = json.load(f)

    # 3. GET CURRENT POSITIONS
    # We want to check if we already have this position to avoid duplicates
    try:
        positions = client.get_all_positions()
        current_symbols = {p.symbol for p in positions}
    except Exception as e:
        print(f"Error fetching positions: {e}")
        return

    # 4. PROCESS SIGNALS
    # Your app.js "renderBuyCard" renders data from the "buys" array.
    # Those cards say "Sell a ... put option".
    # So we look at 'buys' to find Puts to Sell (Short Put Strategy).
    
    if "buys" not in data:
        print("No 'buys' key in signals.json")
        return

    for signal in data["buys"]:
        ticker = signal.get("ticker")
        put_info = signal.get("put", {})
        
        strike = put_info.get("strike")
        expiration = put_info.get("expiration")
        
        if not ticker or not strike or not expiration:
            continue

        # Generate the specific Option Symbol (e.g. AAPL230616P00150000)
        symbol = get_occ_symbol(ticker, expiration, strike, 'P')
        if not symbol:
            continue

        print(f"Checking Signal: Sell Put {symbol}...")

        # 5. EXECUTE TRADE
        # Check if we already hold this specific option symbol
        if symbol in current_symbols:
            print(f" -> SKIP: Already in portfolio ({symbol})")
        else:
            print(f" -> EXECUTING: Selling to Open {symbol}")
            try:
                # 'qty=1' sells 1 contract. Adjust as needed.
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=1,
                    side=OrderSide.SELL,  # Selling to Open (Short Put)
                    time_in_force=TimeInForce.DAY
                )
                client.submit_order(req)
                print(f" -> SUCCESS: Order submitted.")
            except Exception as e:
                print(f" -> ERROR submitting order: {e}")

if __name__ == "__main__":
    run_trader()
