import json
import datetime
import time
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    OrderLegRequest, LimitOrderRequest, MarketOrderRequest, 
    OrderSide, TimeInForce
)
from alpaca.trading.enums import AssetClass, OrderStatus

API_KEY = os.getenv("ALPACA_NISHANTMEAN_KEY")
SECRET_KEY = os.getenv("ALPACA_NISHANTMEAN_SECRET")

if not API_KEY or not SECRET_KEY:
    raise ValueError("Alpaca API keys not found in environment variables.")
  
JSON_PATH = "data/spreads.json"
LOG_FILE = "trading_report.txt"
MIN_STOCK_PRICE = 100.0
ENTRY_LIMIT = 2.50 # $250 cost/credit
MIN_DAYS_OUT = 30

client = TradingClient(API_KEY, SECRET_KEY, paper=True)

def log_event(message):
    """Timestamped reporting for your trades."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    with open(LOG_FILE, "a") as f:
        f.write(formatted_msg + "\n")

def check_buying_power():
    """Ensures we have at least $250 available to place the trade."""
    account = client.get_account()
    # For options, we look at non_marginable_buying_power or equity
    bp = float(account.options_buying_power)
    log_event(f"Current Options Buying Power: ${bp:,.2f}")
    return bp

def reset_and_trade():
    log_event("--- STARTING TRADE CYCLE ---")
    client.cancel_orders()
    
    bp = check_buying_power()
    portfolio = [p.symbol for p in client.get_all_positions()]
    
    try:
        with open(JSON_PATH, "r") as f:
            data = json.load(f)
            signals = data if isinstance(data, list) else data.get('all', [])
    except FileNotFoundError:
        log_event("CRITICAL: spreads.json not found.")
        return

    for s in signals:
        ticker, price, strategy = s['ticker'], s['price'], s['strategy']

        # 1. THE FILTERS
        if price < MIN_STOCK_PRICE: continue
        if ticker in portfolio: continue
        
        # 2. THE BUYING POWER GATEKEEPER
        if bp < 250:
            log_event(f"SKIPPED {ticker}: Insufficient Buying Power (${bp:.2f})")
            continue

        log_event(f"SIGNAL FOUND: {strategy} for {ticker} at ${price}")
        
        legs = find_leg_symbols(ticker, price, strategy)
        if legs:
            success = submit_spread_order(ticker, strategy, legs)
            if success:
                bp -= 250 # Optimistically decrement bp for the next loop check

def submit_spread_order(ticker, strategy, legs):
    leg_reqs = [OrderLegRequest(symbol=l['symbol'], qty=1, side=l['side']) for l in legs]
    
    order_data = LimitOrderRequest(
        symbol=ticker,
        limit_price=ENTRY_LIMIT,
        qty=1,
        side=OrderSide.BUY if "Debit" in strategy else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        order_legs=leg_reqs,
        asset_class=AssetClass.OTPS
    )
    
    try:
        client.submit_order(order_data)
        log_event(f"ORDER PLACED: {strategy} {ticker} | Legs: {[l['symbol'] for l in legs]}")
        return True
    except Exception as e:
        log_event(f"ORDER ERROR {ticker}: {e}")
        return False

# ... (find_leg_symbols and monitor_stop_loss from previous steps) ...

if __name__ == "__main__":
    reset_and_trade()
    log_event("Entering Monitor Mode (Stop-Loss Protection)...")
    while True:
        # monitor_stop_loss() code goes here
        time.sleep(300)
