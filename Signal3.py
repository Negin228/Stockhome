import os
import datetime
import json
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import logging
from logging.handlers import RotatingFileHandler
import argparse
import config
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict

# === Logging setup: file + console with rotation ===
os.makedirs(config.LOG_DIR, exist_ok=True)
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(
    log_path, maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8"
)
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# === Secrets from environment vars ===
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")



finnhub_client = finnhub.Client(api_key=API_KEY)

# Helper functions to load/save notified buys per email type
def load_previous_buys(email_type):
    file_path = f"sent_buys_{email_type}.json"
    if os.path.exists(file_path):
        try:
            with open(file_path) as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Could not load previous buys for {email_type}: {e}")
    return set()

def save_buys(email_type, buy_tickers):
    file_path = f"sent_buys_{email_type}.json"
    try:
        with open(file_path, "w") as f:
            json.dump(list(buy_tickers), f)
    except Exception as e:
        logger.warning(f"Could not save buys for {email_type}: {e}")

# Historical data with caching
def fetch_cached_history(symbol, period="2y", interval="1d"):
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df, force_full = None, False
    if os.path.exists(file_path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(file_path))).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            logger.info("%s cache too old (%d days) → full refresh", symbol, age_days)
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=False)
                df.index = pd.to_datetime(df.index, format="%m/%d/%Y", errors='coerce')
                if df.index.isnull().any():
                    logger.warning("Date parsing failed in cached data for %s, forcing full refresh", symbol)
                    force_full = True
            except Exception:
                df = None
    if df is None or df.empty or force_full:
        try:
            logger.info("⬇️ Downloading full history: %s", symbol)
            df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        except Exception as e:
            logger.error("Download error %s: %s", symbol, e)
            return pd.DataFrame()
    else:
        last_date = df.index[-1]
        if not isinstance(last_date, pd.Timestamp):
            last_date = pd.to_datetime(last_date)
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        logger.info("🔄 Updating %s from %s", symbol, start)
        try:
            new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning("Update error %s: %s", symbol, e)
    try:
        df.to_csv(file_path)
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", symbol, e)
    return df

# Indicators calc
def calculate_indicators(df):
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    return df

def generate_rsi_signal(df):
    last = df.iloc[-1]
    rsi, price = last["rsi"], last["Close"]
    if isinstance(rsi, (pd.Series, pd.DataFrame)):
        rsi = float(rsi.squeeze())
    if isinstance(price, (pd.Series, pd.DataFrame)):
        price = float(price.squeeze())
    signal, reason = None, ""
    if pd.notna(rsi):
        if rsi < config.RSI_OVERSOLD:
            signal, reason = "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
        elif rsi > config.RSI_OVERBOUGHT:
            signal, reason = "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return signal, reason, rsi, price

# Fundamentals and IV fetch
def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning("Fundamentals error %s: %s", symbol, e)
    return None, None

def fetch_option_iv_history(symbol, lookback_days=52):
    iv_data = []
    try:
        ticker = yf.Ticker(symbol)
        for date in ticker.options[-lookback_days:]:
            chain = ticker.option_chain(date)
            if chain.puts.empty:
                continue
            under = ticker.history(period="1d")["Close"].iloc[-1]
            chain.puts["distance"] = abs(chain.puts["strike"] - under)
            atm = chain.puts.loc[chain.puts["distance"].idxmin()]
            iv_data.append({"date": date, "IV": atm["impliedVolatility"]})
    except Exception as e:
        logger.warning("IV history error %s: %s", symbol, e)
    return pd.DataFrame(iv_data)

