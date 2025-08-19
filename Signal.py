import os
import datetime
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import config
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Load credentials ---
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

# Ensure data directory exists
os.makedirs(config.DATA_DIR, exist_ok=True)

# ===== Ticker Fetching =====
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

# Refresh tickers on Sunday
today = datetime.datetime.today()
if today.weekday() == 6:  # Sunday
    print("📈 Refreshing ticker list...")
    try:
        sp500 = get_sp500_tickers()
        nasdaq100 = get_nasdaq100_tickers()
        all_tickers = sorted(set(sp500 + nasdaq100))

        with open("tickers.py", "w") as f:
            f.write("# Auto-generated ticker lists\n\n")
            f.write("sp500_tickers = " + repr(sp500) + "\n\n")
            f.write("nasdaq100_tickers = " + repr(nasdaq100) + "\n\n")
            f.write("all_tickers = " + repr(all_tickers) + "\n")
    except Exception as e:
        print(f"⚠️ Could not refresh tickers: {e}")

from tickers import all_tickers as tickers

# ===== Data Caching with Expiry =====
def fetch_cached_history(symbol, period="2y", interval="1d"):
    """
    Uses local CSV cache if available.
    Updates last 5 days daily, but if cache older than MAX_CACHE_AGE_DAYS, full refresh.
    """
    file_path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df = None
    force_full = False

    if os.path.exists(file_path):
        # Check file age
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        age_days = (datetime.datetime.now() - mtime).days
        if age_days > config.MAX_CACHE_AGE_DAYS:
            print(f"⏳ Cache too old for {symbol} ({age_days} days). Forcing full refresh.")
            force_full = True
        else:
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            except Exception:
                df = None

    if df is None or df.empty or force_full:
        print(f"⬇️ Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
    else:
        # Incremental update
        last_date = df.index[-1]
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        print(f"🔄 Updating {symbol} from {start}")
        new_df = yf.download(symbol, start=start, interval=interval, auto_adjust=False)
        if not new_df.empty:
            df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()

    # Save back
    try:
        df.to_csv(file_path)
    except Exception as e:
        print(f"⚠️ Could not save cache for {symbol}: {e}")

    return df

# ===== Indicators =====
def calculate_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    df['dma200'] = df['Close'].rolling(window=200).mean()
    return df

# ===== Fundamentals & IV =====
def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get('trailingPE', None), info.get('marketCap', None)
    except Exception:
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
            atm_call = calls.loc[calls['distance'].idxmin()]
            iv_data.append({'date': date, 'IV': atm_call['impliedVolatility']})
    except Exception:
        pass
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

# ===== Signals =====
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

def fetch_real_time_quote(symbol):
    try:
        return finnhub_client.quote(symbol)
    except Exception:
        return None

def format_market_cap(mcap):
    if mcap is None: return "N/A"
    if mcap >= 1_000_000_000: return f"{mcap/1_000_000_000:.2f}B"
    if mcap >= 1_000_000: return f"{mcap/1_000_000:.2f}M"
    return str(mcap)

# ===== Email =====
def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = EMAIL_SENDER, EMAIL_RECEIVER, subject
    msg.attach(MIMEText(body, 'plain'))
    server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

# ===== Main Job =====
def job():
    rsi_alerts = []

    for symbol in tickers:
        hist = fetch_cached_history(symbol)
        if hist.empty:
            continue

        hist = calculate_indicators(hist)
        signal, reason, rsi, price = generate_rsi_signal(hist)

        quote = fetch_real_time_quote(symbol)
        rt_price = quote.get('c', price) if quote else price
        pe, mcap = fetch_fundamentals(symbol)

        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"]) if not iv_hist.empty else (None, None)

        if signal:
            line = (
                f"{symbol}: {signal} at ${rt_price:.2f}, {reason}, "
                f"PE={pe if pe else 'N/A'}, MarketCap={format_market_cap(mcap)}"
            )
            if iv_rank is not None:
                line += f", IV Rank={iv_rank}, IV Percentile={iv_pct}"
            rsi_alerts.append(line)

    if not rsi_alerts:
        print("No alerts found.")
        return

    email_body = "RSI Alerts (RSI <30 or >70):\n" + "\n".join(rsi_alerts)
    print(email_body)
    send_email("StockHome Trading Alerts", email_body)

if __name__ == "__main__":
    job()
