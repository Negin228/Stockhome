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
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from curl_cffi import requests  # To create impersonated session

# Setup directories
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

# Logging setup
log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(log_path, maxBytes=config.LOG_MAX_BYTES,
                                   backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8")
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# Secrets
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# Finnhub client
finnhub_client = finnhub.Client(api_key=API_KEY)

# yfinance session with Chrome impersonation to reduce throttling
yf_session = requests.Session(impersonate="chrome")

tickers = config.tickers

# Retry wrapper with max exponential backoff and jitter
def fetch_with_retry(func, *args, retries=5, delay=60, max_delay=130, **kwargs):
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            if 'Too Many Requests' in err_str or 'Rate limited' in err_str or '429' in err_str:
                wait = min(delay * (2 ** attempt), max_delay) + random.uniform(0, 5)
                logger.warning(f"Rate limit hit, sleeping {wait:.1f}s before retry [{attempt+1}/{retries}]...")
                time.sleep(wait)
            else:
                raise
    logger.error("Max retries exceeded during fetch_with_retry.")
    return None

# Safe download using retry and session
def safe_download(symbol, *args, **kwargs):
    def _download():
        return yf.download(symbol, *args, session=yf_session, **kwargs)
    return fetch_with_retry(_download)

def fetch_cached_history(symbol, period="2y", interval="1d"):
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df, force_full = None, False
    if os.path.exists(file_path):
        age_days = (datetime.datetime.now() -
                    datetime.datetime.fromtimestamp(os.path.getmtime(file_path))).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            logger.info(f"{symbol} cache too old ({age_days} days) → full refresh")
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            except Exception:
                df = None
    if df is None or df.empty or force_full:
        try:
            logger.info(f"⬇️ Downloading full history: {symbol}")
            df = safe_download(symbol, period=period, interval=interval, auto_adjust=False)
        except Exception as e:
            logger.error(f"Download error {symbol}: {e}")
            return pd.DataFrame()
    else:
        last_date = df.index[-1]
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        logger.info(f"🔄 Updating {symbol} from {start}")
        try:
            new_df = safe_download(symbol, start=start, interval=interval, auto_adjust=False)
            if new_df is not None and not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning(f"Update error {symbol}: {e}")
    try:
        df.to_csv(file_path)
    except Exception as e:
        logger.warning(f"Cache save failed for {symbol}: {e}")
    return df

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

def fetch_fundamentals(symbol):
    def _fetch():
        ticker = yf.Ticker(symbol, session=yf_session)
        info = ticker.info
        return info.get("trailingPE", None), info.get("marketCap", None)
    try:
        return fetch_with_retry(_fetch)
    except Exception as e:
        logger.warning(f"Fundamentals error {symbol}: {e}")
        return None, None

def fetch_option_iv_history(symbol, lookback_days=52):
    def _fetch():
        iv_data = []
        ticker = yf.Ticker(symbol, session=yf_session)
        for date in ticker.options[-lookback_days:]:
            chain = ticker.option_chain(date)
            if chain.calls.empty:
                continue
            under = ticker.history(period="1d")["Close"].iloc[-1]
            chain.calls["distance"] = abs(chain.calls["strike"] - under)
            atm = chain.calls.loc[chain.calls["distance"].idxmin()]
            iv_data.append({"date": date, "IV": atm["impliedVolatility"]})
        return pd.DataFrame(iv_data)
    try:
        return fetch_with_retry(_fetch)
    except Exception as e:
        logger.warning(f"IV history error {symbol}: {e}")
        return pd.DataFrame()

def safe_finnhub_quote(symbol):
    def _quote():
        return finnhub_client.quote(symbol)
    return fetch_with_retry(_quote)

def calc_iv_rank_percentile(iv_series):
    s = pd.Series(iv_series).dropna()
    if len(s) < 5:
        return None, None
    cur, hi, lo = s.iloc[-1], s.max(), s.min()
    iv_rank = 100 * (cur - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (s < cur).mean()
    return round(iv_rank, 2) if iv_rank else None, round(iv_pct, 2) if iv_pct else None

def send_email(subject, body):
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
        logger.error(f"Email failed: {e}")

def log_alert(alert):
    csv_path = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode="a", header=header, index=False)

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
        sig, reason, rsi, price = generate_rsi_signal(hist)
        try:
            quote = safe_finnhub_quote(symbol)
            rt_price = quote.get("c", price) if quote else price
        except Exception:
            rt_price = price
        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"]) if not iv_hist.empty else (None, None)
        if sig:
            line = f"{symbol}: {sig} at ${rt_price:.2f}, {reason}, PE={pe or 'N/A'}, MarketCap={mcap or 'N/A'}"
            if iv_rank:
                line += f", IV Rank={iv_rank}, IV Percentile={iv_pct}"
            rsi_alerts.append(line)
            log_alert({
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": symbol, "signal": sig, "price": rt_price,
                "rsi": round(rsi, 2) if rsi else None,
                "pe_ratio": pe, "market_cap": mcap,
                "iv_rank": iv_rank, "iv_percentile": iv_pct
            })
        # Sleep a fixed 2 seconds between tickers to avoid hitting rate limits
        time.sleep(2)

    if not rsi_alerts:
        logger.info(f"No alerts. Processed={total}, Skipped={skipped}, Alerts=0")
        print("No alerts found.")
        return

    email_body = "RSI Alerts (RSI <30 or >70):\n" + "\n".join(rsi_alerts)
    logger.info(f"SUMMARY: Processed={total}, Skipped={skipped}, Alerts={len(rsi_alerts)}")
    print(email_body)
    send_email("StockHome Trading Alerts", email_body)

if __name__ == "__main__":
    job()
