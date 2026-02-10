import os
import json
import datetime
import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
    AssetClass,
    QueryOrderStatus,
)
from alpaca.trading.requests import (
    OptionLegRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)

ORDER_QTY = 4
# --- Alpaca market data (alpaca-py) ---
# Options quotes for validation + stock latest trade for live-ish price
try:
    from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
    from alpaca.data.requests import OptionLatestQuoteRequest, StockLatestTradeRequest
except Exception:
    OptionHistoricalDataClient = None
    OptionLatestQuoteRequest = None
    StockHistoricalDataClient = None
    StockLatestTradeRequest = None


# -------------------------
# CONFIG
# -------------------------
ALPACA_KEY = os.getenv("ALPACA_NISHANTMEAN_KEY")
ALPACA_SECRET = os.getenv("ALPACA_NISHANTMEAN_SECRET")

if not ALPACA_KEY or not ALPACA_SECRET:
    raise ValueError("Alpaca API keys not found in environment variables.")

JSON_PATH = "data/spreads.json"
LOG_FILE = "trading_report.txt"

# Re-entry memory: allow another order if price is 5% lower than last trade price
STATE_PATH = "data/last_trade_price.json"

MIN_DAYS_OUT = 30  # first expiration >= 30 days out
REENTRY_DROP_PCT = 0.05  # 5% lower

# Only trade this exact recommendation
TARGET_STRATEGY = "Call Debit (Bullish)"

client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)

opt_data = OptionHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET) if OptionHistoricalDataClient else None
stk_data = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET) if StockHistoricalDataClient else None


# -------------------------
# HELPERS
# -------------------------
def log_event(message: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{ts}] {message}"
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def check_buying_power() -> float:
    acct = client.get_account()
    bp = float(acct.options_buying_power)
    log_event(f"Options Buying Power: ${bp:,.2f}")
    return bp


def width_for_price(price: float):
    """
    Spread width tiers based on stock price:
      50-100   -> $1 wide
      100-1000 -> $5 wide
      1000-5000-> $10 wide
    """
    if 50 <= price < 100:
        return 1.0
    if 100 <= price < 1000:
        return 5.0
    if 1000 <= price <= 5000:
        return 10.0
    return None  # outside desired tiers -> no trade


def half_width_limit(width: float) -> float:
    """Limit price is half the spread width."""
    return round(width / 2.0, 2)


def est_cost_dollars(width: float) -> float:
    """Approx max debit per 1-lot spread (limit * 100)."""
    return half_width_limit(width) * 100.0 * ORDER_QTY


def get_live_stock_price_alpaca(ticker: str):
    """Prefer live-ish stock price from Alpaca market data; returns None if unavailable."""
    if stk_data is None or StockLatestTradeRequest is None:
        return None
    try:
        req = StockLatestTradeRequest(symbol_or_symbols=[ticker])
        resp = stk_data.get_stock_latest_trade(req)
        t = resp.get(ticker) if hasattr(resp, "get") else None
        if t is None:
            return None
        p = getattr(t, "price", None)
        return float(p) if p is not None else None
    except Exception as e:
        log_event(f"STOCK PRICE ERROR {ticker}: {e}")
        return None


def get_alpaca_option_mid(option_symbol: str):
    """Gatekeeper: returns (mid, bid, ask) or (None, None, None) if not quotable."""
    if opt_data is None or OptionLatestQuoteRequest is None:
        return None, None, None
    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        resp = opt_data.get_option_latest_quote(req)
        q = resp.get(option_symbol) if hasattr(resp, "get") else None
        if q is None:
            return None, None, None

        bid = getattr(q, "bid_price", None)
        ask = getattr(q, "ask_price", None)
        bid = float(bid) if bid is not None else None
        ask = float(ask) if ask is not None else None

        if bid is not None and ask is not None and bid > 0 and ask > 0:
            return round((bid + ask) / 2.0, 4), bid, ask
        if bid is not None and bid > 0:
            return float(bid), bid, ask
        if ask is not None and ask > 0:
            return float(ask), bid, ask
        return None, None, None
    except Exception as e:
        log_event(f"OPTION QUOTE ERROR {option_symbol}: {e}")
        return None, None, None


def first_expiration_at_least_days_out(tk: yf.Ticker, min_days_out: int):
    """First available expiration date >= min_days_out from today."""
    today = datetime.date.today()
    options = tk.options
    if not options:
        return None
    valid = [
        e for e in options
        if (datetime.datetime.strptime(e, "%Y-%m-%d").date() - today).days >= min_days_out
    ]
    return valid[0] if valid else None


