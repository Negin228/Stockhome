"""
put_ladder_scanner.py
=====================
Put Ladder Strategy Scanner — integrates with your existing stack
(yfinance + Finnhub + ta + local cache).

Formula
-------
  δ         = (S - K) / S * 100          # OTM%, how far strike is below stock price
  premium%  = put_mid_price / S * 100    # option income as % of stock price
  score(n)  = n * P_min + δ              # n = weeks to expiry

Entry condition (smallest n where BOTH hold):
  1.  premium%(n) >= P_MIN   (default 0.75%)
  2.  score(n)    >= SCORE_MIN (default 10.0)

Ladder (once anchor week n is found):
  n+0: strike K
  n+1: strike K - LADDER_STEP
  n+2: strike K - 2*LADDER_STEP
  ...up to n+MAX_LADDER_LEGS

Weekly re-evaluation (call this function each week):
  - If not assigned: re-run entry test on new week m.
    If passes → sell new anchor at K_m, rebuild ladder.
  - If assigned: do nothing (you own 100 shares at strike).

Filters
-------
  - RSI(14) < RSI_THRESHOLD   (default 30)
  - Market cap > MCAP_MIN_B   (default $100B)
  - Weekly options available

Usage
-----
  python put_ladder_scanner.py
  python put_ladder_scanner.py --tickers AAPL,MSFT,NVDA
  python put_ladder_scanner.py --tickers AAPL --min-premium 0.5 --min-score 8
  python put_ladder_scanner.py --output json   # also writes artifacts/data/put_ladder.json
"""

import os
import json
import datetime
import time
import argparse
import logging
from logging.handlers import RotatingFileHandler

import numpy as np
import pandas as pd
import pytz
import yfinance as yf
import finnhub
import ta
from dateutil.parser import parse

# ── try to import your config; fall back gracefully if running standalone ──────
try:
    import config
    DATA_DIR       = config.DATA_DIR
    LOG_DIR        = config.LOG_DIR
    LOG_FILE       = config.LOG_FILE
    FINNHUB_KEY    = os.getenv("API_KEY", "")
    BASE_TICKERS   = config.tickers if hasattr(config, "tickers") else []
    RSI_OVERSOLD   = getattr(config, "RSI_OVERSOLD", 30)
except ImportError:
    DATA_DIR       = "data"
    LOG_DIR        = "logs"
    LOG_FILE       = "put_ladder.log"
    FINNHUB_KEY    = os.getenv("API_KEY", "")
    BASE_TICKERS   = []
    RSI_OVERSOLD   = 30

# ── Strategy parameters (override via CLI) ──────────────────────────────────
P_MIN           = 0.75    # minimum premium% per week
SCORE_MIN       = 10.0    # minimum n*P_MIN + δ to qualify
LADDER_STEP     = 5.0     # $5 lower strike per subsequent week
MAX_LADDER_LEGS = 6       # how many weeks in the ladder (n through n+MAX)
MAX_DTE         = 49      # look no further than 7 weeks out
MCAP_MIN_B      = 100.0   # minimum market cap in $B

# ── Cache dirs (mirror your existing pattern) ────────────────────────────────
FUND_DIR            = "data/fundamentals"
COMPANY_CACHE_DIR   = "data/company_names"
OPTIONS_CACHE_DIR   = "data/options_availability"
CACHE_FUND_HOURS    = 24
CACHE_OPTIONS_HOURS = 24

for d in [DATA_DIR, LOG_DIR, FUND_DIR, COMPANY_CACHE_DIR, OPTIONS_CACHE_DIR,
          "artifacts/data"]:
    os.makedirs(d, exist_ok=True)

# ── Logging (same rotating pattern as your main script) ─────────────────────
log_path = os.path.join(LOG_DIR, LOG_FILE)
logger = logging.getLogger("PutLadder")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)

pacific = pytz.timezone("US/Pacific")
dt_pacific = datetime.datetime.now(pacific)

# ── API clients (same as your existing code) ─────────────────────────────────
finnhub_client = finnhub.Client(api_key=FINNHUB_KEY) if FINNHUB_KEY else None


# =============================================================================
# HELPERS  (ported directly from your existing helpers)
# =============================================================================

