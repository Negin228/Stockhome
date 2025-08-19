import os
import datetime
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import logging
from logging.handlers import RotatingFileHandler
import config
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Ensure directories ---
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

# --- Setup logging: file (rotating) + console ---
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    log_path,
    maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT,
    encoding="utf-8"
)
console_handler = logging.StreamHandler()

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# --- Load env secrets ---
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

# ===== Ticker Management =====
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return sorted(df['Symbol'].dropna().tolist())

def get_nasdaq100_tickers():
    url = "https://en.wikipedia.org/wiki/NASDAQ-100"
    tables = pd.read_html(url)
    for tbl in tables:
        if 'Ticker' in tbl.columns:
            return sorted(tbl['Ticker'].dropna().tolist())
    return []

# Refresh tickers weekly (Sunday)
today = datetime.datetime.today()
if today.weekday() == 6:
    logger.info("Refreshing tickers from Wikipedia (Sunday).")
    try:
        sp500 = get_sp500_tickers()
        nasdaq100 = get_nasdaq100_tickers()
        all_tickers = sorted(set(sp500 + nasdaq100))
        with open("tickers.py", "w") as f:
            f.write("# Auto-generated ticker lists\n\n")
            f.write("sp500_tickers = " + repr(sp500) + "\n\n")
            f.write("nasdaq100_tickers = " + repr(nasdaq100) + "\n\n")
            f.write("all_tickers = " + repr(all_tickers) + "\n")
        logger.info("Ticker refresh OK. Total tickers: %d", len(all_tickers))
    except Exception as e:
        logger.error("Ticker refresh failed: %s", e)

from tickers import all_tickers as tickers

# ===== Data Caching =====
def fetch_cached_history(symbol, period="2y", interval="1d"):
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df, force_full = None, False

    if os.path.exists(file_path):
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        age_days = (datetime.datetime.now() - mtime).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            logger.info("%s cache too old (%d days) -> full refresh", symbol, age_days)
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            except Exception:
                df = None

    if df is None or df.empty or force_full:
        try:
            logger.info("Downloading full history for %s", symbol)
            df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        except Exception as e:
            logger.error("Download error %s: %s", symbol, e)
            return pd.DataFrame()
    else:
        last_date = df.index[-1]
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        logger.info("Updating %s from %s", symbol, start)
        try:
            new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning("Update error %s: %s", symbol, e)

    try:
        df.to_csv(file_path)
    except Exception as e:
        logger.warning("Cache save error %s: %s", symbol, e)

    return df

# ===== Indicators =====
def calculate_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    df['dma200'] = df['Close'].rolling(200).mean()
    return df

def generate_rsi_signal(df):
    last = df.iloc[-1]
    rsi, price = last['rsi'], last['Close']
    signal, reason = None, ""
    if pd.notna(rsi):
        if rsi < config.RSI_OVERSOLD:
            signal, reason = "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
        elif rsi > config.RSI_OVERBOUGHT:
            signal, reason = "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return signal, reason, rsi, price

# ===== Fundamentals & Options =====
def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning("Fundamentals error %s: %s", symbol, e)
        return None, None

def fetch_option_iv_history(symbol, lookback_days=52):
    ticker = yf.Ticker(symbol)
    iv_data = []
    try:
        for date in ticker.options[-lookback_days:]:
            opt_chain = ticker.option_chain(date)
            calls = opt_chain.calls
            if calls.empty:
                continue
            underlying = ticker.history(period="1d")['Close'].iloc[-1]
            calls['distance'] = abs(calls['strike'] - underlying)
            atm = calls.loc[calls['distance'].idxmin()]
            iv_data.append({'date': date, 'IV': atm['impliedVolatility']})
    except Exception as e:
        logger.warning("IV history error %s: %s", symbol, e)
    return pd.DataFrame(iv_data)

def calc_iv_rank_percentile(iv_series):
    iv_series = pd.Series(iv_series).dropna()
    if len(iv_series) < 5:
        return None, None
    current = iv_series.iloc[-1]
    hi, lo = iv_series.max(), iv_series.min()
    iv_rank = 100 * (current - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (iv_series < current).mean()
    return (round(iv_rank, 2) if iv_rank else None,
            round(iv_pct, 2) if iv_pct else None)

# ===== Email =====
def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = EMAIL_SENDER, EMAIL_RECEIVER, subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info("Email sent: %s", subject)
    except Exception as e:
        logger.error("Email failed: %s", e)

# ===== Alert CSV Writer =====
def log_alert_to_csv(alert):
    """
    Append alert (dict) to CSV file for long-term tracking.
    """
    csv_path = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    header = not os.path.exists(csv_path)
    try:
        df.to_csv(csv_path, mode='a', header=header, index=False)
    except Exception as e:
        logger.warning("Failed saving alert to CSV: %s", e)

# ===== Main Job =====
def job():
    rsi_alerts = []
    total, skipped = 0, 0

    for symbol in tickers:
        total += 1
        hist = fetch_cached_history(symbol)
        if hist.empty:
            skipped += 1
            continue

        hist = calculate_indicators(hist)
        signal, reason, rsi, price = generate_rsi_signal(hist)

        rt_price = price
        try:
            quote = finnhub_client.quote(symbol)
            rt_price = quote.get('c', price) if quote else price
        except Exception:
            pass

        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist['IV']) if not iv_hist.empty else (None, None)

        if signal:
            line = (
                f"{symbol}: {signal} at ${rt_price:.2f}, {reason}, "
                f"PE={pe if pe else 'N/A'}, MarketCap={mcap if mcap else 'N/A'}"
            )
            if iv_rank is not None:
                line += f", IV Rank={iv_rank}, IV Percentile={iv_pct}"
            rsi_alerts.append(line)

            # Save structured alert
            alert = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": symbol,
                "signal": signal,
                "price": rt_price,
                "rsi": round(rsi,2) if rsi else None,
                "pe_ratio": pe,
                "market_cap": mcap,
                "iv_rank": iv_rank,
                "iv_percentile": iv_pct
            }
            log_alert_to_csv(alert)

    # Summary
    if not rsi_alerts:
        logger.info("No alerts. Processed=%d, Skipped=%d, Alerts=0", total, skipped)
        print("No alerts found.")
        return

    email_body = "RSI Alerts (RSI <30 or >70):\n" + "\n".join(rsi_alerts)
    logger.info("Run summary: Processed=%d, Skipped=%d, Alerts=%d",
                total, skipped, len(rsi_alerts))
    logger.info("Alerts:\n%s", email_body)
    print(email_body)
    send_email("StockHome Trading Alerts", email_body)

if __name__ == "__main__":
    job()
