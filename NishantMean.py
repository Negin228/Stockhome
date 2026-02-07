import os
import json
import datetime
import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, AssetClass
from alpaca.trading.requests import OptionLegRequest, LimitOrderRequest

# --- Alpaca option quotes (alpaca-py) ---
try:
    from alpaca.data.historical import OptionHistoricalDataClient
    from alpaca.data.requests import OptionLatestQuoteRequest
except Exception as e:
    OptionHistoricalDataClient = None
    OptionLatestQuoteRequest = None


# Read secrets from environment variables
ALPACA_NISHANTMEAN_KEY = os.getenv("ALPACA_NISHANTMEAN_KEY")
ALPACA_NISHANTMEAN_SECRET = os.getenv("ALPACA_NISHANTMEAN_SECRET")

if not ALPACA_NISHANTMEAN_KEY or not ALPACA_NISHANTMEAN_SECRET:
    raise ValueError("Alpaca API keys not found in environment variables.")

JSON_PATH = "data/spreads.json"
LOG_FILE = "trading_report.txt"
MIN_STOCK_PRICE = 100.0
ENTRY_LIMIT = 2.50      # $2.50 max debit/credit per spread (=$250)
MIN_DAYS_OUT = 30

client = TradingClient(ALPACA_NISHANTMEAN_KEY, ALPACA_NISHANTMEAN_SECRET, paper=True)

# Option data client (for quotes/validation)
opt_data = None
if OptionHistoricalDataClient is not None:
    opt_data = OptionHistoricalDataClient(ALPACA_NISHANTMEAN_KEY, ALPACA_NISHANTMEAN_SECRET)