def normalize_tickers(x):
    if x is None:
        return []
    parts = x.split(",") if isinstance(x, str) else list(x)
    seen, out = set(), []
    for t in parts:
        t = str(t).strip().upper()
        if t and t not in seen:
            out.append(t); seen.add(t)
    return out

def scalar(x):
    if isinstance(x, pd.Series):
        return float(x.iloc[-1])
    if hasattr(x, "iloc"):
        return float(x.iloc[0])
    return float(x)

def format_market_cap(mcap):
    try:
        m = float(mcap)
        if np.isnan(m) or m <= 0:
            return ""
        for div, suffix, dec in [(1e12,"T",2),(1e9,"B",2),(1e6,"M",1),(1e3,"K",0)]:
            if m >= div:
                return f"{m/div:,.{dec}f}{suffix}"
        return f"{m:,.0f}"
    except Exception:
        return ""


# =============================================================================
# OPTIONS HELPERS  (same logic as your existing code)
# =============================================================================

def option_expiration_type(expiration_str: str) -> str:
    try:
        d = parse(expiration_str).date()
        if d.weekday() == 5:          # Saturday → treat as Friday
            d -= datetime.timedelta(days=1)
        if d.weekday() == 4 and 15 <= d.day <= 21:
            return "MONTHLY"
        if d.weekday() == 4:
            return "WEEKLY"
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"

def option_availability(expiration_list):
    types = [option_expiration_type(e) for e in expiration_list]
    return {
        "weekly_available":  any(t == "WEEKLY"  for t in types),
        "monthly_available": any(t == "MONTHLY" for t in types),
    }

def fetch_options_availability_cached(symbol):
    """Identical caching pattern to your existing function."""
    path = os.path.join(OPTIONS_CACHE_DIR, f"{symbol}.json")
    if os.path.exists(path):
        if time.time() - os.path.getmtime(path) < CACHE_OPTIONS_HOURS * 3600:
            try:
                d = json.load(open(path))
                return {"weekly_available": bool(d.get("weekly_available")),
                        "monthly_available": bool(d.get("monthly_available"))}
            except Exception:
                pass
    out = {"weekly_available": False, "monthly_available": False}
    try:
        exps = yf.Ticker(symbol).options or []
        if exps:
            avail = option_availability(exps)
            out = {"weekly_available": bool(avail["weekly_available"]),
                   "monthly_available": bool(avail["monthly_available"])}
    except Exception as e:
        logger.warning(f"Options availability error for {symbol}: {e}")
    try:
        json.dump(out, open(path, "w"))
    except Exception:
        pass
    return out


# =============================================================================
# PRICE  (same priority chain as your get_live_price)
# =============================================================================

def get_live_price(symbol, fallback_close, retries=2, wait=1):
    if finnhub_client:
        for attempt in range(retries):
            try:
                q = finnhub_client.quote(symbol)
                price = q.get("c")
                if price and price > 0:
                    logger.info(f"Live price {symbol} (Finnhub): {price}")
                    return float(price)
            except Exception as e:
                logger.warning(f"Finnhub attempt {attempt+1} for {symbol}: {e}")
                if attempt < retries - 1:
                    time.sleep(wait)
    try:
        price = yf.Ticker(symbol).fast_info.get("lastPrice")
        if price and price > 0:
            logger.info(f"Live price {symbol} (yfinance): {price}")
            return float(price)
    except Exception as e:
        logger.warning(f"yfinance fast_info failed for {symbol}: {e}")
    logger.warning(f"Using fallback close for {symbol}: {fallback_close}")
    try:
        return float(fallback_close)
    except Exception:
        return None


# =============================================================================
# COMPANY NAME  (same cache as yours)
# =============================================================================

