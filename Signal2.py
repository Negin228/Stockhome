#!/usr/bin/env python3
# signal2.py
import os
import sys
import json
import time
import math
import argparse
import datetime as dt
from typing import List, Dict, Tuple, Set

import pandas as pd
import yfinance as yf
import ta

import logging
from logging.handlers import RotatingFileHandler

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config

# ================================
# Directories & environment
# ================================
# Ensure base dirs exist every run so GitHub Actions doesn't fail on missing paths
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

STATE_DIR = os.getenv("STATE_DIR", "state")
os.makedirs(STATE_DIR, exist_ok=True)

# Optional externalized puts folder (kept for compatibility if you later save option data)
PUTS_DIR = os.getenv("PUTS_DIR", "puts_data")
os.makedirs(PUTS_DIR, exist_ok=True)

# Email creds from env (set these in GitHub Secrets)
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# ================================
# Logging
# ================================
logger = logging.getLogger("Signal2")
logger.setLevel(logging.INFO)

_log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
_file_handler = RotatingFileHandler(
    _log_path,
    maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT,
    encoding="utf-8"
)
_console_handler = logging.StreamHandler(sys.stdout)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_file_handler.setFormatter(_fmt)
_console_handler.setFormatter(_fmt)

# Avoid duplicate handlers when re-imported
if not logger.handlers:
    logger.addHandler(_file_handler)
    logger.addHandler(_console_handler)

# ================================
# State helpers
# ================================
def state_path(name: str) -> str:
    return os.path.join(STATE_DIR, name)

def load_previous_sends(email_type: str) -> Set[str]:
    fp = state_path(f"sent_buys_{email_type}.json")
    if os.path.exists(fp):
        try:
            with open(fp, "r") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception as e:
            logger.warning("Failed loading state %s: %s", fp, e)
    return set()

def save_previous_sends(email_type: str, tickers: Set[str]) -> None:
    fp = state_path(f"sent_buys_{email_type}.json")
    try:
        with open(fp, "w") as f:
            json.dump(sorted(list(tickers)), f)
    except Exception as e:
        logger.warning("Failed saving state %s: %s", fp, e)

# ================================
# Data fetch & caching
# ================================
def _ticker_cache_path(symbol: str) -> str:
    return os.path.join(config.DATA_DIR, f"{symbol}.csv")

def fetch_history_cached(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV with a simple CSV cache per ticker."""
    path = _ticker_cache_path(symbol)
    use_cache = False

    if os.path.exists(path):
        try:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(path))
            age_days = (dt.datetime.now() - mtime).days
            if age_days <= config.MAX_CACHE_AGE_DAYS:
                use_cache = True
        except Exception as e:
            logger.warning("Could not stat cache for %s: %s", symbol, e)

    if use_cache:
        try:
            df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
            # Handle potential empty read
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            logger.warning("Cache read failed for %s: %s; refetching", symbol, e)

    # Fetch from yfinance
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            logger.warning("%s: empty dataframe from yfinance", symbol)
            return pd.DataFrame()
        # Normalize index name and persist
        df.index.name = "Date"
        df.to_csv(path)
        logger.info("%s: saved history to %s", symbol, path)
        return df
    except Exception as e:
        logger.error("%s: yfinance download failed: %s", symbol, e)
        return pd.DataFrame()

# ================================
# Indicators & signals
# ================================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI and moving averages to the dataframe."""
    if df is None or df.empty:
        return df

    close = df["Close"]

    try:
        df["RSI"] = ta.momentum.rsi(close, window=14, fillna=False)
    except Exception as e:
        logger.warning("RSI failed: %s", e)
        df["RSI"] = math.nan

    try:
        df["MA_SHORT"] = ta.trend.sma_indicator(close, window=config.MA_SHORT, fillna=False)
        df["MA_LONG"]  = ta.trend.sma_indicator(close, window=config.MA_LONG,  fillna=False)
    except Exception as e:
        logger.warning("SMA failed: %s", e)
        df["MA_SHORT"] = math.nan
        df["MA_LONG"] = math.nan

    return df

def evaluate_latest_signal(df: pd.DataFrame) -> Tuple[bool, str, Dict[str, float]]:
    """
    Return (is_buy, reason, snapshot_dict).
    Simple heuristic:
      - Buy if RSI < RSI_OVERSOLD
      - OR price crosses above MA_SHORT today
      - Bonus confidence if MA_SHORT > MA_LONG (uptrend)
    """
    if df is None or df.empty or len(df) < max(15, config.MA_LONG + 2):
        return (False, "insufficient_data", {})

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["Close"])
    rsi = float(last.get("RSI", math.nan))
    ma_s = float(last.get("MA_SHORT", math.nan))
    ma_l = float(last.get("MA_LONG", math.nan))

    # Cross above MA_SHORT today?
    cross_up_short = False
    if not math.isnan(ma_s):
        prev_rel = float(prev["Close"]) - float(prev.get("MA_SHORT", math.nan))
        curr_rel = price - ma_s
        cross_up_short = (not math.isnan(prev_rel) and not math.isnan(curr_rel) and prev_rel < 0 <= curr_rel)

    # Heuristics
    reasons = []
    is_buy = False

    if not math.isnan(rsi) and rsi <= config.RSI_OVERSOLD:
        is_buy = True
        reasons.append(f"RSI({rsi:.1f})<=oversold({config.RSI_OVERSOLD})")

    if cross_up_short:
        is_buy = True
        reasons.append("price_crossed_above_MA_SHORT")

    if not math.isnan(ma_s) and not math.isnan(ma_l) and ma_s > ma_l:
        reasons.append("uptrend(MA_SHORT>MA_LONG)")

    reason = ";".join(reasons) if reasons else "no_rule_triggered"

    snapshot = {
        "price": price,
        "rsi": rsi,
        "ma_short": ma_s,
        "ma_long": ma_l
    }
    return (is_buy, reason, snapshot)