def calc_iv_rank_percentile(iv_series):
    s = pd.Series(iv_series).dropna()
    if len(s) < 5:
        return None, None
    cur, hi, lo = s.iloc[-1], s.max(), s.min()
    iv_rank = 100 * (cur - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (s < cur).mean()
    return (round(iv_rank, 2) if iv_rank else None, round(iv_pct, 2) if iv_pct else None)

# Fetch puts for next 7 weeks
def fetch_puts_for_7_weeks(symbol):
    from dateutil.parser import parse
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        valid_dates = [d for d in ticker.options if (parse(d) - today).days <= 49]
        for exp_date in valid_dates:
            chain = ticker.option_chain(exp_date)
            if chain.puts.empty:
                continue
            for _, put in chain.puts.iterrows():
                strike = put["strike"]
                last_price = put.get("lastPrice", None)
                bid = put.get("bid", None)
                ask = put.get("ask", None)
                if last_price is not None and last_price > 0:
                    premium = last_price
                elif bid is not None and ask is not None:
                    premium = (bid + ask) / 2
                else:
                    premium = None
                puts_data.append({
                    "expiration": exp_date,
                    "strike": strike,
                    "premium": premium
                })
    except Exception as e:
        logger.warning(f"Failed to fetch 7 weeks puts for {symbol}: {e}")
    return puts_data

# Calculate custom metric
def calculate_custom_metric(puts_data, stock_price):
    if stock_price is None or stock_price == 0:
        return puts_data
    for put in puts_data:
        strike = put.get("strike", None)
        premium = put.get("premium", None)
        try:
            prem_val = float(premium) if premium is not None else 0.0
        except Exception:
            prem_val = 0.0
        if strike is not None:
            try:
                metric = (((stock_price - strike) + (prem_val / 100)) / stock_price) * 100
                put["custom_metric"] = metric
            except Exception as e:
                logger.warning(f"Error computing custom metric for put: {put}, error: {e}")
                put["custom_metric"] = None
        else:
            put["custom_metric"] = None
    return puts_data

# Email send
def send_email(subject, body):
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

# Alert CSV logging
def log_alert(alert):
    csv_path = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode="a", header=header, index=False)

