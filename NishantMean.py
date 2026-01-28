import os
import json
import datetime
import time
import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, AssetClass, OrderStatus 
from alpaca.trading.requests import (
    OptionLegRequest, 
    LimitOrderRequest, 
    MarketOrderRequest
)

# Read secrets from environment variables
ALPACA_NISHANTMEAN_KEY = os.getenv("ALPACA_NISHANTMEAN_KEY")
ALPACA_NISHANTMEAN_SECRET = os.getenv("ALPACA_NISHANTMEAN_SECRET")

if not ALPACA_NISHANTMEAN_KEY or not ALPACA_NISHANTMEAN_SECRET:
    raise ValueError("Alpaca API keys not found in environment variables.")
  
JSON_PATH = "data/spreads.json"
LOG_FILE = "trading_report.txt"
MIN_STOCK_PRICE = 100.0
ENTRY_LIMIT = 2.50 # $250 cost/credit
MIN_DAYS_OUT = 30

client = TradingClient(ALPACA_NISHANTMEAN_KEY, ALPACA_NISHANTMEAN_SECRET, paper=True)

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
    """Uses yfinance to find two legs with 4-6 width and fair pricing data."""
    log_event(f"DEBUG: Searching legs for {ticker_sym} using strategy: {strategy}")
    tk = yf.Ticker(ticker_sym)
    today = datetime.date.today()
    
    options = tk.options
    if not options: return None

    valid_exps = [e for e in options if (datetime.datetime.strptime(e, '%Y-%m-%d').date() - today).days >= MIN_DAYS_OUT]
    if not valid_exps: return None
    
    target_exp = valid_exps[0]
    try:
        opts = tk.option_chain(target_exp)
    except Exception as e: return None
    
    strat_upper = strategy.upper()
    if "CALL" in strat_upper and "DEBIT" in strat_upper:
        buy_s, sell_s = current_price - 2.5, current_price + 2.5
        chain, side1, side2 = opts.calls, OrderSide.BUY, OrderSide.SELL
    elif "PUT" in strat_upper and "CREDIT" in strat_upper:
        sell_s, buy_s = current_price + 2.5, current_price - 2.5
        chain, side1, side2 = opts.puts, OrderSide.SELL, OrderSide.BUY
    elif "CALL" in strat_upper and "CREDIT" in strat_upper:
        sell_s, buy_s = current_price + 2.5, current_price + 7.5
        chain, side1, side2 = opts.calls, OrderSide.SELL, OrderSide.BUY
    elif "PUT" in strat_upper and "DEBIT" in strat_upper:
        buy_s, sell_s = current_price - 2.5, current_price - 7.5
        chain, side1, side2 = opts.puts, OrderSide.BUY, OrderSide.SELL
    else: return None

    if chain.empty: return None

    # Find First Leg
    l1 = chain.iloc[(chain['strike'] - buy_s).abs().argsort()[:1]].iloc[0]
    strike1 = l1['strike']

    # --- MINIMAL CHANGE: Strike Width 4-6 Logic ---
    if "CALL" in strat_upper or ("PUT" in strat_upper and "CREDIT" in strat_upper):
        mask = (chain['strike'] >= strike1 + 4.0) & (chain['strike'] <= strike1 + 6.0)
    else:
        mask = (chain['strike'] <= strike1 - 4.0) & (chain['strike'] >= strike1 - 6.0)
    
    valid_second_legs = chain[mask]
    if valid_second_legs.empty: return None

    l2 = valid_second_legs.iloc[(valid_second_legs['strike'] - sell_s).abs().argsort()[:1]].iloc[0]

    # --- MINIMAL CHANGE: Pass Mid-Price data ---
    return [
        {"symbol": l1['contractSymbol'], "side": side1, "mid": (l1['bid'] + l1['ask']) / 2},
        {"symbol": l2['contractSymbol'], "side": side2, "mid": (l2['bid'] + l2['ask']) / 2}
    ]

def submit_spread_order(ticker, strategy, legs):
    """Submits order at Market Mid-Price, capped by ENTRY_LIMIT."""
    
    # --- MINIMAL CHANGE: Dynamic Pricing Logic ---
    mark = round(abs(legs[0]['mid'] - legs[1]['mid']), 2)
    final_price = min(mark, ENTRY_LIMIT) # Capped at 2.50

    leg_reqs = [OptionLegRequest(symbol=l['symbol'], ratio_qty=1, side=l['side']) for l in legs]
    
    order_data = LimitOrderRequest(
        symbol=None,
        limit_price=final_price,
        qty=1,
        side=OrderSide.BUY if "DEBIT" in strategy.upper() else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.MLEG,
        legs=leg_reqs,
        asset_class=AssetClass.US_OPTION
    )
    
    try:
        client.submit_order(order_data)
        log_event(f"ORDER PLACED: {ticker} at ${final_price} (Mid was ${mark})")
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
    except FileNotFoundError: return

    for s in signals:
        ticker, price, strategy = s['ticker'], s['price'], s['strategy']
        
        if not (("CALL" in strategy.upper() and "DEBIT" in strategy.upper()) or ("PUT" in strategy.upper() and "CREDIT" in strategy.upper())):
            continue

        if price < MIN_STOCK_PRICE: continue
        
        # --- MINIMAL CHANGE: Improved Portfolio Check ---
        if any(ticker in pos for pos in portfolio):
            continue
        
        if bp < 250: continue

        legs = find_leg_symbols(ticker, price, strategy)
        if legs:
            success = submit_spread_order(ticker, strategy, legs)
            if success: bp -= 250

if __name__ == "__main__":
    reset_and_trade()