# ================================
# Email
# ================================
def send_email(subject: str, body: str) -> None:
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        logger.warning("Email not sent: missing EMAIL_SENDER/EMAIL_PASSWORD/EMAIL_RECEIVER envs.")
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent to %s", EMAIL_RECEIVER)
    except Exception as e:
        logger.error("Email send failed: %s", e)

# ================================
# Alerts CSV (append-only log)
# ================================
def append_alert_row(ts: dt.datetime, ticker: str, price: float, rsi: float,
                     ma_short: float, ma_long: float, signal: str) -> None:
    row = {
        "timestamp": ts.replace(microsecond=0).isoformat(),
        "ticker": ticker,
        "price": price,
        "rsi": rsi,
        "ma_short": ma_short,
        "ma_long": ma_long,
        "signal": signal
    }
    # Make sure parent dir exists (already created at start, but safe)
    os.makedirs(os.path.dirname(config.ALERTS_CSV), exist_ok=True)

    # Append in a robust way
    try:
        header = not os.path.exists(config.ALERTS_CSV)
        df = pd.DataFrame([row])
        df.to_csv(config.ALERTS_CSV, mode="a", header=header, index=False)
    except Exception as e:
        logger.warning("Failed to append alerts CSV: %s", e)

# ================================
# Main
# ================================
def main():
    parser = argparse.ArgumentParser(description="Generate buy signals and (optionally) email them.")
    parser.add_argument("--email-type", default="hourly", choices=["hourly", "daily", "weekly"],
                        help="Tag used for deduping emails (separate state per type).")
    parser.add_argument("--max", type=int, default=0,
                        help="Optional cap on number of tickers processed (for testing). 0 = no cap.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Do everything except sending the email.")
    parser.add_argument("--period", default="2y", help="yfinance period for history (default: 2y).")
    parser.add_argument("--interval", default="1d", help="yfinance interval (default: 1d).")
    args = parser.parse_args()

    start = dt.datetime.now()
    logger.info("Run started: email_type=%s dry_run=%s", args.email_type, args.dry_run)

    tickers = config.tickers[:]
    if args.max and args.max > 0:
        tickers = tickers[:args.max]

    already_sent = load_previous_sends(args.email_type)
    to_send_now: List[Tuple[str, str, Dict[str, float]]] = []  # (ticker, reason, snapshot)

    processed = 0
    for t in tickers:
        t = t.strip().upper()
        if not t:
            continue

        try:
            df = fetch_history_cached(t, period=args.period, interval=args.interval)
            if df is None or df.empty:
                logger.info("%s: no data; skipping", t)
                continue

            df = compute_indicators(df)
            is_buy, reason, snap = evaluate_latest_signal(df)

            # Log one line per ticker to alerts CSV
            append_alert_row(dt.datetime.now(), t, snap.get("price", math.nan),
                             snap.get("rsi", math.nan), snap.get("ma_short", math.nan),
                             snap.get("ma_long", math.nan), reason)

            if is_buy and (t not in already_sent):
                to_send_now.append((t, reason, snap))

            processed += 1
            # Be nice to API providers if you add network calls later
            time.sleep(0.05)

        except Exception as e:
            logger.exception("Error processing %s: %s", t, e)

    # Prepare output summary file for this run
    summary_lines = []
    if to_send_now:
        summary_lines.append("BUY SIGNALS:")
        for t, reason, snap in to_send_now:
            summary_lines.append(
                f"- {t} @ {snap.get('price', float('nan')):.2f} | RSI={snap.get('rsi', float('nan')):.1f} "
                f"| MA{config.MA_SHORT}={snap.get('ma_short', float('nan')):.2f} "
                f"| MA{config.MA_LONG}={snap.get('ma_long', float('nan')):.2f} "
                f"| {reason}"
            )
    else:
        summary_lines.append("No NEW buy signals.")

    summary = "\n".join(summary_lines)
    with open("buy_signals.txt", "w", encoding="utf-8") as f:
        f.write(summary + "\n")

    logger.info("Processed tickers: %d", processed)
    logger.info(summary.replace("\n", " | "))

    # Email behavior
    if to_send_now and not args.dry_run:
        subject = f"[Signals] {len(to_send_now)} new buy(s) — {args.email_type}"
        body = (
            f"Run time: {start.replace(microsecond=0).isoformat()}\n"
            f"Email type: {args.email_type}\n\n"
            f"{summary}\n"
        )
        send_email(subject, body)

        # Update state AFTER successful send attempt (even if SMTP failed we avoid spamming)
        for t, _, _ in to_send_now:
            already_sent.add(t)
        save_previous_sends(args.email_type, already_sent)

    logger.info("Run finished.")

if __name__ == "__main__":
    # Pandas display options to avoid scientific notation surprises (optional)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    try:
        main()
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)