def find_call_debit_legs_exact_width(ticker: str, stock_price: float, width: float):
    """
    Call Debit Spread selection:
      - Buy call strike < stock_price
      - Sell call strike = buy_strike + width (EXACT)
      - Prefer LOWEST possible buy strike that still produces sell_strike > stock_price.
      - If none satisfy sell > price, fallback to any exact-width pair where buy < price.
      - Expiration = first available >= MIN_DAYS_OUT
    Uses yfinance to choose contracts; Alpaca quotes are checked before ordering.
    """
    tk = yf.Ticker(ticker)
    exp = first_expiration_at_least_days_out(tk, MIN_DAYS_OUT)
    if not exp:
        return None

    try:
        calls = tk.option_chain(exp).calls
    except Exception as e:
        log_event(f"YF option_chain error {ticker} {exp}: {e}")
        return None

    if calls is None or calls.empty:
        return None

    strikes = sorted(calls["strike"].dropna().unique().tolist())
    
    # DEBUG: Log available strikes
    log_event(f"DEBUG: {ticker} stock_price={stock_price:.2f}, width={width}, exp={exp}")
    log_event(f"DEBUG: Available strikes: {strikes}")
    
    strike_set = set(strikes)
    buy_candidates = [s for s in strikes if s < stock_price]
    
    log_event(f"DEBUG: Buy candidates (< {stock_price:.2f}): {buy_candidates}")

    chosen_buy = None
    chosen_sell = None

    # Prefer LOWEST buy that yields sell above stock price
    for b in buy_candidates:
        s = round(b + width, 2)  # ← FIX: Round to avoid floating point issues
        log_event(f"DEBUG: Checking buy={b}, sell={s}, in_set={s in strike_set}, sell>price={s > stock_price}")
        if s in strike_set and s > stock_price:
            chosen_buy, chosen_sell = b, s
            log_event(f"DEBUG: ✓ Found preferred pair: buy={chosen_buy}, sell={chosen_sell}")
            break

    # Fallback: any exact-width pair as long as buy < stock_price
    if chosen_buy is None:
        log_event(f"DEBUG: Trying fallback (any exact-width pair)...")
        for b in buy_candidates:
            s = round(b + width, 2)  # ← FIX: Round to avoid floating point issues
            log_event(f"DEBUG: Fallback checking buy={b}, sell={s}, in_set={s in strike_set}")
            if s in strike_set:
                chosen_buy, chosen_sell = b, s
                log_event(f"DEBUG: ✓ Found fallback pair: buy={chosen_buy}, sell={chosen_sell}")
                break

    if chosen_buy is None:
        log_event(f"DEBUG: ✗ No exact ${width} call-debit strike pair found for {ticker} at {exp}")
        return None

    l1 = calls.iloc[(calls["strike"] - chosen_buy).abs().argsort()[:1]].iloc[0]
    l2 = calls.iloc[(calls["strike"] - chosen_sell).abs().argsort()[:1]].iloc[0]

    log_event(f"DEBUG: ✓ Final selection: {ticker} buy_strike={chosen_buy} sell_strike={chosen_sell}")
    
    return {
        "ticker": ticker,
        "expiration": exp,
        "width": float(width),
        "legs": [
            {"symbol": str(l1["contractSymbol"]), "side": OrderSide.BUY, "strike": float(l1["strike"])},
            {"symbol": str(l2["contractSymbol"]), "side": OrderSide.SELL, "strike": float(l2["strike"])},
        ],
    }
def submit_call_debit_spread(ticker: str, width: float, legs: list):
    """
    Places a 2-leg MLEG limit order:
      - limit price = width/2
      - time_in_force = DAY (expires end of day)
    Uses Alpaca option quotes as a gate (both legs must have a quote).
    """
    mid1, bid1, ask1 = get_alpaca_option_mid(legs[0]["symbol"])
    mid2, bid2, ask2 = get_alpaca_option_mid(legs[1]["symbol"])
    if mid1 is None or mid2 is None:
        log_event(
            f"SKIP {ticker}: Alpaca quote missing. "
            f"L1={legs[0]['symbol']} mid={mid1} | L2={legs[1]['symbol']} mid={mid2}"
        )
        return False

    limit_price = half_width_limit(width)

    leg_reqs = [OptionLegRequest(symbol=l["symbol"], ratio_qty=1, side=l["side"]) for l in legs]

    order = LimitOrderRequest(
        symbol=None,
        qty=ORDER_QTY,
        side=OrderSide.BUY,               # Call Debit Spread = BUY
        limit_price=limit_price,
        time_in_force=TimeInForce.DAY,    # expires end of day
        order_class=OrderClass.MLEG,
        legs=leg_reqs,
        asset_class=AssetClass.US_OPTION,
    )

    try:
        client.submit_order(order)
        log_event(
            f"ORDER PLACED: {ticker} {TARGET_STRATEGY} | QTY={ORDER_QTY} | width=${width:.0f} limit=${limit_price:.2f} "
            f"| BUY K={legs[0]['strike']} ({legs[0]['symbol']}) "
            f"SELL K={legs[1]['strike']} ({legs[1]['symbol']}) "
            f"| L1 mid={mid1} (bid={bid1}, ask={ask1}) L2 mid={mid2} (bid={bid2}, ask={ask2})"
        )
        return True
    except Exception as e:
        log_event(f"ORDER ERROR {ticker}: {e}")
        return False


