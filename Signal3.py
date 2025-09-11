#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import datetime
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import argparse

import pandas as pd
import numpy as np
import yfinance as yf
import ta
from dateutil.parser import parse

# Optional (only used if API key present)
try:
    import finnhub
except Exception:
    finnhub = None

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config  # expects: tickers, LOG_DIR/FILE, DATA_DIR, SMTP_SERVER/PORT, RSI_* thresholds, etc.


# ------------------------------
# Logging setup
# ------------------------------
os.makedirs(config.LOG_DIR, exist_ok=True)
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(
    log_path, maxBytes=getattr(config, "LOG_MAX_BYTES", 1_000_000),
    backupCount=getattr(config, "LOG_BACKUP_COUNT", 3), encoding="utf-8"
)
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ------------------------------
# Env & clients
# ------------------------------
API_KEY = os.getenv("API_KEY")  # Finnhub API key (optional)
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

TICKERS = getattr(config, "tickers", [])
finnhub_client = finnhub.Client(api_key=API_KEY) if (finnhub and API_KEY) else None


# ------------------------------
# Utilities / helpers
# ------------------------------
def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure df has simple string column labels (no MultiIndex/tuples)."""
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join([str(x) for x in tup if x is not None]).strip("_")
            for tup in df.columns.to_list()
        ]
    else:
        df.columns = [str(c) for c in df.columns]
    return df


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


def is_temporary_failure(error) -> bool:
    try:
        msg = str(error).lower()
    except Exception:
        return True
    temp = ["rate limit", "too many requests", "timed out", "timeout", "503", "429", "unavailable"]
    perm = ["delisted", "no price data", "not found", "404"]
    if any(t in msg for t in temp):
        return True
    if any(p in msg for p in perm):
        return False
    return True


# ------------------------------
# History with cache (hardened)
# ------------------------------
def fetch_cached_history(symbol: str, period="2y", interval="1d") -> pd.DataFrame:
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df, force_full = None, False

    if os.path.exists(file_path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(file_path))).days
        if age_days > getattr(config, "MAX_CACHE_AGE_DAYS", 7):
            logger.info("%s cache too old (%d days) → full refresh", symbol, age_days)
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path)
                df = _flatten_columns(df)
                # Prefer "Date" column; else fallback to first column
                date_col = "Date" if "Date" in df.columns else df.columns[0]
                # Use dateutil.parse to avoid "Could not infer format" warning
                df[date_col] = df[date_col].map(lambda x: parse(x) if pd.notna(x) else pd.NaT)
                df = df.dropna(subset=[date_col]).set_index(date_col)
            except Exception:
                df = None

    if df is None or df.empty or force_full:
        try:
            logger.info("⬇️ Downloading full history: %s", symbol)
            df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
            df = _flatten_columns(df)
        except Exception as e:
            logger.error("Download error %s: %s", symbol, e)
            if is_temporary_failure(e):
                raise
            else:
                logger.info(f"Permanent failure for {symbol}: {e}")
                return pd.DataFrame()
    else:
        try:
            last_date = df.index[-1]
            if not isinstance(last_date, pd.Timestamp):
                last_date = pd.to_datetime(last_date)
            start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logger.info("🔄 Updating %s from %s", symbol, start)
            new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False, progress=False)
            if not new_df.empty:
                new_df = _flatten_columns(new_df)
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning("Update error %s: %s", symbol, e)
            if not is_temporary_failure(e):
                return pd.DataFrame()

    # ensure numeric OHLCV (use str(col).lower() to avoid tuple .lower() errors)
    for col in df.columns:
        col_l = str(col).lower()
        if any(k in col_l for k in ["open", "high", "low", "close", "adj", "volume"]):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Save cache with a proper Date column
    try:
        df.reset_index().to_csv(file_path, index=False)
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", symbol, e)

    return df


# ------------------------------
# Indicators & RSI signal
# ------------------------------
def _close_series(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    # Map lowercased string labels -> original labels
    lower_map = {str(c).lower(): c for c in df.columns}
    close_col = lower_map.get("close") or lower_map.get("adj close") or lower_map.get("adjclose")
    if close_col is None:
        for c in df.columns:
            if "close" in str(c).lower():
                close_col = c
                break
    if close_col is None:
        return None
    s = df[close_col]
    if isinstance(s, pd.DataFrame):
        s = s.squeeze()
    return pd.to_numeric(s, errors="coerce")


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    s = _close_series(df)
    if s is None or s.dropna().empty:
        df["rsi"] = np.nan
        df["dma200"] = np.nan
        return df
    try:
        df["rsi"] = ta.momentum.RSIIndicator(s, window=14).rsi().reindex(df.index)
    except Exception as e:
        logger.warning(f"RSI calculation failed: {e}")
        df["rsi"] = np.nan
    df["dma200"] = s.rolling(200).mean()
    return df


def generate_rsi_signal(df: pd.DataFrame):
    s = _close_series(df)
    if s is None or s.dropna().empty:
        return None, "", None, None
    price = float(s.dropna().iloc[-1])
    rsi_val = None
    try:
        rsi_val = float(df["rsi"].dropna().iloc[-1])
    except Exception:
        rsi_val = None
    signal, reason = None, ""
    if rsi_val is not None:
        if rsi_val < config.RSI_OVERSOLD:
            signal, reason = "BUY", f"RSI={rsi_val:.1f} < {config.RSI_OVERSOLD}"
        elif rsi_val > config.RSI_OVERBOUGHT:
            signal, reason = "SELL", f"RSI={rsi_val:.1f} > {config.RSI_OVERBOUGHT}"
    return signal, reason, rsi_val, price


# ------------------------------
# Fundamentals & IV (optional)
# ------------------------------
def fetch_fundamentals(symbol: str):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning("Fundamentals error %s: %s", symbol, e)
    return None, None


def fetch_option_iv_history(symbol: str, lookback_days=52) -> pd.DataFrame:
    iv_data = []
    try:
        ticker = yf.Ticker(symbol)
        dates = ticker.options[-lookback_days:]
        for date in dates:
            chain = ticker.option_chain(date)
            if chain.puts.empty:
                continue
            under = ticker.history(period="1d")["Close"].iloc[-1]
            chain.puts["distance"] = (chain.puts["strike"] - under).abs()
            atm = chain.puts.loc[chain.puts["distance"].idxmin()]
            iv_data.append({"date": date, "IV": atm.get("impliedVolatility", np.nan)})
    except Exception as e:
        logger.warning("IV history error %s: %s", symbol, e)
    return pd.DataFrame(iv_data)


def calc_iv_rank_percentile(iv_series) -> tuple:
    s = pd.Series(iv_series).dropna()
    if len(s) < 5:
        return None, None
    cur, hi, lo = s.iloc[-1], s.max(), s.min()
    iv_rank = 100 * (cur - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (s < cur).mean()
    return (round(iv_rank, 2) if iv_rank is not None else None,
            round(iv_pct, 2) if iv_pct is not None else None)


# ------------------------------
# Options gathering (≈7 weeks)
# ------------------------------
def fetch_puts_for_7_weeks(symbol: str) -> list[dict]:
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        # keep expirations within ~49 days (upper bound)
        valid_dates = [d for d in ticker.options if (parse(d) - today).days <= 49]
        for exp_date in valid_dates:
            chain = ticker.option_chain(exp_date)
            if chain.puts.empty:
                continue
            for _, put in chain.puts.iterrows():
                strike = put.get("strike", None)
                last_price = put.get("lastPrice", None)
                bid = put.get("bid", None)
                ask = put.get("ask", None)

                premium = None
                try:
                    if last_price is not None and not pd.isna(last_price) and float(last_price) > 0:
                        premium = float(last_price)
                    elif bid is not None and ask is not None and not pd.isna(bid) and not pd.isna(ask):
                        premium = float((bid + ask) / 2.0)
                except Exception:
                    premium = None

                if strike is None or pd.isna(strike) or premium is None:
                    continue

                puts_data.append({
                    "expiration": exp_date,
                    "strike": float(strike),
                    "premium": float(premium)
                })
    except Exception as e:
        logger.warning(f"Failed to fetch 7 weeks puts for {symbol}: {e}")
    return puts_data


# ------------------------------
# Three metrics per put
# ------------------------------
def calculate_option_metrics(puts_data: list[dict], stock_price: float) -> list[dict]:
    """
    Adds to each put:
      - delta_pct: (stock - strike)/stock * 100
      - premium_pct: premium/stock * 100
      - overall_metric: ( (stock - strike) + (premium/100) ) / stock * 100
    """
    if stock_price is None or stock_price == 0:
        return puts_data

    for put in puts_data:
        strike = put.get("strike")
        premium = put.get("premium")
        prem_val = None
        try:
            prem_val = float(premium) if premium is not None else None
        except Exception:
            prem_val = None

        put["delta_pct"] = ((float(stock_price) - float(strike)) / float(stock_price)) * 100 \
                           if strike is not None else None
        put["premium_pct"] = (prem_val / float(stock_price)) * 100 if prem_val is not None else None
        prem_for_overall = prem_val if prem_val is not None else 0.0
        put["overall_metric"] = (((float(stock_price) - float(strike)) + (prem_for_overall / 100)) / float(stock_price)) * 100 \
                                if strike is not None else None
    return puts_data


# ------------------------------
# Email
# ------------------------------
def send_email(subject: str, body: str) -> None:
    if not EMAIL_SENDER or not EMAIL_RECEIVER or not EMAIL_PASSWORD:
        logger.error("Email environment variables are not properly set.")
        return
    try:
        msg = MIMEMultipart()
        msg["From"], msg["To"], msg["Subject"] = EMAIL_SENDER, EMAIL_RECEIVER, subject
        msg.attach(MIMEText(body, "plain"))
        s = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        s.starttls()
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.send_message(msg)
        s.quit()
        logger.info("✉️ Email sent.")
    except Exception as e:
        logger.error("Email failed: %s", e)


def log_alert(alert: dict) -> None:
    csv_path = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode="a", header=header, index=False)


def format_email_body_clean(buy_alerts: list[str], sell_alerts: list[str], version="4") -> str:
    """
    Format email body with clean table format. Shows Delta%, Premium%, Overall%.
    """
    email_body = f"📊 StockHome Trading Signals v{version}\n"
    email_body += f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    email_body += "=" * 60 + "\n\n"

    if buy_alerts:
        email_body += "🟢 BUY SIGNALS\n\n"
        for alert in buy_alerts:
            lines = alert.split("\n")
            main_line = lines[0]
            puts_data = [line for line in lines[1:] if line.strip() and "expiration=" in line and "=" in line]

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

                        clean_line = (
                            f"Exp: {exp}, "
                            f"Strike: ${strike}, "
                            f"Premium: ${premium}, "
                            f"Stock: ${stock_price}, "
                            f"Delta%: {delta_pct}, "
                            f"Premium%: {premium_pct}, "
                            f"Overall%: {overall}"
                        )
                        email_body += f"      • {clean_line}\n"
                    except Exception as e:
                        logger.warning(f"Failed to parse put line: {put_line}, error: {e}")
                        email_body += f"      • {put_line}\n"
                email_body += "\n"

    if sell_alerts:
        email_body += "🔴 SELL SIGNALS\n\n"
        for alert in sell_alerts:
            email_body += f"📉 {alert}\n\n"

    return email_body


# ------------------------------
# Core job
# ------------------------------
def job(tickers_to_run: list[str]):
    buy_alerts, sell_alerts = [], []
    buy_tickers: list[str] = []
    buy_prices: dict[str, float] = {}
    failed_tickers: list[str] = []

    for symbol in tickers_to_run:
        try:
            hist = fetch_cached_history(symbol)
            if hist.empty:
                logger.info(f"No historical data found for {symbol}; skipping.")
                continue
        except Exception as e:
            msg = str(e).lower()
            if "possibly delisted" in msg or "no price data found" in msg:
                logger.info(f"Permanent failure (delisted) for {symbol}: {e}")
                continue
            elif is_temporary_failure(e):
                logger.warning(f"Temporary failure fetching data for {symbol}: {e}")
                failed_tickers.append(symbol)
                continue
            else:
                logger.info(f"Permanent failure fetching data for {symbol}: {e}")
                continue

        hist = calculate_indicators(hist)
        sig, reason, rsi, price = generate_rsi_signal(hist)

        # Prefer real-time price from Finnhub if available
        rt_price = price
        if finnhub_client:
            try:
                q = finnhub_client.quote(symbol) or {}
                c = q.get("c", None)
                if c:
                    rt_price = float(c)
            except Exception:
                rt_price = price

        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"])

        if sig:
            def fmt_mcap(v):
                if not v:
                    return "N/A"
                return f"{v/1_000_000_000:.1f}B" if v >= 1_000_000_000 else f"{v/1_000_000:.1f}M"

            parts = [
                f"{symbol}: {sig} at ${rt_price:.2f}",
                reason,
                f"PE={f'{pe:.1f}' if pe else 'N/A'}",
                f"MarketCap={fmt_mcap(mcap)}"
            ]
            if iv_rank is not None:
                parts.append(f"IV Rank={iv_rank}")
            if iv_pct is not None:
                parts.append(f"IV Percentile={iv_pct}")

            line = ", ".join(p for p in parts if p)
            log_alert({
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": symbol,
                "signal": sig,
                "price": rt_price,
                "rsi": round(rsi, 2) if rsi else None,
                "pe_ratio": pe,
                "market_cap": mcap,
                "iv_rank": iv_rank,
                "iv_percentile": iv_pct,
            })

            if sig == "BUY":
                buy_alerts.append(line)
                buy_tickers.append(symbol)
                buy_prices[symbol] = rt_price
            else:
                sell_alerts.append(line)

    # For each BUY ticker: build put recs (single best expiration by highest Premium% among Overall%>=10)
    puts_dir = "puts_data"
    os.makedirs(puts_dir, exist_ok=True)

    for sym in buy_tickers:
        puts_7w = fetch_puts_for_7_weeks(sym)
        rt_price = buy_prices.get(sym, None)
        if rt_price is None or rt_price == 0:
            hist = fetch_cached_history(sym)
            if not hist.empty:
                s = _close_series(hist)
                rt_price = float(s.dropna().iloc[-1]) if s is not None and not s.dropna().empty else None

        puts_7w = calculate_option_metrics(puts_7w, rt_price)

        # Filter: ITM (strike < spot) and Overall% >= 10
        qualified = [
            p for p in puts_7w
            if p.get("strike") is not None and rt_price is not None
            and float(p["strike"]) < float(rt_price)
            and p.get("overall_metric") is not None and float(p["overall_metric"]) >= 10.0
        ]

        # Choose ONE globally: highest Premium%
        best_put = max(
            qualified,
            key=lambda x: (x.get("premium_pct") if x.get("premium_pct") is not None else -1e9),
            default=None
        )
        selected_puts = [best_put] if best_put else []

        # Build details string with three metrics
        puts_details_lines = []
        for p in selected_puts:
            strike = p.get("strike")
            premium = p.get("premium")
            overall_metric = p.get("overall_metric")
            delta_pct = p.get("delta_pct")
            premium_pct = p.get("premium_pct")

            strike_str = f"{strike:.1f}" if strike is not None else "N/A"
            premium_str = f"{premium:.2f}" if premium is not None else "N/A"
            overall_str = f"%{overall_metric:.1f}" if overall_metric is not None else "N/A"
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
                f"overall_metric={overall_str}"
            )

        puts_concat = ("\n" + "\n----------------------\n".join(puts_details_lines)) if puts_details_lines else ""

        # Append to alert line
        for i, alert_line in enumerate(buy_alerts):
            if alert_line.startswith(f"{sym}:"):
                buy_alerts[i] = alert_line + " " + puts_concat
                break

        # Persist JSON for inspection
        if selected_puts:
            out_file = os.path.join(puts_dir, f"{sym}_puts_7weeks.json")
            try:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(selected_puts, f, indent=2)
                logger.info(f"Saved 7-week put option data with metrics to {out_file}")
            except Exception as e:
                logger.error(f"Failed to save put data for {sym}: {e}")

    return buy_tickers, buy_alerts, sell_alerts, failed_tickers


# ------------------------------
# Main
# ------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated tickers to run Signal3.py on")
    parser.add_argument("--email-type", type=str, choices=["first", "second", "hourly"], default="hourly",
                        help="Type of email to send")
    args = parser.parse_args()

    if args.tickers:
        tickers_to_run = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers_to_run = TICKERS

    previous_buys = load_previous_buys(args.email_type)

    # Per-ticker retries
    retry_counts = defaultdict(int)
    max_retries = 10
    to_process = tickers_to_run.copy()

    all_buy_alerts, all_sell_alerts, all_buy_tickers = [], [], []

    while to_process:
        logger.info("Running job on %d tickers (per-ticker retries)", len(to_process))
        buy_tickers, buy_alerts, sell_alerts, failed_tickers = job(to_process)

        all_buy_alerts.extend(buy_alerts)
        all_sell_alerts.extend(sell_alerts)
        all_buy_tickers.extend(buy_tickers)

        # retries only for current failures
        next_batch = []
        for sym in failed_tickers:
            retry_counts[sym] += 1
            if retry_counts[sym] < max_retries:
                next_batch.append(sym)
            else:
                logger.error("Giving up on %s after %d retries.", sym, retry_counts[sym])

        to_process = next_batch
        if to_process:
            time.sleep(60)

    # dedup & new buys
    all_buy_tickers = list(set(all_buy_tickers))
    new_buys = set(all_buy_tickers) - previous_buys

    if new_buys or all_sell_alerts:
        body = format_email_body_clean(all_buy_alerts, all_sell_alerts)
        logger.info(f"Sending email with {len(new_buys)} new buys")
        print(body)
        send_email("StockHome Trading Alerts (with three metrics)", body)
        save_buys(args.email_type, previous_buys.union(new_buys))
    else:
        logger.info("No new buys/sells to send after per-ticker retry attempts.")


if __name__ == "__main__":
    main()
