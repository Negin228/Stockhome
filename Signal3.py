import os
import datetime
import json
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import argparse
import time
import numpy as np
from dateutil.parser import parse
import config

def fetch_history(symbol, period="2y", interval="1d"):
    path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df = None
    force_full = False
    if os.path.exists(path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age_days > config.MAX_CACHE_DAYS:
            force_full = True
            logging.info(f"Cache for {symbol} is stale ({age_days} days), refreshing")
        else:
            try:
                cols = ['Date', 'Price', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
                df = pd.read_csv(path, skiprows=3, names=cols)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df.set_index('Date', inplace=True)
                if df.index.hasnans:
                    logging.warning(f"Cache date parsing failed for {symbol}, refreshing cache")
                    force_full = True
            except Exception as e:
                logging.warning(f"Failed reading cache for {symbol}: {e}")
                df = None
    if df is None or df.empty or force_full:
        logging.info(f"Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df.to_csv(path)
    else:
        try:
            last = df.index[-1]
            if not isinstance(last, pd.Timestamp):
                last = pd.to_datetime(last)
            start_date = (last - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logging.info(f"Updating {symbol} from {start_date}")
            new_df = yf.download(symbol, start=start_date, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
                df.to_csv(path)
        except Exception as e:
            logging.warning(f"Incremental update failed for {symbol}: {e}")
    return df

def fetch_quote(symbol):
    finnhub_client = finnhub.Client(api_key=os.getenv("API_KEY"))
    quote = finnhub_client.quote(symbol)
    price = quote.get("c", None)
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return None
    return price

def calculate_indicators(df):
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    return df

def generate_signal(df, oversold_val):
    if df.empty or "rsi" not in df.columns:
        return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None, ""
    if rsi < oversold_val:
        return "BUY", f"RSI={rsi:.1f}"
    if rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f}"
    return None, ""

def fetch_fundamentals_safe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logging.warning(f"Failed to fetch fundamentals for {symbol}: {e}")
        return None, None

def fetch_puts(symbol):
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        valid_dates = [d for d in ticker.options if (parse(d) - today).days <= 49]
        for exp in valid_dates:
            chain = ticker.option_chain(exp)
            if chain.puts.empty:
                continue
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
            chain.puts["distance"] = abs(chain.puts["strike"] - under_price)
            for _, put in chain.puts.iterrows():
                strike = put["strike"]
                premium = put.get("lastPrice") or ((put.get("bid") + put.get("ask")) / 2 if (put.get("bid") is not None and put.get("ask") is not None) else None)
                puts_data.append({
                    "expiration": exp,
                    "strike": strike,
                    "premium": premium,
                    "stock_price": under_price
                })
    except Exception as e:
        logging.warning(f"Failed to fetch puts for {symbol}: {e}")
    return puts_data

def calculate_custom_metrics(puts, price):
    if price is None or price <= 0 or np.isnan(price):
        return puts
    for p in puts:
        strike = p.get("strike")
        premium = p.get("premium") or 0.0
        try:
            premium_val = float(premium)
            delta_percent = ((price - strike) / price) * 100 if strike else 0
            premium_percent = (premium_val / price) * 100 if premium_val else 0
            p["delta_percent"] = delta_percent
            p["premium_percent"] = premium_percent
            p["custom_metric"] = delta_percent + premium_percent if strike else None
        except Exception as e:
            logging.warning(f"Error computing metrics for put {p}: {e}")
            p["custom_metric"] = p["delta_percent"] = p["premium_percent"] = None
    return puts

def format_market_cap(mcap):
    if not mcap:
        return "N/A"
    if mcap >= 1e9:
        return f"${mcap / 1e9:.1f}B"
    if mcap >= 1e6:
        return f"${mcap / 1e6:.1f}M"
    return str(mcap)

def format_email_body(buy_alerts, sell_alerts, version="4"):
    lines = [
        f"📊 StockHome Trading Signals v{version}",
        f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "="*60,
        ""
    ]
    if buy_alerts:
        lines.append("🟢 BUY SIGNALS")
        for alert in buy_alerts:
            lines.append(f"📈 {alert}")
    if sell_alerts:
        lines.append("🔴 SELL SIGNALS")
        lines.extend(f"📉 {alert}" for alert in sell_alerts)
    return "\n".join(lines)

def job(tickers):
    buy_alerts, sell_alerts, failed = [], [], []
    prices = {}
    failed = []
    for symbol in tickers:
        try:
            hist = fetch_history(symbol)
            if hist.empty:
                logging.info(f"No historical data for {symbol}, skipping.")
                continue
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logging.warning(f"Rate limited on fetching history for {symbol}, retry delayed.")
                failed.append(symbol)
                continue
            if any(k in msg for k in ["delisted", "no data", "not found"]):
                logging.info(f"{symbol} delisted or no data, skipping.")
                continue
            logging.error(f"Error fetching history for {symbol}: {e}")
            continue
        hist = calculate_indicators(hist)
        sig, reason = generate_signal(hist, config.RSI_OVERSOLD)
        if not sig:
            continue
        try:
            rt_price = fetch_quote(symbol)
        except Exception as e:
            rt_price = hist["Close"].iloc[-1] if not hist.empty else None
        if rt_price is None or rt_price != rt_price or rt_price <= 0:
            logging.warning(f"Invalid price for {symbol}, skipping.")
            continue
        pe, mcap = fetch_fundamentals_safe(symbol)
        cap_str = format_market_cap(mcap)
        pe_str = f"{pe:.1f}" if pe is not None else "N/A"
        puts_dir = "puts_data"
        os.makedirs(puts_dir, exist_ok=True)
        puts_list = fetch_puts(symbol)
        puts_list = calculate_custom_metrics(puts_list, rt_price)
        filtered_puts = [
            p for p in puts_list
            if p.get("strike") is not None and rt_price
            and p["strike"] < rt_price
            and p.get("custom_metric") and p["custom_metric"] >= 10
        ]
        if filtered_puts:
            best_put = max(filtered_puts, key=lambda x: x.get('premium_percent', 0) or x.get('premium', 0))
            # Format expiration date
            try:
                exp_date_fmt = datetime.datetime.strptime(str(best_put['expiration']), "%Y-%m-%d").strftime("%b %d, %Y")
            except Exception:
                exp_date_fmt = str(best_put['expiration'])
            strike = f"{best_put['strike']:.1f}" if isinstance(best_put['strike'], (int, float)) else "N/A"
            premium = f"{best_put['premium']:.2f}" if isinstance(best_put['premium'], (int, float)) else "N/A"
            delta = best_put.get('delta_percent', 0)
            prem_pct = best_put.get('premium_percent', 0)
            metric_sum = delta + prem_pct
            alert_line = (
                f"{symbol}: BUY at ${rt_price:.2f}, RSI={hist['rsi'].iloc[-1]:.1f}, "
                f"P/E={pe_str}, Market Cap={cap_str}, "
                f"Exp date: {exp_date_fmt}, Strike Price: ${strike}, Premium: ${premium}, "
                f"[Δ {delta:.1f}% + 💎 {prem_pct:.1f}%] = {metric_sum:.1f}%"
            )
            buy_alerts.append(alert_line)
            puts_json_path = os.path.join(puts_dir, f"{symbol}_puts_7weeks.json")
            try:
                with open(puts_json_path, "w") as fp:
                    json.dump([best_put], fp, indent=2)
                logging.info(f"Saved puts data for {symbol}")
            except Exception as e:
                logging.error(f"Failed to save puts json for {symbol}: {e}")
    return buy_alerts, sell_alerts, failed

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    parser.add_argument("--email-type", type=str, choices=["first","second","hourly"], default="hourly", help="Email type")
    args = parser.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else config.tickers
    all_buy_alerts, all_sell_alerts, _ = job(tickers)
    body = format_email_body(all_buy_alerts, all_sell_alerts)
    print(body)

if __name__ == "__main__":
    main()