def log_event(message):
    """Timestamped reporting for your trades."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")


def check_buying_power():
    """Ensures we have at least $250 available to place the trade."""
    account = client.get_account()
    bp = float(account.options_buying_power)
    log_event(f"Current Options Buying Power: ${bp:,.2f}")
    return bp


def get_alpaca_option_mid(option_symbol: str):
    """
    Fetch latest option quote from Alpaca.
    Returns (mid, bid, ask) or (None, None, None) if unavailable.
    """
    if opt_data is None or OptionLatestQuoteRequest is None:
        return None, None, None

    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        resp = opt_data.get_option_latest_quote(req)

        # resp is typically dict-like keyed by symbol
        q = resp.get(option_symbol) if hasattr(resp, "get") else None
        if q is None:
            return None, None, None

        bid = getattr(q, "bid_price", None)
        ask = getattr(q, "ask_price", None)

        # Normalize
        bid = float(bid) if bid is not None else None
        ask = float(ask) if ask is not None else None

        if bid is not None and ask is not None and bid > 0 and ask > 0:
            return round((bid + ask) / 2.0, 4), bid, ask

        # If one side missing, still allow but mid is that side
        if bid is not None and bid > 0:
            return float(bid), bid, ask
        if ask is not None and ask > 0:
            return float(ask), bid, ask

        return None, None, None
    except Exception as e:
        log_event(f"QUOTE ERROR for {option_symbol}: {e}")
        return None, None, None


def first_expiration_at_least_days_out(tk: yf.Ticker, min_days_out: int):
    """First available expiration date >= min_days_out from today."""
    today = datetime.date.today()
    options = tk.options
    if not options:
        return None
    valid_exps = [
        e for e in options
        if (datetime.datetime.strptime(e, "%Y-%m-%d").date() - today).days >= min_days_out
    ]
    return valid_exps[0] if valid_exps else None


def find_leg_symbols(ticker_sym, current_price, strategy):
    """Uses yfinance to pick candidate legs; Alpaca used later for quotes/validation."""
    log_event(f"DEBUG: Searching legs for {ticker_sym} using strategy: {strategy}")
    tk = yf.Ticker(ticker_sym)

    target_exp = first_expiration_at_least_days_out(tk, MIN_DAYS_OUT)
    if not target_exp:
        return None

    try:
        opts = tk.option_chain(target_exp)
    except Exception as e:
        log_event(f"DEBUG: option_chain failed for {ticker_sym} {target_exp}: {e}")
        return None

    strat_upper = strategy.upper()

    # ✅ ONLY CHANGE: Call Debit Spread uses EXACT width selection
    if "CALL" in strat_upper and "DEBIT" in strat_upper:
        chain = opts.calls
        if chain is None or chain.empty:
            return None

        width = 5.0  # exact width for price ~180 (your 100–1000 tier)
        strikes = sorted(chain["strike"].dropna().unique().tolist())
        strike_set = set(strikes)

        # candidate buy strikes: must be below current price
        buy_candidates = [s for s in strikes if s < current_price]

        # Prefer the LOWEST possible buy strike that has an exact +$5 partner
        # (and keeps sell strike above current price, per your earlier requirement)
        chosen_buy = None
        chosen_sell = None
        for b in buy_candidates:
            s = b + width
            if s in strike_set and s > current_price:
                chosen_buy, chosen_sell = b, s
                break

        # If none found with sell > price, fall back to any exact-width pair
        # as long as buy < price (per your latest message).
        if chosen_buy is None:
            for b in buy_candidates:
                s = b + width
                if s in strike_set:
                    chosen_buy, chosen_sell = b, s
                    break

        if chosen_buy is None:
            log_event(f"DEBUG: No exact ${width} call-debit strike pair found for {ticker_sym} at {target_exp}")
            return None

        # Get the exact contracts for those strikes
        l1 = chain.iloc[(chain["strike"] - chosen_buy).abs().argsort()[:1]].iloc[0]
        l2 = chain.iloc[(chain["strike"] - chosen_sell).abs().argsort()[:1]].iloc[0]

        return {
            "ticker": ticker_sym,
            "expiration": target_exp,
            "strategy": strategy,
            "legs": [
                {"symbol": str(l1["contractSymbol"]), "side": OrderSide.BUY, "strike": float(l1["strike"])},
                {"symbol": str(l2["contractSymbol"]), "side": OrderSide.SELL, "strike": float(l2["strike"])},
            ]
        }


def submit_spread_order(ticker, strategy, legs):
    """
    Submits order priced using Alpaca option quotes (NOT yfinance).
    - Computes mid for each leg from Alpaca
    - Computes spread 'mark' as abs(mid1 - mid2)
    - Caps price at ENTRY_LIMIT
    """
    # --- Pull real quotes from Alpaca (validation + pricing) ---
    mid1, bid1, ask1 = get_alpaca_option_mid(legs[0]["symbol"])
    mid2, bid2, ask2 = get_alpaca_option_mid(legs[1]["symbol"])

    # If we can't quote both legs, skip (prevents non-tradable / stale yfinance legs)
    if mid1 is None or mid2 is None:
        log_event(
            f"SKIP {ticker}: Alpaca quote missing. "
            f"L1={legs[0]['symbol']} mid={mid1} | L2={legs[1]['symbol']} mid={mid2}"
        )
        return False

    # --- Dynamic Pricing using Alpaca mids ---
    mark = round(abs(mid1 - mid2), 2)
    final_price = round(min(mark, ENTRY_LIMIT), 2)

    leg_reqs = [OptionLegRequest(symbol=l["symbol"], ratio_qty=1, side=l["side"]) for l in legs]

    order_data = LimitOrderRequest(
        symbol=None,
        limit_price=final_price,
        qty=1,
        side=OrderSide.BUY if "DEBIT" in strategy.upper() else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,     # expires end of day
        order_class=OrderClass.MLEG,
        legs=leg_reqs,
        asset_class=AssetClass.US_OPTION
    )

    try:
        client.submit_order(order_data)
        log_event(
            f"ORDER PLACED: {ticker} {strategy} @ ${final_price} (mark=${mark}) | "
            f"L1 mid={mid1} (bid={bid1}, ask={ask1}) | L2 mid={mid2} (bid={bid2}, ask={ask2})"
        )
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
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            signals = data if isinstance(data, list) else data.get("all", [])
    except FileNotFoundError:
        return

    for s in signals:
        ticker, price, strategy = s["ticker"], float(s["price"]), s["strategy"]

        # Keep your existing filter (only bull call debit + bull put credit)
        if not (("CALL" in strategy.upper() and "DEBIT" in strategy.upper()) or
                ("PUT" in strategy.upper() and "CREDIT" in strategy.upper())):
            continue

        if price < MIN_STOCK_PRICE:
            continue

        # Portfolio check (unchanged behavior)
        if any(ticker in pos for pos in portfolio):
            continue

        if bp < 250:
            continue

        candidate = find_leg_symbols(ticker, price, strategy)
        if not candidate:
            continue

        success = submit_spread_order(ticker, strategy, candidate["legs"])
        if success:
            bp -= 250


if __name__ == "__main__":
    reset_and_trade()

