import os
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import config

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load secrets from environment variables (set in GitHub Actions secrets)
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

# --- Fetch ticker lists ---
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

# Fetch lists
sp500 = get_sp500_tickers()
nasdaq100 = get_nasdaq100_tickers()

# Merge lists (deduplicated)
all_tickers = sorted(set(sp500 + nasdaq100))

# Write ticker lists to tickers.py
with open("tickers.py", "w") as f:
    f.write("# Auto-generated ticker lists\n\n")
    f.write("sp500_tickers = " + repr(sp500) + "\n\n")
    f.write("nasdaq100_tickers = " + repr(nasdaq100) + "\n\n")
    f.write("all_tickers = " + repr(all_tickers) + "\n")

# Import the generated all_tickers
from tickers import all_tickers as tickers

# --- Data fetching & calculations ---
def fetch_historical_data_yfinance(symbol):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="2y", interval="1d")
    return hist

def calculate_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    df['dma200'] = df['Close'].rolling(window=200).mean()
    return df

def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        pe = info.get('trailingPE', None)
        market_cap = info.get('marketCap', None)
        return pe, market_cap
    except Exception as e:
        print(f"Error retrieving fundamentals for {symbol}: {e}")
        return None, None

def fetch_option_iv_history(symbol, lookback_days=52):
    ticker = yf.Ticker(symbol)
    iv_data = []
    try:
        opt_dates = ticker.options
        for date in opt_dates[-lookback_days:]:
            opt_chain = ticker.option_chain(date)
            calls = opt_chain.calls
            if calls.empty:
                continue
            underlying_price = ticker.history(period="1d")['Close'].iloc[-1]
            calls['distance'] = abs(calls['strike'] - underlying_price)
            atm_call = calls.loc[calls['distance'].idxmin()]
            iv_row = {
                'date': date,
                'IV': atm_call['impliedVolatility']
            }
            iv_data.append(iv_row)
    except Exception as e:
        print(f"Error fetching IV data for {symbol}: {e}")
    return pd.DataFrame(iv_data)

def calc_iv_rank_percentile(iv_series):
    iv_series = pd.Series(iv_series).dropna()
    if len(iv_series) < 5:
        return None, None
    current_iv = iv_series.iloc[-1]
    iv_high = iv_series.max()
    iv_low = iv_series.min()
    iv_rank = 100 * (current_iv - iv_low) / (iv_high - iv_low) if (iv_high - iv_low) > 0 else None
    iv_percentile = 100 * (iv_series < current_iv).mean()
    iv_rank = round(iv_rank, 2) if iv_rank is not None else None
    iv_percentile = round(iv_percentile, 2) if iv_percentile is not None else None
    return iv_rank, iv_percentile

def generate_rsi_only_signals(df):
    last = df.iloc[-1]
    rsi = last['rsi']
    price = last['Close']
    signal, reason = None, ""
    if pd.notna(rsi):
        if rsi < config.RSI_OVERSOLD:
            signal = "BUY"
            reason = f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
        elif rsi > config.RSI_OVERBOUGHT:
            signal = "SELL"
            reason = f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return signal, reason, rsi, price

def fetch_real_time_quote(symbol):
    try:
        return finnhub_client.quote(symbol)
    except Exception:
        return None

def format_market_cap(market_cap):
    if market_cap is None:
        return "N/A"
    billion = 1_000_000_000
    million = 1_000_000
    if market_cap >= billion:
        return f"{market_cap / billion:.2f}B"
    elif market_cap >= million:
        return f"{market_cap / million:.2f}M"
    else:
        return str(market_cap)

# --- Email ---
def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

# --- Main Job ---
def job():
    rsi_alert_lines = []
    iv_alert_lines = []

    for symbol in tickers:
        hist_data = fetch_historical_data_yfinance(symbol)
        if hist_data.empty:
            continue

        hist_data = calculate_indicators(hist_data)
        signal, reason, rsi, price = generate_rsi_only_signals(hist_data)

        quote = fetch_real_time_quote(symbol)
        rt_price = quote.get('c', price) if quote else price

        pe, market_cap = fetch_fundamentals(symbol)

        iv_hist = fetch_option_iv_history(symbol, lookback_days=52)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist['IV'])

        if signal is not None:
            line = (
                f"{symbol}: {signal} at real-time price ${rt_price:.2f}, {reason}, "
                f"PE={pe if pe is not None else 'N/A'}, MarketCap={format_market_cap(market_cap)}"
            )
            if iv_rank is not None and iv_pct is not None:
                line += f", IV Rank={iv_rank}, IV Percentile={iv_pct}"
            rsi_alert_lines.append(line)

    if not rsi_alert_lines and not iv_alert_lines:
        print("No alerts found.")
        return

    email_body = ""
    if rsi_alert_lines:
        email_body += "RSI Alerts (RSI < 30 or > 70):\n" + "\n".join(rsi_alert_lines) + "\n\n"
    if iv_alert_lines:
        email_body += "IV Alerts (Rank ≥ 60 or Percentile ≥ 70):\n" + "\n".join(iv_alert_lines)

    print(email_body)
    send_email("StockHome Trading Alerts", email_body)

if __name__ == "__main__":
    job()
