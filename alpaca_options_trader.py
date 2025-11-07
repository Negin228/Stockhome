import os
import json
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus, ContractType

API_KEY = os.environ["APCA_API_KEY_ID"]
API_SECRET = os.environ["APCA_API_SECRET_KEY"]
client = TradingClient(API_KEY, API_SECRET, paper=True)

def get_put_contract_symbol(symbol, strike, expiry):
    expiry_formatted = datetime.strptime(expiry, '%b %d, %Y').strftime('%Y-%m-%d')
    req = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status=AssetStatus.ACTIVE,
        contract_type=ContractType.PUT,
        expiration_date=expiry_formatted
    )
    response = client.get_option_contracts(req)
    for contract in response.option_contracts:
        if float(contract.strike_price) == float(strike) and contract.expiration_date == expiry_formatted:
            return contract.symbol
    return None

def has_active_put_position(symbol):
    positions = client.get_all_positions()
    for p in positions:
        # Short position; match symbol (partial if contract symbols are longer)
        if symbol.upper() in p.symbol.split()[0] and p.asset_class == "option" and p.side == "short" and "p" in p.symbol.lower():
            return True
    return False

def get_pending_put_orders(symbol):
    pending = []
    for o in client.get_orders(status='open'):
        if hasattr(o, 'legs') and o.legs:
            option_sym = o.legs[0]['symbol']
            if symbol.upper() in option_sym and o.legs[0]['side'] == 'sell_to_open' and "p" in option_sym.lower():
                pending.append(o)
    return pending

def pending_order_matches(pending, target_symbol, target_strike, target_expiry):
    for o in pending:
        leg = o.legs[0]
        # check symbol, strike, expiry—these field names may differ, adjust if needed
        if (
            leg['symbol'] == target_symbol
            and float(leg['strike_price']) == float(target_strike)
            and leg['expiration_date'] == target_expiry
        ):
            return True
    return False

def cancel_all_pending_orders(pending):
    for o in pending:
        print(f"[Put] Cancelling pending order {o.id}")
        client.cancel_order(o.id)

def place_put_sell_order(option_symbol):
    order_data = {
        'symbol': option_symbol,
        'qty': 1,
        'side': 'sell',  # SELL to OPEN (short put)
        'type': 'market',
        'time_in_force': 'day',
        'asset_class': 'option'
    }
    resp = client.submit_order(order_data)
    print(f"[Put] Sell order submitted: {resp}")

# --- MAIN LOGIC ---

with open("artifacts/data/signals.json", "r") as f:
    signals = json.load(f)

for buy in signals.get("buys", []):
    symbol = buy["ticker"]
    strike = float(buy["put"]["strike"])
    expiry = buy["put"]["expiration"]

    print(f"\nProcessing {symbol} {strike} {expiry}")

    # Find options contract symbol
    option_symbol = get_put_contract_symbol(symbol, strike, expiry)
    if not option_symbol:
        print(f"[Put] Contract not found, skipping.")
        continue

    # Check for active short put position
    if has_active_put_position(symbol):
        print(f"[Put] Already have an active short put for {symbol}. Skipping.")
        continue

    # Check pending orders
    pending = get_pending_put_orders(symbol)
    if pending_order_matches(pending, option_symbol, strike, expiry):
        print(f"[Put] Matching pending order already exists. Skipping.")
        continue

    if pending:
        print(f"[Put] Old pending put orders found; cancelling all before submitting new order.")
        cancel_all_pending_orders(pending)

    print(f"[Put] Placing new sell-to-open put option for {symbol} {strike} {expiry}")
    place_put_sell_order(option_symbol)