def job(tickers_to_run):
    buy_alerts = []
    sell_alerts = []
    buy_tickers = []
    buy_prices = {}
    total, skipped = 0, 0

    for symbol in tickers_to_run:
        total += 1
        hist = fetch_cached_history(symbol)
        if hist.empty:
            skipped += 1
            continue
        hist = calculate_indicators(hist)
        sig, reason, rsi, price = generate_rsi_signal(hist)
        try:
            rt_price = finnhub_client.quote(symbol).get("c", price)
            if isinstance(rt_price, (pd.Series, pd.DataFrame)):
                rt_price = float(rt_price.squeeze())
        except Exception:
            rt_price = price
        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"])
        if sig:
            # Format market cap in millions with two decimals
            mcap_million = f"{(mcap / 1_000_000):,.2f}M" if mcap else "N/A"
            line_parts = [
                f"{symbol}: {sig} at ${rt_price:.2f}",
                reason,
                f"PE={pe if pe else 'N/A'}",
                f"MarketCap={mcap_million}"
            ]
            if iv_rank is not None:
                line_parts.append(f"IV Rank={iv_rank}")
            line_parts.append(f"IV Percentile={iv_pct}")
            line = ", ".join(line_parts)
            alert_entry = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": symbol,
                "signal": sig,
                "price": rt_price,
                "rsi": round(rsi, 2) if rsi else None,
                "pe_ratio": pe,
                "market_cap": mcap,
                "iv_rank": iv_rank,
                "iv_percentile": iv_pct,
            }
            log_alert(alert_entry)
            if sig == "BUY":
                buy_alerts.append(line)
                buy_tickers.append(symbol)
                buy_prices[symbol] = rt_price
                logger.info(f"Added buy ticker: {symbol}")
            else:
                sell_alerts.append(line)

    logger.info(f"Total buy tickers collected: {len(buy_tickers)}")

    if buy_tickers:
        buy_file_path = "buy_signals.txt"
        try:
            with open(buy_file_path, "w", encoding="utf-8") as file:
                for ticker in buy_tickers:
                    file.write(ticker + "\n")
            logger.info(f"Saved buy tickers to {buy_file_path}")
        except Exception as e:
            logger.error(f"Failed to save buy_signals.txt: {e}")

    puts_dir = "puts_data"
    os.makedirs(puts_dir, exist_ok=True)

    for buy_symbol in buy_tickers:
        puts_7weeks = fetch_puts_for_7_weeks(buy_symbol)
        rt_price = buy_prices.get(buy_symbol, None)
        if rt_price is None or rt_price == 0:
            hist = fetch_cached_history(buy_symbol)
            if not hist.empty:
                rt_price = hist["Close"].iloc[-1]
            else:
                logger.warning(f"No spot or fallback price for {buy_symbol}")

        puts_7weeks = calculate_custom_metric(puts_7weeks, rt_price)

        puts_7weeks = [
            put for put in puts_7weeks
            if put.get("strike") is not None and put["strike"] < rt_price
            and put.get("custom_metric") is not None and put["custom_metric"] >= 10
        ]

        puts_by_exp = defaultdict(list)
        for put in puts_7weeks:
            exp = put.get("expiration")
            if exp:
                puts_by_exp[exp].append(put)

        selected_puts = []
        for exp, puts_list in puts_by_exp.items():
            closest_put = min(puts_list, key=lambda x: abs(x.get("custom_metric", float('inf')) - 10))
            selected_puts.append(closest_put)

        puts_7weeks = selected_puts

        # Build concatenated puts details string with % sign on custom_metric
        puts_details = []
        for put in puts_7weeks:
            strike = put.get("strike")
            premium = put.get("premium")
            custom_metric = put.get("custom_metric")
            strike_str = f"{strike:.1f}" if strike is not None else "N/A"
            premium_str = f"{premium:.2f}" if premium is not None else "N/A"
            custom_metric_str = f"%{custom_metric:.1f}" if custom_metric is not None else "N/A"
            puts_details.append(
                f"\n\nexpiration={put['expiration']}, strike={strike_str}, premium={premium_str}, stock_price={rt_price:.2f}, custom_metric={custom_metric_str}"
            )
        puts_concat = " ".join(puts_details)

        # Append puts info to buy alert lines
        for i, alert_line in enumerate(buy_alerts):
            if alert_line.startswith(f"{buy_symbol}:"):
                buy_alerts[i] = alert_line + " " + puts_concat
                break


        # Save puts data JSON file
        if puts_7weeks:
            puts_file = os.path.join(puts_dir, f"{buy_symbol}_puts_7weeks.json")
            try:
                with open(puts_file, "w", encoding="utf-8") as f:
                    json.dump(puts_7weeks, f, indent=2)
                logger.info(f"Saved 7-week put option data with metrics to {puts_file}")
            except Exception as e:
                logger.error(f"Failed to save put data for {buy_symbol}: {e}")

    return buy_tickers, buy_alerts, sell_alerts

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated tickers to run Signal.py on")
    parser.add_argument("--email-type", type=str, choices=["first", "second", "hourly"], default="hourly",
                        help="Type of email to send")
    args = parser.parse_args()

    if args.tickers:
        tickers_to_run = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers_to_run = config.tickers

    previous_buys = load_previous_buys(args.email_type)

    buy_tickers, buy_alerts, sell_alerts = job(tickers_to_run)

    new_buys = set(buy_tickers) - previous_buys
    new_buys = set(buy_tickers)
    if new_buys:
        email_body = ""
        if buy_alerts:
            email_body += f"🔹 Buy Signals ({args.email_type}):\n"
            email_body += "\n\n".join(f" - {alert}" for alert in buy_alerts) + "\n\n"
        if sell_alerts:
            email_body += f"🔸 Sell Signals:\n"
            email_body += "\n\n".join(f" - {alert}" for alert in sell_alerts) + "\n\n"

        logger.info(f"Sending {args.email_type} email with {len(new_buys)} new buys")

        print(email_body)
        send_email(f"StockHome Trading Alerts ({args.email_type})", email_body)

        save_buys(args.email_type, previous_buys.union(new_buys))
    else:
        logger.info(f"No new buys to send for {args.email_type}")

if __name__ == "__main__":
    main()
