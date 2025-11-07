import json
import os
from alpaca.trading.client import TradingClient

# ---- CONFIG ----
API_KEY = os.environ["ALPACA_PAPER_API_KEY_ID"]
API_SECRET = os.environ["ALPACA_PAPER_API_SECRET_KEY"]
client = TradingClient(API_KEY, API_SECRET, paper=True)

# ---- UTILITY FUNCTIONS ----

def find_put_contract(symbol, strike, expiry):
    """Finds the symbol of the desired put option."""
    options = client.get_option_contracts(
        underlying_symbol=symbol,
        expiration_date=expiry,
        type="put"
    )
    for contract in options:
        if float(contract.strike_price) == float(strike):
            return contract.symbol
    return None

def find_call_contract(symbol, call_strike):
    """Finds the nearest expiry call contract at or just above the target strike."""
    # Alpaca recommends not passing expiration_date to get all
    options = client.get_option_contracts(
        underlying_symbol=symbol,
        type="call"
    )
    candidates = [
        c for c in options
        if float(c.strike_price) >= call_strike
    ]
    if not candidates:
        return None
    # Sort for earliest expiry and lowest strike (closest above target)
    candidates.sort(key=lambda c: (c.expiration_date, float(c.strike_price)))
    return candidates[0].symbol

def open_option_positions(symbol, side):  # side = 'put'/'call'
    """Returns list of ACTIVE short positions for given symbol/type."""
    positions = client.get_all_positions()
    return [
        p for p in positions
        if p.symbol.startswith(symbol) and p.asset_class == "option"
        and p.side == "short" and side in p.symbol.lower()
    ]

def pending_option_orders(symbol, side):  # side = 'put'/'call'
    """Returns list of OPEN option orders for symbol/type."""
    all_orders = client.get_orders(status='open')
    result = []
    for o in all_orders:
        if hasattr(o, 'legs') and o.legs:
            if (
                symbol.upper() in o.legs[0]['symbol'].upper()
                and o.legs[0]['side'] == 'sell_to_open'
                and side in o.legs[0]['symbol'].lower()
            ):
                result.append(o)
    return result

# ---- MAIN PUT LOGIC ----

with open("artifacts/data/signals.json", "r") as f:
    signals = json.load(f)

for buy in signals.get("buys", []):
    symbol = buy['ticker']
    strike = float(buy['strike'])
    expiry = buy['expiration']
    option_symbol = find_put_contract(symbol, strike, expiry)
    if not option_symbol:
        print(f"[PUT] No contract found for {symbol} {strike} {expiry}")
        continue

    filled_puts = open_option_positions(symbol, "put")
    pending_puts = pending_option_orders(symbol, "put")

    # Rule: If a filled PUT exists, do nothing
    if filled_puts:
        print(f"[PUT] Already have filled put for {symbol}, skipping.")
        continue

    # Rule: If matching pending PUT exists, do nothing
    already_pending = [
        o for o in pending_puts
        if o.legs[0]['symbol'] == option_symbol and float(o.legs[0]['strike_price']) == strike and o.legs[0]['expiration_date'] == expiry
    ]
    if already_pending:
        print(f"[PUT] Pending put already exists for {symbol}, skipping.")
        continue

    # Rule: If unrelated pending PUT exists, cancel it then place new
    for o in pending_puts:
        print(f"[PUT] Cancelling outdated pending put for {symbol}: {o.id}")
        client.cancel_order(o.id)

    print(f"[PUT] Selling put for {symbol} {expiry} ${strike}")
    put_order_data = {
        "symbol": option_symbol,
        "qty": 1,
        "side": "sell",
        "type": "market",
        "time_in_force": "day",
        "asset_class": "option"
    }
    response = client.submit_order(put_order_data)
    print(response)

# ---- ASSIGNMENT LOGIC (SELL CALLS) ----

def write_calls_after_assignment():
    positions = client.get_all_positions()
    for pos in positions:
        # If we hold assigned stock and no open call, sell covered call at 10% higher strike
        if pos.asset_class == "us_equity" and int(float(pos.qty)) > 0:
            symbol = pos.symbol
            cost_basis = float(pos.avg_entry_price)
            call_strike = round(cost_basis * 1.1, 2)
            call_option_symbol = find_call_contract(symbol, call_strike)
            if not call_option_symbol:
                print(f"[CALL] No call found for {symbol} at strike >= {call_strike}")
                continue

            if open_option_positions(symbol, "call") or pending_option_orders(symbol, "call"):
                print(f"[CALL] Already have call position or open order for {symbol}, skipping.")
                continue

            print(f"[CALL] Selling call for {symbol} at strike >= {call_strike}")
            call_order_data = {
                "symbol": call_option_symbol,
                "qty": 1,
                "side": "sell",
                "type": "market",
                "time_in_force": "day",
                "asset_class": "option"
            }
            response = client.submit_order(call_order_data)
            print(response)

# To run call-writing logic, uncomment the following:
# write_calls_after_assignment()
