import os
import json
import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# 1. SETUP ALPACA
API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
PAPER = True 

client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)

def get_occ_symbol(ticker, expiration_str, strike, option_type='P'):
    """Converts readable data into OCC Option Symbol format."""
    try:
        exp_date = datetime.datetime.strptime(expiration_str, "%b %d, %Y")
    except ValueError:
        try:
            exp_date = datetime.datetime.strptime(expiration_str, "%Y-%m-%d")
        except ValueError:
            return None

    yymmdd = exp_date.strftime("%y%m%d")
    strike_int = int(float(strike) * 1000)
    strike_str = f"{strike_int:08d}"
    return f"{ticker:<6}{yymmdd}{option_type}{strike_str}".replace(" ", "")

def run_trader():
    # --- STEP 1: LOAD SIGNALS ---
    signal_path = "artifacts/data/signals.json" 
    if not os.path.exists(signal_path):
        print("Signal file not found.")
        return

    with open(signal_path, "r") as f:
        data = json.load(f)

    # --- STEP 2: GET CURRENT PORTFOLIO & OPEN ORDERS ---
    # This ensures we don't trade anything we already own or are currently trying to sell
    try:
        # Get actual positions (filled trades)
        positions = client.get_all_positions()
        portfolio_symbols = {p.symbol for p in positions}

        # Get open orders (trades waiting to be filled)
        open_orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
        active_order_symbols = {o.symbol for o in open_orders}
        
        # Combine both sets
        existing_commitments = portfolio_symbols.union(active_order_symbols)
        print(f"Current commitments: {existing_commitments}")
    except Exception as e:
        print(f"Error fetching portfolio: {e}")
        return

    # --- STEP 3: PREPARE AND SORT BUY SIGNALS ---
    buy_signals = data.get("buys", [])

    # Sort the signals by 'score' in descending order (Highest Score First)
    # We use .get('score', 0) to handle cases where score might be missing safely
    buy_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

    print(f"Loaded {len(buy_signals)} buy signals. Processing in order of highest score...")

    # --- STEP 4: PROCESS BUY SIGNALS ---
    for signal in buy_signals:
        ticker = signal.get("ticker")
        score = signal.get("score", 0) # visual logging
        put_info = signal.get("put", {})
        
        strike = put_info.get("strike")
        expiration = put_info.get("expiration")
        raw_premium = put_info.get("premium")
        
        if not all([ticker, strike, expiration, raw_premium]):
            continue

        symbol = get_occ_symbol(ticker, expiration, strike, 'P')
        
        # --- CRITICAL CHECK: ONLY TRADE IF NOT IN PORTFOLIO ---
        if symbol in existing_commitments:
            print(f" >> SKIP (Score: {score:.1f}): {symbol} is already in portfolio or has an open order.")
            continue

        # Apply a 5% haircut to the premium to improve fill probability
        limit_price = round(float(raw_premium) * 0.95, 2)

        print(f" >> EXECUTING (Score: {score:.1f}): Selling {symbol} at Limit ${limit_price}")
        try:
            req = LimitOrderRequest(
                symbol=symbol,
                qty=1,
                side=OrderSide.SELL,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY # Auto-cancels at market close
            )
            client.submit_order(req)
            print(f"Successfully submitted order for {symbol}")
        except Exception as e:
            print(f"Failed to submit order for {symbol}: {e}")

if __name__ == "__main__":
    run_trader()
