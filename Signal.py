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

# --- Secrets from environment (set via GitHub Actions or .env) ---
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

# --- Ticker fetchers ---
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return sorted(df['Symbol'].tolist())

def get_nasdaq100_tickers():
    url = "https://en.wikipedia.org/wiki/NASDAQ-100"
    tables = pd.read_html(url)
    for tbl in tables:
        if 'Ticker' in tbl.columns:
            return sorted(tbl['Ticker'].tolist())
    return []

# --- Regenerate tickers only on Sundays ---
today = datetime.datetime.today()
if today.weekday() == 6:  # Sunday = 6
    print("📈 Regenerating tickers (Sunday refresh)...")
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
        print(f"⚠️ Failed to refresh tickers: {e}. Using cached file.")

from tickers import all_tickers as tickers

# --- Data fetching ---
def fetch_bulk_historical(tickers, period="2y", interval="1d"):
    try:
        df = yf.download(tickers, period=period, interval=interval, group_by="ticker", threads=True)
        return df
    except Exception as e:
        print(f"Error bulk downloading: {e}")
        return pd.DataFrame()

def calculate_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    df['dma200'] = df['Close'].rolling(window=200).mean()
    return df

def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get('trailingPE', None), info.get('marketCap', None)
    except Exception as e:
        print(f"Error fundamentals {symbol}: {e}")
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
            underlying_price = ticker.history(period="1d")['Close'].iloc[-1]
            calls['distance'] = abs(calls['strike'] - underlying_price)
            atm_call = calls.loc[calls['distance'].idxmin()]
            iv_data.append({'date': date, 'IV': atm_call['impliedVolatility']})
    except Exception as e:
        print(f"Error IV {symbol}: {e}")
    return pd.DataFrame(iv_data)

def calc_iv_rank_percentile(iv_series):
    iv_series = pd.Series(iv_series).dropna()
    if len(iv_series) < 5:
        return None, None
    curr = iv_series.iloc[-1]
    hi, lo = iv_series.max(), iv_series.min()
    iv_rank = 100 * (curr - lo) / (hi - lo) if hi > lo else None
    iv_pct = 100 * (iv_series < curr).mean()
    return (
        round(iv_rank, 2) if iv_rank is not None else None,
        round(iv_pct, 2) if iv_pct is not None else None,
    )

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
    if mcap is None:
        return "N/A"
    if mcap >= 1_000_000_000:
        return f"{mcap/1_000_000_000:.2f}B"
    elif mcap >= 1_000_000:
        return f"{mcap/1_000_000:.2f}M"
    return str(mcap)

# --- Email ---
def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = EMAIL_SENDER, EMAIL_RECEIVER, subject
    msg.attach(MIMEText(body, 'plain'))
    server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

# --- Job ---
def job():
    rsi_alerts = []
    iv_alerts = []

    bulk_data = fetch_bulk_historical(tickers)

    for symbol in tickers:
        try:
            df = bulk_data[symbol].dropna() if isinstance(bulk_data.columns, pd.MultiIndex) else bulk_data
            if df.empty:
                continue

            df = calculate_indicators(df)
            signal, reason, rsi, price = generate_rsi_signal(df)

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
        except Exception as e:
            print(f"⚠️ {symbol} error: {e}")
            continue

    if not rsi_alerts:
        print("No alerts found.")
        return

    email_body = "RSI Alerts (RSI <30 or >70):\n" + "\n".join(rsi_alerts)
    print(email_body)
    send_email("StockHome Trading Alerts", email_body)

if __name__ == "__main__":
    job()
