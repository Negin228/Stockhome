import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, AssetStatus, ContractType

# Enter your Alpaca keys
API_KEY = os.environ["APCA_API_KEY_ID"]
API_SECRET = os.environ["APCA_API_SECRET_KEY"]

client = TradingClient(API_KEY, API_SECRET, paper=True)

def find_put_contract(symbol, strike, expiry):
    req = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status=AssetStatus.ACTIVE,
        contract_type=ContractType.PUT,
        expiration_date=expiry,
        strike_price=strike
    )
    contracts = client.get_option_contracts(req)
    for contract in contracts.option_contracts:
        if contract.strike_price == strike and contract.expiration_date == expiry:
            return contract.symbol
    return None

def place_put_order(option_symbol, qty):
    order_req = MarketOrderRequest(
        symbol=option_symbol,
        qty=qty,
        side=OrderSide.BUY
    )
    order = client.submit_order(order_req)
    return order

if __name__ == "__main__":
    # Example usage for SPY 450 strike expiring 2025-11-21
    symbol = "SPY"
    strike = 450
    expiry = "2025-11-21"
    option_symbol = find_put_contract(symbol, strike, expiry)
    if option_symbol:
        print("Found contract:", option_symbol)
        order_response = place_put_order(option_symbol, qty=1)
        print("Order submitted:", order_response)
    else:
        print("No contract found")
