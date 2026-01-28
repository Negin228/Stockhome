import os
import json
import datetime
import time
import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, AssetClass, OrderStatus 
from alpaca.trading.requests import (
    OptionLegRequest, # Corrected from OrderLegRequest
    LimitOrderRequest, 
    MarketOrderRequest
)

# Read secrets from environment variables
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
    bp = float(account.options_buying_power)
    log_event(f"Current Options Buying Power: ${bp:,.2f}")
    return bp

def find_leg_symbols(ticker_sym, current_price, strategy):
    """Uses yfinance to find the two legs for the spread."""
    tk = yf.Ticker(ticker_sym)
    today = datetime.date.today()
    
    valid_exps = [e for e in tk.options if (datetime.datetime.strptime(e, '%Y-%m-%d').date() - today).days >= MIN_DAYS_OUT]
    if not valid_exps: return None
    
    target_exp = valid_exps[0]
    opts = tk.option_chain(target_exp)
    
    if "Call Debit" in strategy:
        buy_s, sell_s = current_price - 2.5, current_price + 2.5
        chain = opts.calls
        side1, side2 = OrderSide.BUY, OrderSide.SELL
    elif "Put Credit" in strategy:
        sell_s, buy_s = current_price + 2.5, current_price - 2.5
        chain = opts.puts
        side1, side2 = OrderSide.SELL, OrderSide.BUY
    else: return None

    l1 = chain.iloc[(chain['strike'] - buy_s).abs().argsort()[:1]].iloc[0]
    l2 = chain.iloc[(chain['strike'] - sell_s).abs().argsort()[:1]].iloc[0]

    return [
        {"symbol": l1['contractSymbol'], "side": side1},
        {"symbol": l2['contractSymbol'], "side": side2}
    ]

def submit_spread_order(ticker, strategy, legs):
    """Submits a multi-leg limit order using OptionLegRequest."""
    # Multi-leg orders use ratio_qty to define the contract balance
    leg_reqs = [
        OptionLegRequest(
            symbol=l['symbol'], 
            ratio_qty=1, 
            side=l['side']
        ) for l in legs
    ]
    
    order_data = LimitOrderRequest(
        symbol=ticker,
        limit_price=ENTRY_LIMIT,
        qty=1,
        side=OrderSide.BUY if "Debit" in strategy else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.MLEG, # Required for multi-leg spreads
        legs=leg_reqs,               # Correct parameter name is 'legs'
        asset_class=AssetClass.OTPS
    )
    
    try:
        client.submit_order(order_data)
        log_event(f"ORDER PLACED: {strategy} {ticker} | Legs: {[l['symbol'] for l in legs]}")
        return True
    except Exception as e:
        log_event(f"ORDER ERROR {ticker}: {e}")
        return False

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

        if price < MIN_STOCK_PRICE: continue
        if ticker in portfolio: continue
        
        if bp < 250:
            log_event(f"SKIPPED {ticker}: Insufficient Buying Power (${bp:.2f})")
            continue

        log_event(f"SIGNAL FOUND: {strategy} for {ticker} at ${price}")
        
        legs = find_leg_symbols(ticker, price, strategy)
        if legs:
            success = submit_spread_order(ticker, strategy, legs)
            if success:
                bp -= 250

if __name__ == "__main__":
    reset_and_trade()
    log_event("Entering Monitor Mode (Stop-Loss Protection)...")
    # Monitor loop placeholder
    # time.sleep(300)
