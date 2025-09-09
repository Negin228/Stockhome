#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal3.py — rewritten to add:
  - delta_pct = (stock - strike) / stock * 100
  - premium_pct = premium / stock * 100
  - overall_metric (your previous custom metric; same formula, just renamed)
Selection rule:
  - If multiple expirations have overall_metric >= 10%, keep only ONE:
    the one with the highest premium_pct.
Also includes:
  - Per‑ticker retry logic (up to 10)
  - Clean email formatter that prints the three metrics
  - Minor robustness in option premium selection (uses lastPrice, then bid, then ask)
"""

import os
import datetime
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import argparse

import pandas as pd
import yfinance as yf
import ta

# Optional: only used if you wire it for fundamentals/IV
try:
    import finnhub
except Exception:
    finnhub = None

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---- Project config (expects a config.py alongside this file) ----
# config.py should define: tickers (list), LOG_DIR, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT
import config


# ============================
# Environment / Globals
# ============================
API_KEY = os.getenv("FINNHUB_API_KEY")  # optional
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SENDER    = os.getenv("EMAIL_SENDER")
RECEIVER  = os.getenv("EMAIL_RECEIVER")

TICKERS = getattr(config, "tickers", [])
finnhub_client = finnhub.Client(api_key=API_KEY) if (finnhub and API_KEY) else None

# ============================
# Logging
# ============================
os.makedirs(config.LOG_DIR, exist_ok=True)
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(
    log_path,
    maxBytes=getattr(config, "LOG_MAX_BYTES", 1_000_000),
    backupCount=getattr(config, "LOG_BACKUP_COUNT", 3),
    encoding="utf-8"
)
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ============================
# Helpers: previous sends
# ============================
def load_previous_buys(email_type: str) -> set:
    file_path = f"sent_buys_{email_type}.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Could not load previous buys for {email_type}: {e}")
    return set()


def save_buys(email_type: str, buy_tickers: set) -> None:
    file_path = f"sent_buys_{email_type}.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(buy_tickers)), f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save buys for {email_type}: {e}")


# ============================
# Retry classification
# ============================
def is_temporary_failure(exc_msg: str) -> bool:
    if not exc_msg:
        return False
    msg = exc_msg.lower()
    transient_keywords = [
        "timed out", "timeout", "temporarily unavailable", "rate limit",
        "too many requests", "service unavailable", "connection aborted",
        "connection reset", "502", "503", "504"
    ]
    return any(k in msg for k in transient_keywords)


# ============================
# Historical data (with cache)
# ============================
CACHE_DIR = "cache_hist"
os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_cached_history(symbol: str, period="1y", interval="1d") -> pd.DataFrame:
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{period}_{interval}.csv")
    if os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file, parse_dates=["Date"], index_col="Date")
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Failed reading cache for {symbol}: {e}")
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.reset_index().rename(columns={"Date": "Date"})
            df.to_csv(cache_file, index=False)
            return df.set_index("Date")
    except Exception as e:
        logger.error(f"Error fetching history for {symbol}: {e}")
    return pd.DataFrame()


# ============================
# Indicators & simple RSI signal
# ============================
def calculate_indicators(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return hist
    df = hist.copy()
    try:
        df["rsi"] = ta.momentum.RSIIndicator(close=df["Close"], window=14).rsi()
    except Exception as e:
        logger.warning(f"RSI calculation failed: {e}")
        df["rsi"] = pd.NA
    df["sma20"]  = df["Close"].rolling(20).mean()
    df["sma50"]  = df["Close"].rolling(50).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    return df


def generate_rsi_signal(df: pd.DataFrame, symbol: str):
    if df is None or df.empty:
        return None, None
    last = df.iloc[-1]
    rsi = last.get("rsi", None)
    price = last.get("Close", None)
    signal = None
    try:
        if pd.notna(rsi) and pd.notna(price):
            if rsi < 30:
                signal = f"{symbol}: RSI={rsi:.1f} (oversold) @ ${price:.2f}"
            elif rsi > 70:
                signal = f"{symbol}: RSI={rsi:.1f} (overbought) @ ${price:.2f}"
    except Exception:
        pass
    return signal, float(price) if price is not None and pd.notna(price) else None


# ============================
# Option helpers
# ============================
def _coalesce_premium(row) -> float | None:
    """Try lastPrice, then bid, then ask; return float or None."""
    for key in ("lastPrice", "bid", "ask"):
        val = row.get(key, None)
        try:
            if val is not None and not pd.isna(val):
                return float(val)
        except Exception:
            continue
    return None


def fetch_puts_for_7_weeks(symbol: str) -> list[dict]:
    """
    Fetch put options about ~7 weeks out (35–60 days). If none, fallback to the nearest 1–2 expirations.
    Returns: list of dicts with keys: expiration(str), strike(float), premium(float)
    """
    puts_data: list[dict] = []
    try:
        tk = yf.Ticker(symbol)
        expirations = tk.options
        if not expirations:
            return puts_data

        now = datetime.date.today()

        def days_out(exp: str) -> int:
            try:
                d = datetime.datetime.strptime(exp, "%Y-%m-%d").date()
                return (d - now).days
            except Exception:
                return 9999

        candidates = [e for e in expirations if 35 <= days_out(e) <= 60]
        if not candidates:
            candidates = expirations[:2]

        for exp in candidates:
            try:
                opt = tk.option_chain(exp)
                puts = opt.puts if hasattr(opt, "puts") else pd.DataFrame()
                if puts is None or puts.empty:
                    continue
                for _, row in puts.iterrows():
                    strike = row.get("strike", None)
                    if strike is None or pd.isna(strike):
                        continue
                    premium = _coalesce_premium(row)
                    if premium is None:
                        continue
                    puts_data.append({
                        "expiration": exp,
                        "strike": float(strike),
                        "premium": float(premium)
                    })
            except Exception as e:
                logger.warning(f"Option chain fetch failed for {symbol} @ {exp}: {e}")
    except Exception as e:
        logger.warning(f"Failed to fetch 7-week puts for {symbol}: {e}")
    return puts_data


def calculate_option_metrics(puts_data: list[dict], stock_price: float) -> list[dict]:
    """
    Adds metrics per put:
      - delta_pct: (stock - strike)/stock * 100
      - premium_pct: premium/stock * 100
      - overall_metric: previous custom metric (unchanged formula)
    """
    if not puts_data or stock_price is None or stock_price == 0:
        return puts_data

    out = []
    for put in puts_data:
        strike  = put.get("strike", None)
        premium = put.get("premium", None)
        delta_pct = None
        premium_pct = None
        overall_metric = None

        try:
            if strike is not None:
                delta_pct = ((float(stock_price) - float(strike)) / float(stock_price)) * 100.0
        except Exception:
            delta_pct = None

        try:
            if premium is not None:
                premium_pct = (float(premium) / float(stock_price)) * 100.0
        except Exception:
            premium_pct = None

        try:
            if strike is not None and premium is not None:
                overall_metric = (((float(stock_price) - float(strike)) + (float(premium) / 100.0)) / float(stock_price)) * 100.0
        except Exception as e:
            logger.warning(f"overall_metric error for {put}: {e}")
            overall_metric = None

        new_put = dict(put)
        new_put["delta_pct"] = delta_pct
        new_put["premium_pct"] = premium_pct
        new_put["overall_metric"] = overall_metric
        out.append(new_put)
    return out


# ============================
# Email
# ============================
def send_email(subject: str, body: str) -> None:
    """Sends email if creds exist; otherwise prints to stdout."""
    if not all([SMTP_USER, SMTP_PASS, SENDER, RECEIVER]):
        logger.warning("Email creds or addresses missing; printing only.")
        print("=" * 80)
        print(subject)
        print("-" * 80)
        print(body)
        print("=" * 80)
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER
        msg["To"] = RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SENDER, [RECEIVER], msg.as_string())
        logger.info("Email sent.")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def format_email_body_clean(buy_alerts: list[str], sell_alerts: list[str], version: str = "4") -> str:
    """
    Nicely formats all alerts and recommended puts (with all three metrics).
    """
    email_body = f"📊 StockHome Trading Signals v{version}\n"
    email_body += f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    email_body += "=" * 60 + "\n\n"

    if buy_alerts:
        email_body += "🟢 BUY SIGNALS\n\n"
        for alert in buy_alerts:
            lines = alert.split("\n")
            main_line = lines[0]
            puts_data = [line for line in lines[1:] if "expiration=" in line]

            email_body += f"📈 {main_line}\n"
            if puts_data:
                email_body += "   📋 Recommended Put Options:\n"
                for put_line in puts_data:
                    try:
                        kv = {}
                        for part in put_line.split(", "):
                            if "=" in part:
                                k, v = part.split("=", 1)
                                kv[k.strip()] = v.strip()

                        exp         = kv.get("expiration", "N/A")
                        strike      = kv.get("strike", "N/A")
                        premium     = kv.get("premium", "N/A")
                        stock_price = kv.get("stock_price", "N/A")
                        delta_pct   = kv.get("delta_pct", "N/A")
                        premium_pct = kv.get("premium_pct", "N/A")
                        overall     = kv.get("overall_metric", "N/A")

                        clean = (
                            f"Exp: {exp}, "
                            f"Strike: ${strike}, "
                            f"Premium: ${premium}, "
                            f"Stock: ${stock_price}, "
                            f"Delta%: {delta_pct}, "
                            f"Premium%: {premium_pct}, "
                            f"Overall%: {overall}"
                        )
                        email_body += f"      • {clean}\n"
                    except Exception as e:
                        logger.warning(f"Failed to parse put line: {put_line}: {e}")
                        email_body += f"      • {put_line}\n"
                email_body += "\n"

    if sell_alerts:
        email_body += "🔴 SELL SIGNALS\n\n"
        for alert in sell_alerts:
            email_body += f"📉 {alert}\n\n"

    return email_body


# ============================
# Core job
# ============================
def job(tickers_to_run: list[str]):
    buy_alerts: list[str] = []
    sell_alerts: list[str] = []
    buy_tickers: list[str] = []
    buy_prices: dict[str, float] = {}
    failed_tickers: list[str] = []

    for symbol in tickers_to_run:
        try:
            hist = fetch_cached_history(symbol)
            if hist.empty:
                logger.info(f"No historical data for {symbol}")
                continue

            df = calculate_indicators(hist)
            signal, price = generate_rsi_signal(df, symbol)
            if price is not None:
                buy_prices[symbol] = price

            if signal:
                buy_alerts.append(signal)
                buy_tickers.append(symbol)
                logger.info("BUY: %s -> %s", symbol, signal)

        except Exception as e:
            msg = str(e)
            logger.error(f"Error processing {symbol}: {msg}")
            failed_tickers.append(symbol)

    # For each BUY ticker, compute options and append one best put (if any)
    puts_dir = "puts_json"
    os.makedirs(puts_dir, exist_ok=True)

    for sym in buy_tickers:
        puts_7w = fetch_puts_for_7_weeks(sym)
        rt_price = buy_prices.get(sym)
        if not rt_price:
            hist = fetch_cached_history(sym)
            if not hist.empty:
                rt_price = float(hist["Close"].iloc[-1])

        puts_7w = calculate_option_metrics(puts_7w, rt_price if rt_price else 0.0)

        # Filter: ITM only (strike < spot) and overall_metric >= 10%
        qualified = [
            p for p in puts_7w
            if p.get("strike") is not None
            and rt_price is not None
            and p["strike"] < rt_price
            and p.get("overall_metric") is not None
            and p["overall_metric"] >= 10.0
        ]

        # Choose ONLY one: the one with highest premium_pct
        best_put = None
        if qualified:
            best_put = max(
                qualified,
                key=lambda x: (x.get("premium_pct") if x.get("premium_pct") is not None else -1e9)
            )

        selected_puts = [best_put] if best_put else []

        # Build details string(s)
        puts_details_lines = []
        for p in selected_puts:
            strike = p.get("strike")
            premium = p.get("premium")
            overall_metric = p.get("overall_metric")
            delta_pct = p.get("delta_pct")
            premium_pct = p.get("premium_pct")

            strike_str = f"{strike:.1f}" if strike is not None else "N/A"
            premium_str = f"{premium:.2f}" if premium is not None else "N/A"
            overall_metric_str = f"%{overall_metric:.1f}" if overall_metric is not None else "N/A"
            delta_str = f"%{delta_pct:.1f}" if delta_pct is not None else "N/A"
            prem_pct_str = f"%{premium_pct:.1f}" if premium_pct is not None else "N/A"
            stock_str = f"{rt_price:.2f}" if rt_price is not None else "N/A"

            puts_details_lines.append(
                f"\nexpiration={p['expiration']}, "
                f"strike={strike_str}, "
                f"premium={premium_str}, "
                f"stock_price={stock_str}, "
                f"delta_pct={delta_str}, "
                f"premium_pct={prem_pct_str}, "
                f"overall_metric={overall_metric_str}"
            )

        puts_concat = "\n" + "\n----------------------\n".join(puts_details_lines) if puts_details_lines else ""

        # Append to the corresponding alert line
        for i, alert_line in enumerate(buy_alerts):
            if alert_line.startswith(f"{sym}:"):
                buy_alerts[i] = alert_line + puts_concat
                break

        # Persist JSON for inspection
        if selected_puts:
            out_file = os.path.join(puts_dir, f"{sym}_puts_7weeks.json")
            try:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(selected_puts, f, indent=2)
                logger.info(f"Saved selected put for {sym} -> {out_file}")
            except Exception as e:
                logger.error(f"Failed to save put data for {sym}: {e}")

    return buy_tickers, buy_alerts, sell_alerts, failed_tickers


# ============================
# Main
# ============================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated tickers to run Signal3.py on")
    parser.add_argument(
        "--email-type",
        type=str,
        choices=["first", "second", "hourly"],
        default="hourly",
        help="Type of email to send (used to suppress repeats)"
    )
    args = parser.parse_args()

    tickers_to_run = [x.strip().upper() for x in args.tickers.split(",")] if args.tickers else list(TICKERS)

    retries: defaultdict[str, int] = defaultdict(int)
    previous_buys = load_previous_buys(args.email_type)
    to_process = tickers_to_run.copy()

    all_buy_alerts: list[str] = []
    all_sell_alerts: list[str] = []
    all_buy_tickers: list[str] = []

    while to_process:
        logger.info("Running job on %d tickers (per-ticker retries)", len(to_process))
        buy_tickers, buy_alerts, sell_alerts, failed_tickers = job(to_process)

        all_buy_alerts.extend(buy_alerts)
        all_sell_alerts.extend(sell_alerts)
        all_buy_tickers.extend(buy_tickers)

        next_batch = []
        for sym in failed_tickers:
            retries[sym] += 1
            if retries[sym] <= 10:  # up to 10 retries per ticker
                next_batch.append(sym)
            else:
                logger.error("Giving up on %s after %d retries.", sym, retries[sym])
        to_process = next_batch

    # Only email if there are new buys or any sells
    new_buys = set(all_buy_tickers) - previous_buys
    if new_buys or all_sell_alerts:
        body = format_email_body_clean(all_buy_alerts, all_sell_alerts)
        logger.info(f"Sending email with {len(new_buys)} new buys")
        print(body)
        send_email("StockHome Trading Alerts (with metrics)", body)
        save_buys(args.email_type, previous_buys.union(new_buys))
    else:
        logger.info("No new buys/sells to send after per-ticker retry attempts.")


if __name__ == "__main__":
    main()
