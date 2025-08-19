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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# = Setup Directories =
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

# = Logging setup: file + console with rotation =
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

# = Secrets from environment vars =
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
finnhub_client = finnhub.Client(api_key=API_KEY)

tickers = config.tickers

# = Fetch tickers (weekly cache) =
def get_sp500_tickers():
    df = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
    return sorted(df["Symbol"].dropna().tolist())

def get_nasdaq100_tickers():
    tables = pd.read_html("https://en.wikipedia.org/wiki/NASDAQ-100")
    for tbl in tables:
        if "Ticker" in tbl.columns:
            return sorted(tbl["Ticker"].dropna().tolist())
    return []

# = RETRY WRAPPER =
def fetch_with_retry(func, *args, retries=5, delay=60, **kwargs):
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if 'Too Many Requests' in str(e) or 'Rate limited' in str(e) or '429' in str(e):
                wait = delay * (2 ** attempt)
                logger.warning(f"Rate limit hit, sleeping {wait}s before retry...")
                time.sleep(wait)
            else:
                raise
    logger.error("Max retries exceeded.")
    return None

# = HISTORICAL DATA with cache =
def safe_download(symbol, *args, **kwargs):
    def _download():
        return yf.download(symbol, *args, **kwargs)
    return fetch_with_retry(_download)

def fetch_cached_history(symbol, period="2y", interval="1d"):
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df, force_full = None, False
    if os.path.exists(file_path):
        age_days = (datetime.datetime.now() -
                    datetime.datetime.fromtimestamp(os.path.getmtime(file_path))).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            logger.info("%s cache too old (%d days) → full refresh", symbol, age_days)
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            except Exception:
                df = None
    if df is None or df.empty or force_full:
        try:
            logger.info("⬇️ Downloading full history: %s", symbol)
            df = safe_download(symbol, period=period, interval=interval, auto_adjust=False)
        except Exception as e:
            logger.error("Download error %s: %s", symbol, e)
            return pd.DataFrame()
    else:
        last_date = df.index[-1]
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        logger.info("🔄 Updating %s from %s", symbol, start)
        try:
            new_df = safe_download(symbol, start=start, interval=interval, auto_adjust=False)
            if new_df is not None and not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
        except Exception as e:
            logger.warning("Update error %s: %s", symbol, e)
    try:
        df.to_csv(file_path)
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", symbol, e)
    return df

# = INDICATORS =
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

# = FUNDAMENTALS & IV =
def fetch_fundamentals(symbol):
    def _fetch():
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    try:
        return fetch_with_retry(_fetch)
    except Exception as e:
        logger.warning("Fundamentals error %s: %s", symbol, e)
        return None, None

def fetch_option_iv_history(symbol, lookback_days=52):
    def _fetch():
        iv_data = []
        ticker = yf.Ticker(symbol)
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

# = IV Rank Calculation =
def calc_iv_rank_percentile(iv_series):
    s = pd.Series(iv_series).dropna()
    if len(s) < 5:
        return None, None
    cur, hi, lo = s.iloc[-1], s.max(), s.min()
    iv_rank = 100 * (cur - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (s < cur).mean()
    return round(iv_rank, 2) if iv_rank else None, round(iv_pct, 2) if iv_pct else None

# = EMAIL SEND =
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
        logger.error("Email failed: %s", e)

# = ALERT CSV =
def log_alert(alert):
    csv_path = config.ALERTS_CSV
    df = pd.DataFrame([alert])
    header = not os.path.exists(csv_path)
    df.to_csv(csv_path, mode="a", header=header, index=False)

# = MAIN JOB =
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
