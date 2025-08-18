import os
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import config
import schedule
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ta.volatility import AverageTrueRange

# =================== CONFIG / SECRETS ===================
tickers = config.tickers
RSI_OVERSOLD = config.RSI_OVERSOLD
RSI_OVERBOUGHT = config.RSI_OVERBOUGHT

API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)


# =================== DATA FETCHING ===================
def fetch_historical_data_yfinance(symbol):
    ticker = yf.Ticker(symbol)
    return ticker.history(period="2y", interval="1d")


def fetch_fundamentals(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
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
            iv_data.append({
                'date': date,
                'IV': atm_call['impliedVolatility']
            })
    except Exception as e:
        print(f"Error fetching IV data for {symbol}: {e}")
    return pd.DataFrame(iv_data)


def fetch_real_time_quote(symbol):
    try:
        return finnhub_client.quote(symbol)
    except Exception:
        return None


# =================== INDICATORS ===================
def calculate_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    df['dma200'] = df['Close'].rolling(window=200).mean()
    df['dma50'] = df['Close'].rolling(window=50).mean()
    df['atr'] = AverageTrueRange(df['High'], df['Low'], df['Close'], window=14).average_true_range()
    return df


def calc_iv_rank_percentile(iv_series):
    iv_series = pd.Series(iv_series).dropna()
    if len(iv_series) < 5:
        return None, None
    current_iv = iv_series.iloc[-1]
    iv_high, iv_low = iv_series.max(), iv_series.min()
    iv_rank = 100 * (current_iv - iv_low) / (iv_high - iv_low) if (iv_high - iv_low) > 0 else None
    iv_percentile = 100 * (iv_series < current_iv).mean()
    return (round(iv_rank, 2) if iv_rank is not None else None,
            round(iv_percentile, 2) if iv_percentile is not None else None)


def generate_trade_signal(df):
    last = df.iloc[-1]
    rsi, price, dma50, dma200, atr = last['rsi'], last['Close'], last['dma50'], last['dma200'], last['atr']
    signal, reason = None, ""

    if pd.notna(rsi):
        if rsi < RSI_OVERSOLD and price > dma200:
            signal, reason = "BUY", f"RSI={rsi:.1f} < {RSI_OVERSOLD}, Price > 200DMA"
        elif rsi > RSI_OVERBOUGHT and price < dma200:
            signal, reason = "SELL", f"RSI={rsi:.1f} > {RSI_OVERBOUGHT}, Price < 200DMA"

    # Trend filter
    if dma50 > dma200:
        reason += " (Bullish Trend)"
    else:
        reason += " (Bearish Trend)"

    # Volatility filter
    atr_pct = 100 * atr / price if price > 0 else 0
    reason += f", ATR%={atr_pct:.2f}"

    return signal, reason, rsi, price


# =================== HELPERS ===================
def format_market_cap(market_cap):
    if market_cap is None:
        return "N/A"
    billion, million = 1_000_000_000, 1_000_000
    if market_cap >= billion:
        return f"{market_cap / billion:.2f}B"
    elif market_cap >= million:
        return f"{market_cap / million:.2f}M"
    return str(market_cap)


def log_alert(symbol, signal, price, reason, pe, market_cap, iv_rank, iv_pct):
    log_file = "alerts_log.csv"
    data = {
        "symbol": symbol, "signal": signal, "price": price,
        "reason": reason, "pe": pe, "market_cap": market_cap,
        "iv_rank": iv_rank, "iv_percentile": iv_pct,
        "timestamp": pd.Timestamp.now()
    }
    df = pd.DataFrame([data])
    if not os.path.exists(log_file):
        df.to_csv(log_file, index=False)
    else:
        df.to_csv(log_file, mode='a', header=False, index=False)


# =================== EMAIL ===================
def send_email(subject, body, html=True):
    msg = MIMEMultipart("alternative")
    msg['From'], msg['To'], msg['Subject'] = EMAIL_SENDER, EMAIL_RECEIVER, subject
    msg.attach(MIMEText(body, 'html' if html else 'plain'))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)


# =================== MAIN JOB ===================
def job():
    rsi_alerts = []

    for symbol in tickers:
        hist_data = fetch_historical_data_yfinance(symbol)
        if hist_data.empty:
            continue

        hist_data = calculate_indicators(hist_data)
        signal, reason, rsi, price = generate_trade_signal(hist_data)
        quote = fetch_real_time_quote(symbol)
        rt_price = quote.get("c", price) if quote else price
        pe, market_cap = fetch_fundamentals(symbol)

        iv_hist = fetch_option_iv_history(symbol, lookback_days=52)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist['IV'])

        if signal is not None:
            rsi_alerts.append({
                "symbol": symbol,
                "signal": signal,
                "price": rt_price,
                "reason": reason,
                "pe": pe if pe is not None else "N/A",
                "mcap": format_market_cap(market_cap),
                "iv_rank": iv_rank,
                "iv_pct": iv_pct
            })
            log_alert(symbol, signal, rt_price, reason, pe, market_cap, iv_rank, iv_pct)

    if not rsi_alerts:
        print("No alerts found.")
        return

    # Build HTML email
    email_body = """
    <h2>Trading Alerts</h2>
    <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Ticker</th><th>Signal</th><th>Price</th><th>Reason</th>
            <th>P/E</th><th>Market Cap</th><th>IV Rank</th><th>IV %ile</th>
        </tr>
    """
    for alert in rsi_alerts:
        email_body += f"""
        <tr>
            <td>{alert['symbol']}</td>
            <td>{alert['signal']}</td>
            <td>${alert['price']:.2f}</td>
            <td>{alert['reason']}</td>
            <td>{alert['pe']}</td>
            <td>{alert['mcap']}</td>
            <td>{alert['iv_rank'] if alert['iv_rank'] is not None else 'N/A'}</td>
            <td>{alert['iv_pct'] if alert['iv_pct'] is not None else 'N/A'}</td>
        </tr>
        """
    email_body += "</table>"

    print("Sending email with alerts...")
    send_email("StockHome Trading Alerts", email_body, html=True)


# =================== SCHEDULER ===================
if __name__ == "__main__":
    # Run once immediately
    job()

    # Schedule daily run at 1:00PM PT
    schedule.every().day.at("13:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)