def fetch_company_name_cached(symbol):
    path = os.path.join(COMPANY_CACHE_DIR, f"{symbol}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        try:
            return json.load(open(path)).get("name", "")
        except Exception:
            pass
    try:
        info = yf.Ticker(symbol).info
        name = info.get("shortName") or info.get("longName") or ""
        json.dump({"name": name}, open(path, "w"))
        return name
    except Exception:
        return ""


# =============================================================================
# FUNDAMENTALS  (same cache as yours)
# =============================================================================

def fetch_fundamentals_cached(symbol):
    path = os.path.join(FUND_DIR, f"{symbol}.json")
    if os.path.exists(path):
        if time.time() - os.path.getmtime(path) < CACHE_FUND_HOURS * 3600:
            try:
                data = json.load(open(path))
                if data.get("market_cap"):
                    return data
            except Exception:
                pass

    market_cap = None
    try:
        ticker = yf.Ticker(symbol)
        if hasattr(ticker, "fast_info"):
            market_cap = ticker.fast_info.get("market_cap")
        info = ticker.info or {}
        if not market_cap:
            market_cap = info.get("marketCap")
    except Exception as e:
        logger.warning(f"Fundamentals error for {symbol}: {e}")

    if (not market_cap) and finnhub_client:
        try:
            prof = finnhub_client.company_profile2(symbol=symbol) or {}
            mc_m = prof.get("marketCapitalization")
            if mc_m and mc_m > 0:
                market_cap = float(mc_m) * 1_000_000
        except Exception as e:
            logger.warning(f"Finnhub fundamentals fallback for {symbol}: {e}")

    data = {"market_cap": market_cap}
    if market_cap and market_cap > 0:
        try:
            json.dump(data, open(path, "w"))
        except Exception:
            pass
    return data


# =============================================================================
# HISTORY + RSI  (same fetch_cached_history + calculate_indicators pattern)
# =============================================================================

def fetch_cached_history(symbol, period="2y"):
    path = os.path.join(DATA_DIR, f"{symbol}.csv")
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            for c in ["Open", "High", "Low", "Close", "Volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if not df.empty and len(df) >= 200:
                return df
        except Exception as e:
            logger.warning(f"Cache read failed for {symbol}: {e}")
    df = yf.download(symbol, period=period, progress=False)
    if not df.empty:
        try:
            df.to_csv(path)
        except Exception:
            pass
    return df

def get_rsi(df) -> float:
    """Return latest RSI(14) using the ta library, same as your calculate_indicators."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].iloc[:, 0].astype(float)
        else:
            close = df["Close"].astype(float)
        rsi_series = ta.momentum.RSIIndicator(close=close, window=14).rsi()
        return float(rsi_series.iloc[-1])
    except Exception as e:
        logger.warning(f"RSI calculation error: {e}")
        return float("nan")


# =============================================================================
# PUT CHAIN FETCH  (adapted from your fetch_puts — same structure)
# =============================================================================

def fetch_weekly_puts(symbol: str, price: float) -> list[dict]:
    """
    Fetch all put options within MAX_DTE days.
    Returns list of dicts with keys:
        expiration, strike, premium, exp_type, dte,
        weeks_out, delta_pct, premium_pct, score
    Only includes puts where strike < price (OTM).
    """
    rows = []
    try:
        ticker   = yf.Ticker(symbol)
        today    = dt_pacific.replace(tzinfo=None)
        all_exps = getattr(ticker, "options", []) or []

        valid_exps = []
        for d in all_exps:
            try:
                days = (parse(d) - today).days
                if 0 < days <= MAX_DTE:
                    valid_exps.append((d, days))
            except Exception:
                continue

        if not valid_exps:
            return []

        for exp_str, dte in valid_exps:
            exp_type  = option_expiration_type(exp_str)
            weeks_out = max(1, round(dte / 7))   # approximate weeks

            try:
                chain = ticker.option_chain(exp_str)
                if chain.puts.empty:
                    continue
                puts = chain.puts.copy()
            except Exception as e:
                logger.warning(f"Option chain error {symbol} {exp_str}: {e}")
                continue

            for _, row in puts.iterrows():
                strike = row.get("strike")
                if not strike or pd.isna(strike) or float(strike) >= price:
                    continue  # only OTM puts

                bid  = row.get("bid")
                ask  = row.get("ask")
                last = row.get("lastPrice")
                try:
                    if pd.notna(bid) and pd.notna(ask) and (bid + ask) > 0:
                        premium = (float(bid) + float(ask)) / 2
                    else:
                        premium = float(last) if last and pd.notna(last) else None
                except Exception:
                    premium = None

                if not premium or premium <= 0:
                    continue

                strike     = float(strike)
                delta_pct  = (price - strike) / price * 100
                prem_pct   = premium / price * 100
                score      = weeks_out * P_MIN + delta_pct

                rows.append({
                    "expiration":  exp_str,
                    "exp_type":    exp_type,
                    "dte":         dte,
                    "weeks_out":   weeks_out,
                    "strike":      strike,
                    "premium":     round(premium, 2),
                    "delta_pct":   round(delta_pct, 2),
                    "premium_pct": round(prem_pct, 4),
                    "score":       round(score, 2),
                })

    except Exception as e:
        logger.warning(f"fetch_weekly_puts failed for {symbol}: {e}")

    return rows


# =============================================================================
# LADDER BUILDER
# =============================================================================

def build_ladder(puts: list[dict], price: float,
                 p_min: float = P_MIN,
                 score_min: float = SCORE_MIN,
                 ladder_step: float = LADDER_STEP) -> dict | None:
    """
    Given all OTM puts for a symbol, find the anchor week and build the ladder.

    Returns:
      {
        "qualifies":   True/False,
        "anchor":      { expiration, weeks_out, strike, premium, delta_pct,
                         premium_pct, score },
        "ladder":      [ { week_label, expiration, weeks_out, strike,
                           premium, delta_pct_adjusted, premium_pct,
                           score_adjusted, is_anchor } … ],
        "fail_reason": "…"   # only when qualifies=False
      }
    """
    if not puts:
        return {"qualifies": False, "fail_reason": "No OTM puts found in range"}

    # ── Group by weeks_out; for each week pick the put closest to 10-20% OTM ──
    by_week: dict[int, list] = {}
    for p in puts:
        by_week.setdefault(p["weeks_out"], []).append(p)

    # For each week, select the single best candidate:
    # prefer the strike that maximises premium_pct while still being OTM (not ITM)
    week_reps: list[dict] = []
    for wk in sorted(by_week.keys()):
        candidates = sorted(by_week[wk], key=lambda x: x["premium_pct"], reverse=True)
        # keep first candidate with delta_pct between 5% and 30% (sensible OTM zone)
        chosen = next(
            (c for c in candidates if 5 <= c["delta_pct"] <= 30),
            candidates[0]  # fallback: best premium regardless of zone
        )
        week_reps.append(chosen)

    # ── Find the anchor: smallest n where BOTH conditions hold ─────────────────
    anchor = None
    for rep in week_reps:
        prem_ok  = rep["premium_pct"] >= p_min
        score_ok = rep["score"] >= score_min
        if prem_ok and score_ok:
            anchor = rep
            break   # smallest qualifying n

    if anchor is None:
        # Explain why: find the week closest to qualifying
        best = max(week_reps, key=lambda x: x["score"])
        return {
            "qualifies":   False,
            "fail_reason": (
                f"No week satisfies both conditions. "
                f"Best score={best['score']:.1f} at week {best['weeks_out']} "
                f"(need {score_min}); best premium%={best['premium_pct']:.3f}% "
                f"(need {p_min}%)"
            ),
            "week_reps": week_reps,
        }

    # ── Build ladder: anchor + subsequent weeks at $LADDER_STEP lower each ─────
    anchor_idx  = week_reps.index(anchor)
    ladder_legs = week_reps[anchor_idx:]

    ladder = []
    for i, week in enumerate(ladder_legs[:MAX_LADDER_LEGS + 1]):
        adj_strike    = round(anchor["strike"] - i * ladder_step, 2)
        adj_delta_pct = round((price - adj_strike) / price * 100, 2)
        adj_score     = round(week["weeks_out"] * p_min + adj_delta_pct, 2)

        ladder.append({
            "week_label":        "★ ANCHOR" if i == 0 else f"+{i}w",
            "expiration":        week["expiration"],
            "weeks_out":         week["weeks_out"],
            "strike":            adj_strike,
            "premium":           week["premium"],        # actual market premium at that expiry
            "premium_pct":       round(week["premium_pct"], 3),
            "delta_pct":         adj_delta_pct,          # recalculated for adjusted strike
            "score":             adj_score,
            "qualifies":         week["premium_pct"] >= p_min and adj_score >= score_min,
            "is_anchor":         i == 0,
        })

    return {
        "qualifies": True,
        "anchor":    {k: anchor[k] for k in
                      ("expiration","weeks_out","strike","premium",
                       "delta_pct","premium_pct","score")},
        "ladder":    ladder,
    }


# =============================================================================
# RE-EVALUATION LOGIC (weekly call)
# =============================================================================

def reevaluate(symbol: str,
               p_min: float  = P_MIN,
               score_min: float = SCORE_MIN,
               ladder_step: float = LADDER_STEP) -> dict:
    """
    Call this every week for open positions.
    Returns:
      {
        "action":    "NEW_ANCHOR" | "NO_SIGNAL" | "ASSIGNED_DO_NOTHING" | "ERROR",
        "ticker":    symbol,
        "result":    <full ladder dict>  # only when action == "NEW_ANCHOR"
        "message":   "…"
      }
    """
    try:
        df    = fetch_cached_history(symbol)
        if df.empty or len(df) < 14:
            return {"action": "ERROR", "ticker": symbol, "message": "Insufficient history"}
        close = scalar(df["Close"].iloc[-1])
        price = get_live_price(symbol, close)
        if not price:
            return {"action": "ERROR", "ticker": symbol, "message": "Could not get price"}

        rsi = get_rsi(df)
        if rsi >= RSI_OVERSOLD:
            return {
                "action":  "NO_SIGNAL",
                "ticker":  symbol,
                "message": f"RSI {rsi:.1f} no longer oversold (need < {RSI_OVERSOLD})"
            }

        puts   = fetch_weekly_puts(symbol, price)
        result = build_ladder(puts, price, p_min, score_min, ladder_step)

        if result and result["qualifies"]:
            return {
                "action":  "NEW_ANCHOR",
                "ticker":  symbol,
                "price":   price,
                "rsi":     rsi,
                "message": f"New anchor at week {result['anchor']['weeks_out']}, "
                           f"strike ${result['anchor']['strike']:.2f}",
                "result":  result,
            }
        else:
            reason = result.get("fail_reason", "Unknown") if result else "No puts found"
            return {
                "action":  "NO_SIGNAL",
                "ticker":  symbol,
                "message": f"Formula not satisfied — {reason}"
            }
    except Exception as e:
        logger.exception(f"reevaluate error for {symbol}: {e}")
        return {"action": "ERROR", "ticker": symbol, "message": str(e)}


# =============================================================================
# MAIN SCANNER JOB
# =============================================================================

def scan(tickers: list[str],
         p_min: float       = P_MIN,
         score_min: float   = SCORE_MIN,
         ladder_step: float = LADDER_STEP,
         output: str        = "console") -> list[dict]:
    """
    Full scan: for each ticker apply all 4 filters then build the ladder.
    Returns list of result dicts (all tickers, qualifying and not).
    """
    results = []

    for symbol in tickers:
        symbol = symbol.strip().upper()
        logger.info(f"Scanning {symbol}…")

        rec = {
            "ticker":           symbol,
            "company":          "",
            "price":            None,
            "rsi":              None,
            "market_cap_b":     None,
            "market_cap_str":   "",
            "weekly_available": False,
            "filters_pass":     False,
            "filter_fail":      [],
            "ladder_result":    None,
            "qualifying":       False,
        }

        try:
            # ── 1. Price history + RSI ────────────────────────────────────────
            df = fetch_cached_history(symbol)
            if df.empty or len(df) < 200:
                rec["filter_fail"].append(f"Insufficient history ({len(df)} rows)")
                results.append(rec); continue

            close = scalar(df["Close"].iloc[-1])
            price = get_live_price(symbol, close)
            if not price:
                rec["filter_fail"].append("Could not fetch price"); results.append(rec); continue

            rec["price"] = round(price, 2)
            rec["rsi"]   = round(get_rsi(df), 1)

            # ── 2. Company name ───────────────────────────────────────────────
            rec["company"] = fetch_company_name_cached(symbol)

            # ── 3. Market cap filter ──────────────────────────────────────────
            funds      = fetch_fundamentals_cached(symbol) or {}
            market_cap = funds.get("market_cap") or 0.0
            mcap_b     = market_cap / 1e9 if market_cap else 0.0
            rec["market_cap_b"]   = round(mcap_b, 1)
            rec["market_cap_str"] = format_market_cap(market_cap)

            fail = []
            if rec["rsi"] >= RSI_OVERSOLD:
                fail.append(f"RSI {rec['rsi']:.1f} ≥ {RSI_OVERSOLD} (not oversold)")
            if mcap_b < MCAP_MIN_B:
                fail.append(f"Market cap ${mcap_b:.0f}B < ${MCAP_MIN_B:.0f}B")

            # ── 4. Weekly options availability filter ─────────────────────────
            opts_avail = fetch_options_availability_cached(symbol)
            rec["weekly_available"] = bool(opts_avail.get("weekly_available"))
            if not rec["weekly_available"]:
                fail.append("No weekly options")

            if fail:
                rec["filter_fail"] = fail
                results.append(rec); continue

            rec["filters_pass"] = True

            # ── 5. Fetch put chain + build ladder ─────────────────────────────
            logger.info(f"  {symbol}: filters passed. Fetching put chain…")
            puts   = fetch_weekly_puts(symbol, price)
            result = build_ladder(puts, price, p_min, score_min, ladder_step)

            rec["ladder_result"] = result
            rec["qualifying"]    = bool(result and result.get("qualifies"))

            if rec["qualifying"]:
                anc = result["anchor"]
                logger.info(
                    f"  ✓ {symbol}: anchor=week{anc['weeks_out']} "
                    f"strike=${anc['strike']:.2f} score={anc['score']:.1f}"
                )
            else:
                reason = result.get("fail_reason","") if result else "No puts"
                logger.info(f"  ✗ {symbol}: {reason}")

        except Exception as e:
            logger.exception(f"Error processing {symbol}: {e}")
            rec["filter_fail"].append(str(e))

        results.append(rec)

    return results


# =============================================================================
# OUTPUT FORMATTERS
# =============================================================================

def print_console(results: list[dict], p_min: float, score_min: float):
    qualifying = [r for r in results if r["qualifying"]]
    filtered   = [r for r in results if r["filters_pass"] and not r["qualifying"]]
    skipped    = [r for r in results if not r["filters_pass"]]

    ts = dt_pacific.strftime("%m-%d-%Y %H:%M PT")
    W  = 72
    print(f"\n{'═'*W}")
    print(f"  PUT LADDER SCANNER  ·  {ts}")
    print(f"  Formula: premium%(n) ≥ {p_min}%  AND  n×{p_min} + δ ≥ {score_min}%")
    print(f"  Filters: RSI < {RSI_OVERSOLD}  ·  MCap > ${MCAP_MIN_B:.0f}B  ·  weekly options")
    print(f"{'═'*W}\n")

    if qualifying:
        print(f"  ✅  {len(qualifying)} QUALIFYING TRADE{'S' if len(qualifying)!=1 else ''}\n")
        for r in sorted(qualifying, key=lambda x: x["rsi"]):
            anc  = r["ladder_result"]["anchor"]
            lad  = r["ladder_result"]["ladder"]
            mcap = r["market_cap_str"] or f"${r['market_cap_b']:.0f}B"
            print(f"  ┌─ {r['ticker']:6s}  {r['company']}")
            print(f"  │  Price ${r['price']:.2f}  ·  RSI {r['rsi']:.1f}  ·  MCap {mcap}")
            print(f"  │  Anchor: week {anc['weeks_out']} ({anc['expiration']})  "
                  f"strike ${anc['strike']:.2f}  "
                  f"premium ${anc['premium']:.2f} ({anc['premium_pct']:.2f}%)  "
                  f"δ={anc['delta_pct']:.1f}%  score={anc['score']:.1f}")
            print(f"  │")
            print(f"  │  {'WK':<10} {'EXPIRY':<13} {'STRIKE':>8} {'PREMIUM':>8} "
                  f"{'PREM%':>7} {'DELTA%':>7} {'SCORE':>7}  STATUS")
            print(f"  │  {'─'*68}")
            for leg in lad:
                status = "✓ ANCHOR" if leg["is_anchor"] else ("✓ ok" if leg["qualifies"] else "  ladder")
                print(f"  │  {leg['week_label']:<10} {leg['expiration']:<13} "
                      f"${leg['strike']:>7.2f} ${leg['premium']:>7.2f} "
                      f"{leg['premium_pct']:>6.2f}% {leg['delta_pct']:>6.1f}% "
                      f"{leg['score']:>6.1f}   {status}")
            print(f"  │")
            print(f"  │  RE-EVAL RULE: Next week if not assigned, re-run formula.")
            print(f"  │  If premium%(m) ≥ {p_min}% AND m×{p_min}+δ ≥ {score_min}%  →  new anchor at K_m,")
            print(f"  │  rebuild ladder at $5 intervals.  If assigned → do nothing.")
            print(f"  └{'─'*68}\n")
    else:
        print("  ✗  No qualifying trades found.\n")

    if filtered:
        print(f"  ─ Passed filters but formula not met ({len(filtered)}):")
        for r in filtered:
            reason = r["ladder_result"].get("fail_reason","") if r["ladder_result"] else "No puts fetched"
            print(f"     {r['ticker']:6s}  RSI={r['rsi']:.1f}  {reason}")
        print()

    if skipped:
        print(f"  ─ Filtered out ({len(skipped)}):")
        for r in skipped:
            print(f"     {r['ticker']:6s}  {' | '.join(r['filter_fail'])}")
        print()

    print(f"{'═'*W}\n")


def save_json(results: list[dict],
              p_min: float,
              score_min: float,
              ladder_step: float):
    """
    Writes put_ladder.json to data/ and artifacts/data/,
    mirroring the signals.json / spreads.json pattern in your main script.
    """
    payload = {
        "generated_at_pt": dt_pacific.strftime("%m-%d-%Y %H:%M"),
        "params": {
            "p_min":       p_min,
            "score_min":   score_min,
            "ladder_step": ladder_step,
            "rsi_threshold": RSI_OVERSOLD,
            "mcap_min_b":  MCAP_MIN_B,
        },
        "qualifying": [r for r in results if r["qualifying"]],
        "all":         results,
    }
    for path in ["data/put_ladder.json", "artifacts/data/put_ladder.json"]:
        try:
            with open(path, "w") as f:
                json.dump(payload, f, indent=2)
            logger.info(f"Wrote {path}")
        except Exception as e:
            logger.warning(f"Could not write {path}: {e}")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Put Ladder Strategy Scanner")
    parser.add_argument("--tickers",     help="Comma-separated tickers, overrides config.tickers")
    parser.add_argument("--min-premium", type=float, default=P_MIN,
                        help=f"Minimum premium%% per week (default {P_MIN})")
    parser.add_argument("--min-score",   type=float, default=SCORE_MIN,
                        help=f"Minimum n*P_MIN+delta score (default {SCORE_MIN})")
    parser.add_argument("--ladder-step", type=float, default=LADDER_STEP,
                        help=f"Strike decrement per ladder leg in $ (default {LADDER_STEP})")
    parser.add_argument("--output",      choices=["console","json","both"],
                        default="both", help="Output mode (default: both)")
    args = parser.parse_args()

    raw = args.tickers if args.tickers else BASE_TICKERS
    tickers = normalize_tickers(raw)

    if not tickers:
        parser.error("No tickers provided. Pass --tickers AAPL,MSFT or set config.tickers")

    logger.info(
        f"Starting put ladder scan: {len(tickers)} tickers | "
        f"p_min={args.min_premium}% | score_min={args.min_score} | "
        f"ladder_step=${args.ladder_step}"
    )

    results = scan(
        tickers,
        p_min=args.min_premium,
        score_min=args.min_score,
        ladder_step=args.ladder_step,
    )

    qualifying_count = sum(1 for r in results if r["qualifying"])
    logger.info(f"Scan complete: {qualifying_count} qualifying / {len(results)} total")

    if args.output in ("console", "both"):
        print_console(results, args.min_premium, args.min_score)

    if args.output in ("json", "both"):
        save_json(results, args.min_premium, args.min_score, args.ladder_step)


if __name__ == "__main__":
    main()
