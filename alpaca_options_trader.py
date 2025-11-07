import json
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import OptionOrderRequest, GetOptionContractsRequest
from alpaca.trading.enums import OptionOrderSide, OptionOrderType, TimeInForce

# Load Alpaca credentials from environment
API_KEY = os.environ['ALPACA_PAPER_API_KEY_ID']
API_SECRET = os.environ['ALPACA_PAPER_API_SECRET_KEY']
client = TradingClient(API_KEY, API_SECRET, paper=True)

# --- Utility functions ---

def get_option_contract(client, symbol, strike, expiry, opt_type):
    """Finds an options contract with given parameters."""
    req = GetOptionContractsRequest(
        underlying_symbol=symbol,
        expiration_date=expiry,
        type=opt_type
    )
    contracts = client.get_option_contracts(req)
    for c in contracts:
        # strike_price is string, convert for comparison
        if float(c.strike_price) == float(strike):
            return c
    return None

def get_open_option_positions(symbol, opt_type):
    """Returns list of open (filled) short option positions for symbol/type."""
    return [
        p for p in client.get_all_positions()
        if p.symbol.startswith(symbol)
        and p.asset_class == "option"
        and p.side == "short"
        and (opt_type in p.symbol.lower())
    ]

def get_pending_option_orders(symbol, opt_type):
    """Returns list of open (not yet filled) option orders for symbol/type."""
    pending = []
    # get_orders returns both equities and options orders, we want leg[0] info!
    for o in client.get_orders(status='open'):
        if hasattr(o, 'legs') and o.legs:  # option order
            opt = o.legs[0]
            if (
                symbol.upper() in opt['symbol'].upper()
                and opt['side'] == 'sell_to_open'
                and opt_type in opt['symbol'].lower()
            ):
                pending.append(o)
    return pending

# --- Main action loop for PUT writing ---

with open('artifacts/data/signals.json', 'r') as f:
    signals = json.load(f)

for buy in signals.get('buys', []):
    symbol = buy['ticker']
    strike = float(buy['strike'])
    expiry = buy['expiration']

    # Look up the Alpaca option contract for this put
    contract = get_option_contract(client, symbol, strike, expiry, 'put')
    if not contract:
        print(f"[Put] No contract found for {symbol} {strike} {expiry}")
        continue
    option_symbol = contract.symbol

    filled_puts = get_open_option_positions(symbol, 'put')
    pending_puts = get_pending_option_orders(symbol, 'put')

    # 1. If already have a short put position, do nothing
    if filled_puts:
        print(f"[Put] Active position already exists for {symbol}, skipping.")
        continue

    # 2. If pending order matches signal, do nothing
    pending_match = [
        o for o in pending_puts
        if o.legs[0]['symbol'] == option_symbol and float(o.legs[0]['strike_price']) == strike and o.legs[0]['expiration_date'] == expiry
    ]
    if pending_match:
        print(f"[Put] Pending matching order already exists for {symbol}, skipping.")
        continue

    # 3. If a non-matching pending order exists (old signal), cancel and submit new one
    for o in pending_puts:
        print(f"[Put] Cancelling old pending put order for {symbol}: {o.id}")
        client.cancel_order(o.id)

    # 4. Submit new put order for signal
    print(f"[Put] Placing sell-to-open put order for {symbol} {expiry} ${strike}")
    put_order = OptionOrderRequest(
        symbol=option_symbol,
        qty=1,
        side=OptionOrderSide.SELL_TO_OPEN,
        type=OptionOrderType.MARKET,
        time_in_force=TimeInForce.DAY
    )
    put_submit = client.submit_option_order(put_order)
    print(put_submit)

# --- Assignment logic (covered call writing, e.g. after expiry/assignment days) ---

def write_covered_calls_after_assignment():
    positions = client.get_all_positions()
    for pos in positions:
        # Only if assigned shares, and not already have a pending/filled call
        if pos.asset_class == "us_equity" and int(float(pos.qty)) > 0:
            symbol = pos.symbol
            cost = float(pos.avg_entry_price)
            call_strike = round(cost * 1.1, 2)

            # Find nearest expiry and available call option at/above strike
            req = GetOptionContractsRequest(underlying_symbol=symbol, type='call')
            contracts = client.get_option_contracts(req)
            eligible_contracts = [
                c for c in contracts
                if float(c.strike_price) >= call_strike
            ]
            if not eligible_contracts:
                print(f"[Call] No call contract >= {call_strike} for {symbol}.")
                continue
            # Choose one with the nearest expiry
            eligible_contracts.sort(key=lambda c: (c.expiration_date, float(c.strike_price)))
            contract = eligible_contracts[0]
            option_symbol = contract.symbol

            # Check if call position or pending call order exists
            if get_open_option_positions(symbol, 'call') or get_pending_option_orders(symbol, 'call'):
                print(f"[Call] Existing call position/order for {symbol}, skipping.")
                continue

            print(f"[Call] Placing covered call for {symbol} {contract.expiration_date} ${contract.strike_price}")
            call_order = OptionOrderRequest(
                symbol=option_symbol,
                qty=1,
                side=OptionOrderSide.SELL_TO_OPEN,
                type=OptionOrderType.MARKET,
                time_in_force=TimeInForce.DAY
            )
            call_submit = client.submit_option_order(call_order)
            print(call_submit)

# Uncomment to run
# write_covered_calls_after_assignment()