def get_open_order_underlyings_and_legs():
    """
    Returns:
      - open_underlyings: set of underlying tickers inferred from option symbols
      - open_leg_symbols: set of option leg symbols currently in OPEN orders
    This prevents duplicate orders while they are unfilled.
    """
    open_underlyings = set()
    open_leg_symbols = set()

    try:
        open_orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
    except Exception as e:
        log_event(f"Open orders fetch error: {e}")
        return open_underlyings, open_leg_symbols

    for o in open_orders:
        # Multi-leg orders: legs are the key
        legs = getattr(o, "legs", None) or []
        for leg in legs:
            sym = getattr(leg, "symbol", None)
            if sym:
                open_leg_symbols.add(sym)
                # Underlying ticker is the leading letters before digits in OCC sym
                underlying = "".join([c for c in sym if c.isalpha()])
                # OCC options symbols contain more letters than underlying for some formats,
                # but in practice this works well enough for blocking duplicates like AAPL...
                # Alternative: take leading alpha chars until first digit.
                u = ""
                for ch in sym:
                    if ch.isalpha():
                        u += ch
                    else:
                        break
                if u:
                    open_underlyings.add(u)

        # Single-leg orders: symbol might be on o.symbol
        osym = getattr(o, "symbol", None)
        if osym:
            open_leg_symbols.add(osym)
            u = ""
            for ch in osym:
                if ch.isalpha():
                    u += ch
                else:
                    break
            if u:
                open_underlyings.add(u)

    return open_underlyings, open_leg_symbols


# -------------------------
# MAIN
# -------------------------
def reset_and_trade():
    log_event("--- STARTING TRADE CYCLE ---")

    # Note: do NOT cancel orders automatically if you want open-order protection.
    # If you still want the old behavior, uncomment the next two lines.
    # try:
    #     client.cancel_orders()
    # except Exception as e:
    #     log_event(f"Cancel orders error: {e}")

    bp = check_buying_power()

    # Positions
    try:
        positions = client.get_all_positions()
        portfolio_symbols = [p.symbol for p in positions]
    except Exception as e:
        log_event(f"Error fetching positions: {e}")
        portfolio_symbols = []

    # Open orders (critical protection for unfilled orders)
    open_underlyings, open_leg_symbols = get_open_order_underlyings_and_legs()
    if open_underlyings:
        log_event(f"Open-order underlyings (blocked): {sorted(open_underlyings)}")

    state = load_state()

    # Load signals
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            signals = data if isinstance(data, list) else data.get("all", [])
    except FileNotFoundError:
        log_event(f"Signals file not found: {JSON_PATH}")
        return
    except Exception as e:
        log_event(f"Signals read error: {e}")
        return

    for s in signals:
        ticker = (s.get("ticker") or "").strip()
        if not ticker:
            continue

        strategy = (s.get("strategy") or "").strip()
        if (s.get("type") or "").strip().lower() != "bullish":
            continue

        # Require all three checks to pass
        pe_pass = bool(s.get("pe_check"))
        growth_pass = bool(s.get("growth_check"))
        debt_pass = bool(s.get("debt_check"))
        if not (pe_pass and growth_pass and debt_pass):
            continue

        # Block if there is an existing OPEN order for this underlying
        if ticker in open_underlyings:
            log_event(f"SKIP {ticker}: open order exists (not filled yet).")
            continue

        # Prefer live stock price from Alpaca; fallback to JSON price
        json_price = s.get("price")
        json_price = float(json_price) if json_price is not None else None
        live_price = get_live_stock_price_alpaca(ticker)
        price = live_price if (live_price is not None and live_price > 0) else json_price

        if price is None or price <= 0:
            log_event(f"SKIP {ticker}: No valid price (live and JSON missing).")
            continue

        width = width_for_price(price)
        if width is None:
            log_event(f"SKIP {ticker}: price ${price:.2f} outside width tiers.")
            continue

        # Re-entry rule if already have a position:
        already_have_position = any(ticker in sym for sym in portfolio_symbols)
        if already_have_position:
            last = state.get(ticker, {})
            last_price = float(last.get("last_price") or 0)
            if last_price <= 0:
                log_event(f"SKIP {ticker}: already in portfolio; no last_trade_price recorded for 5% re-entry check.")
                continue
            if price > last_price * (1 - REENTRY_DROP_PCT):
                log_event(
                    f"SKIP {ticker}: already in portfolio; price ${price:.2f} not >=5% below last ${last_price:.2f}."
                )
                continue
            log_event(f"RE-ENTRY OK {ticker}: price ${price:.2f} is >=5% below last ${last_price:.2f}.")

        # Buying power check based on tier width
        need = est_cost_dollars(width)
        if bp < need:
            log_event(f"SKIP {ticker}: insufficient BP. Need ~${need:.0f}, have ${bp:.0f}.")
            continue

        candidate = find_call_debit_legs_exact_width(ticker, price, width)
        if not candidate:
            continue

        legs = candidate["legs"]

        # Extra safety: if any leg symbol is already in open orders, skip
        if any(l["symbol"] in open_leg_symbols for l in legs):
            log_event(f"SKIP {ticker}: one or more option legs already in open orders.")
            continue

        success = submit_call_debit_spread(ticker, width, legs)
        if success:
            bp -= need
            state[ticker] = {
                "last_price": float(price),
                "last_ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_state(state)


if __name__ == "__main__":
    reset_and_trade()
