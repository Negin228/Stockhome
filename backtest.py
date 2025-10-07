#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math, sys, datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf

# -----------------------------
# Black–Scholes helpers
# -----------------------------
def _norm_cdf(x):  # standard normal CDF
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))t

def bs_put_price(S, K, T, r, sigma):
    if T <= 0:  # expiry
        return max(K - S, 0.0)
    if sigma <= 0:
        return max(K - S*math.exp(-r*T), 0.0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return K*math.exp(-r*T)*_norm_cdf(-d2) - S*_norm_cdf(-d1)

def bs_put_delta(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return -1.0 if S < K else 0.0
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    # put delta is N(d1)-1  (negative)
    return _norm_cdf(d1) - 1.0

def strike_for_target_delta(S, T, r, sigma, target_abs_delta=0.20):
    # Bisection on K to achieve |put delta| ~ target
    # Search K in (tiny, 2*S] to be safe
    low, high = max(1e-4, 0.01*S), 2.0*S
    for _ in range(60):
        mid = 0.5*(low + high)
        d = abs(bs_put_delta(S, mid, T, r, sigma))
        if d > target_abs_delta:
            low = mid
        else:
            high = mid
    return 0.5*(low + high)

# -----------------------------
# IV / IV Rank proxies
# -----------------------------
def add_iv_proxies(df_prices, lookback_ivr=252):
    """Adds columns: iv_proxy (HV20 annualized), ivr_proxy in [0,1]"""
    logret = np.log(df_prices["Close"]).diff()
    hv20 = logret.rolling(20).std() * math.sqrt(252)
    df_prices["iv_proxy"] = hv20.clip(lower=0.05).bfill()  # simple floor
    lo = hv20.rolling(lookback_ivr).min()
    hi = hv20.rolling(lookback_ivr).max()
    ivr = (hv20 - lo) / (hi - lo)
    df_prices["ivr_proxy"] = ivr.clip(lower=0.0, upper=1.0).fillna(0.0)
    return df_prices

# -----------------------------
# Backtest
# -----------------------------
def backtest_csp(
    tickers,
    start_cash=100_000.0,
    risk_free_rate=0.02,
    target_delta=0.20,
    target_dte_days=30,
    min_ivr=0.40,                       # IV Rank ≥ 40%
    min_yield_per_30d=0.02,             # premium/strike * (30/DTE) ≥ 2%
    seed=7
):
    np.random.seed(seed)

    # Time range: we need an extra year of history to compute IVR at the start
    today = dt.date.today()
    start_bt = today - dt.timedelta(days=365*2)          # “two years ago”
    hist_start = start_bt - dt.timedelta(days=370)       # extra for IVR lookback
    end_bt = today

    # Download adjusted close for all tickers
    data = yf.download(
        tickers, start=hist_start.isoformat(), end=end_bt.isoformat(),
        auto_adjust=True, progress=False, group_by="ticker", threads=True
    )

    # Normalize to per-ticker DataFrames
    per_ticker = {}
    for t in tickers:
        try:
            df_t = data[t][["Close"]].dropna().copy()
        except Exception:
            # if only 1 ticker, yfinance returns flat columns
            df_t = data[["Close"]].dropna().copy()
        df_t = add_iv_proxies(df_t)
        per_ticker[t] = df_t

    # Align a common calendar (business days)
    all_dates = sorted(set().union(*[set(df.index) for df in per_ticker.values()]))
    cal = pd.DatetimeIndex(all_dates)
    cal = cal[cal.date >= start_bt]  # begin the BT after IVR warmup

    # State
    cash = start_cash
    reserved = 0.0                    # collateral tied up
    open_csp = {t: None for t in tickers}   # one open CSP per ticker
    ledger = []                       # every cashflow
    trades = []                       # per-option stats

    def reserve(amount, date, note):
        nonlocal reserved
        reserved += amount
        ledger.append({"date": date, "type": "reserve", "amount": -amount, "cash": cash, "reserved": reserved, "note": note})

    def release(amount, date, note):
        nonlocal reserved
        reserved -= amount
        ledger.append({"date": date, "type": "release", "amount": amount, "cash": cash, "reserved": reserved, "note": note})

    def credit(amount, date, note):
        nonlocal cash
        cash += amount
        ledger.append({"date": date, "type": "credit", "amount": amount, "cash": cash, "reserved": reserved, "note": note})

    def debit(amount, date, note):
        nonlocal cash
        cash -= amount
        ledger.append({"date": date, "type": "debit", "amount": -amount, "cash": cash, "reserved": reserved, "note": note})

    # Backtest loop
    for current_date in cal:
        # 1) Expire any options today
        for t in tickers:
            pos = open_csp[t]
            if pos is None:
                continue
            if current_date.date() >= pos["expiry"].date():
                df = per_ticker[t]
                if current_date not in df.index:
                    # find the last available close
                    prev = df.index[df.index <= current_date]
                    if len(prev) == 0:  # no price -> close with zero intrinsic
                        S_T = pos["S_at_open"]
                    else:
                        S_T = float(df.loc[prev[-1], "Close"])
                else:
                    S_T = float(df.loc[current_date, "Close"])

                intrinsic = max(pos["K"] - S_T, 0.0)  # put intrinsic
                pnl = (pos["credit"] - intrinsic) * 100.0

                # Release collateral; if ITM, simulate cash buy at K and instant sell at S_T to stay in cash
                release(pos["K"]*100.0, current_date, f"{t} collateral release")
                credit(pnl, current_date, f"{t} option expiry PnL")

                trades.append({
                    "ticker": t,
                    "open_date": pos["open_date"].date(),
                    "expiry": pos["expiry"].date(),
                    "S_open": pos["S_at_open"],
                    "S_expiry": S_T,
                    "strike": pos["K"],
                    "entry_credit": pos["credit"],
                    "itm_on_expiry": int(S_T < pos["K"]),
                    "pnl": pnl
                })
                open_csp[t] = None

        # 2) Consider new entries (skip if we already have a CSP on that ticker)
        for t in tickers:
            if open_csp[t] is not None:
                continue
            df = per_ticker[t]
            if current_date not in df.index:
                continue
            row = df.loc[current_date]
            S = float(row["Close"])
            sigma = float(row["iv_proxy"])
            ivr = float(row["ivr_proxy"])

            if ivr < min_ivr:
                continue

            T = target_dte_days / 365.0
            r = risk_free_rate
            K = strike_for_target_delta(S, T, r, sigma, target_abs_delta=target_delta)
            premium = bs_put_price(S, K, T, r, sigma)
            # yield per 30D test
            yld = (premium / K) * (30.0 / target_dte_days)
            if yld < min_yield_per_30d:
                continue

            collateral = K * 100.0
            if cash - 1e-9 < collateral:   # need cash to secure
                continue

            # Enter: collect premium, reserve collateral
            credit(premium * 100.0, current_date, f"{t} short put premium")
            reserve(collateral, current_date, f"{t} collateral")
            open_csp[t] = {
                "open_date": current_date,
                "expiry": (current_date + pd.Timedelta(days=target_dte_days)),
                "K": K,
                "credit": premium,
                "S_at_open": S
            }

    # Build performance tables
    ledger_df = pd.DataFrame(ledger).sort_values("date").reset_index(drop=True)
    equity = []
    run_cash = 0.0
    run_reserved = 0.0
    # derive equity path from ledger (cash + reserved doesn’t equal equity; equity is cash because options are off-balance sheet,
    # but we track a "utilization" path via reserved collateral).
    # We'll compute cash over time directly:
    cash_series = []
    reserved_series = []
    cur_cash = start_cash
    cur_reserved = 0.0
    last_date = None
    for _, row in ledger_df.iterrows():
        last_date = row["date"]
        cur_cash = row["cash"]
        cur_reserved = row["reserved"]
        cash_series.append((last_date, cur_cash))
        reserved_series.append((last_date, cur_reserved))

    cash_df = pd.DataFrame(cash_series, columns=["date","cash"]).set_index("date").sort_index()
    reserved_df = pd.DataFrame(reserved_series, columns=["date","reserved"]).set_index("date").sort_index()
    idx = pd.DatetimeIndex(cal)
    # forward fill to daily path
    cash_path = cash_df.reindex(idx).ffill().fillna(start_cash)
    res_path = reserved_df.reindex(idx).ffill().fillna(0.0)
    equity_path = cash_path.copy()  # equity == cash in this simple model
    util = (res_path["reserved"] / equity_path["cash"]).replace([np.inf, -np.inf], 0).clip(lower=0, upper=1)

    trades_df = pd.DataFrame(trades)
    summary = {
        "start_cash": start_cash,
        "final_cash": float(equity_path.iloc[-1]["cash"]) if len(equity_path) else start_cash,
        "num_trades": int(len(trades_df)),
        "win_rate_%": round(100.0 * trades_df["pnl"].gt(0).mean(), 2) if len(trades_df) else 0.0,
        "avg_pnl_per_trade": round(trades_df["pnl"].mean(), 2) if len(trades_df) else 0.0,
        "total_pnl": round(trades_df["pnl"].sum(), 2) if len(trades_df) else 0.0,
        "avg_collateral_util_%": round(100.0 * util.mean(), 2) if len(util) else 0.0,
    }

    return trades_df, equity_path.reset_index().rename(columns={"index":"date"}), res_path.reset_index().rename(columns={"index":"date"}), summary

# -----------------------------
# Run example
# -----------------------------
if __name__ == "__main__":
    TICKERS = ["AAPL", "MSFT", "AMZN", "META", "NVDA", "GOOGL", "TSLA"]

    trades, equity, collateral, summary = backtest_csp(
        tickers=TICKERS,
        start_cash=100_000.0,
        risk_free_rate=0.02,
        target_delta=0.20,
        target_dte_days=30,
        min_ivr=0.40,
        min_yield_per_30d=0.02
    )

    print("SUMMARY")
    for k, v in summary.items():
        print(f"- {k}: {v}")

    # Save CSVs
    trades.to_csv("csp_trades.csv", index=False)
    equity.to_csv("csp_equity.csv", index=False)
    collateral.to_csv("csp_collateral.csv", index=False)
    print("\nSaved: csp_trades.csv, csp_equity.csv, csp_collateral.csv")
