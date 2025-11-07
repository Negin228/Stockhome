import json
import os
from datetime import datetime, timedelta
from alpaca.data.options import OptionChainClient
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import OptionOrderRequest, OptionSymbolParams
from alpaca.trading.enums import OptionOrderSide, TimeInForce, OrderClass, OptionOrderType

# Load secrets from environment for github actions
ALPACA_PAPER_API_KEY = os.environ['ALPACA_PAPER_API_KEY_ID']
ALPACA_PAPER_API_SECRET = os.environ['ALPACA_PAPER_API_SECRET_KEY']
client = TradingClient(ALPACA_PAPER_API_KEY, ALPACA_PAPER_API_SECRET, paper=True)

# 1. Load buy signals from signals.json
with open('artifacts/data/signals.json', 'r') as f:
    signal_data = json.load(f)

# Helper: fetch open option positions and pending option orders
def get_active_puts(symbol):
    positions = client.get_all_positions()
    puts = [p for p in positions if p.asset_id == symbol and p.asset_class == "option" and p.side == "short"]
    return puts

def get_pending_put_orders(symbol):
    orders = client.get_orders(status='open', symbols=[symbol])
    puts = [o for o in orders if o.order_class == OrderClass.SIMPLE and o.legs[0]['side'] == OptionOrderSide.SELL_TO_OPEN]
    return puts

# Main logic loop: For each buy signal
for buy in signal_data.get('buys', []):
    symbol = buy['ticker']
    strike = float(buy['strike'])
    expiry = buy['expiration']  # Expecting 'YYYY-MM-DD'
    option_symbol = OptionSymbolParams(
        symbol=symbol, 
        expiry=expiry, 
        strike=strike,
        type='put'
    ).to_option_symbol()
    
    # Check for existing open/pending puts
    open_puts = get_active_puts(symbol)
    pending_puts = get_pending_put_orders(symbol)
    
    # If put already sold/assigned, skip
    if open_puts:
        print(f"Already have sold put on {symbol}. Skipping.")
        continue

    # Pending put: If pending order matches this, do nothing.
    current_pending = [o for o in pending_puts if o.symbol == option_symbol and o.legs[0]['strike'] == strike and o.legs[0]['expiry'] == expiry]
    if current_pending:
        print(f"Pending put already exists for {symbol} at {strike} exp {expiry}. Skipping order.")
        continue
    # If a different pending put exists, cancel it and place new:
    if pending_puts:
        print(f"Cancelling previous pending put for {symbol}.")
        for o in pending_puts:
            client.cancel_order(o.id)
    
    print(f"Placing new sell put option order for {symbol}, {strike} exp {expiry}")
    put_order = OptionOrderRequest(
        symbol=option_symbol,
        qty=1,
        side=OptionOrderSide.SELL_TO_OPEN,
        type=OptionOrderType.MARKET,
        time_in_force=TimeInForce.DAY
    )
    order_response = client.submit_option_order(put_order)
    print(order_response)

# Assignment handler (simplified): If assigned, sell covered call
# You would want to run this logic after options expiration
def handle_assignment_and_sell_call():
    positions = client.get_all_positions()
    for pos in positions:
        if pos.asset_class == "us_equity" and int(pos.qty) > 0:
            # Find the assigned put's strike, then generate call 10% higher for nearest expiry using OptionChainClient
            call_strike = round(float(pos.avg_entry_price) * 1.1, 2)
            occ = OptionChainClient()
            chain = occ.get_option_chain(symbol=pos.symbol)
            upcoming_expiries = sorted({opt.expiry for opt in chain.calls})
            if not upcoming_expiries:
                print(f"No expiry found for {pos.symbol} call.")
                continue
            # Pick earliest expiry and closest strike >= call_strike
            valid_calls = [opt for opt in chain.calls if opt.expiry == upcoming_expiries[0] and opt.strike >= call_strike]
            if not valid_calls:
                print(f"No valid calls for {pos.symbol} at strike {call_strike}")
                continue
            call = min(valid_calls, key=lambda x: x.strike)
            call_order = OptionOrderRequest(
                symbol=call.option_symbol,
                qty=1,
                side=OptionOrderSide.SELL_TO_OPEN,
                type=OptionOrderType.MARKET,
                time_in_force=TimeInForce.DAY
            )
            print(f"Placing covered call order for {pos.symbol} at strike {call.strike}, expiry {call.expiry}")
            order_response = client.submit_option_order(call_order)
            print(order_response)

# Run assignment handler as needed
# handle_assignment_and_sell_call()
