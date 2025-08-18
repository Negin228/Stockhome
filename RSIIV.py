import os
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import config
tickers = config.tickers
RSI_OVERSOLD = config.RSI_OVERSOLD
RSI_OVERBOUGHT = config.RSI_OVERBOUGHT


from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load secrets from environment variables (set in GitHub Actions secrets)
API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

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
    signal = None
    reason = ""
    if pd.notna(rsi):
        if rsi < RSI_OVERSOLD:
            signal = "BUY"
            reason = f"RSI={rsi:.1f} < {RSI_OVERSOLD}"
        elif rsi > RSI_OVERBOUGHT:
            signal = "SELL"
            reason = f"RSI={rsi:.1f} > {RSI_OVERBOUGHT}"
    return signal, reason, rsi, price

def fetch_real_time_quote(symbol):
    try:
        quote = finnhub_client.quote(symbol)
        return quote
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

def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    server = smtplib.SMTP('smtp.gmail.com', 587)  # change SMTP server if needed
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

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

        # RSI Alerts with IV, P/E, Market Cap
        if signal is not None:
            line = (f"{symbol}: {signal} at real-time price ${rt_price:.2f}, {reason}, "
                    f"PE={pe if pe is not None else 'N/A'}, MarketCap={format_market_cap(market_cap)}")
            if iv_rank is not None and iv_pct is not None:
                line += f", IV Rank={iv_rank}, IV Percentile={iv_pct}"
            rsi_alert_lines.append(line)

        # IV Alerts (threshold met) with RSI, P/E, Market Cap
        if (iv_rank is not None and iv_rank >= 60) or (iv_pct is not None and iv_pct >= 70):
            iv_line = (f"{symbol}: IV Rank={iv_rank}, IV Percentile={iv_pct}, RSI={rsi:.1f}, "
                       f"PE={pe if pe is not None else 'N/A'}, MarketCap={format_market_cap(market_cap)}, "
                       f"real-time price ${rt_price:.2f}")
            iv_alert_lines.append(iv_line)

    # Output and email RSI alerts
    if rsi_alert_lines:
        output1 = "RSI Alerts with IV, P/E, Market Cap:\n" + "\n".join(rsi_alert_lines)
        print(output1)
        send_email("RSI Alerts with IV and Fundamentals", output1)
    else:
        print("No RSI alerts found.")

    print("\n----------------------------\n")

    # Output and email IV Alerts
    if iv_alert_lines:
        output2 = "IV Alerts (Rank ≥ 60 or Percentile ≥ 70) with RSI, P/E, Market Cap:\n" + "\n".join(iv_alert_lines)
        print(output2)
        send_email("IV Alerts with RSI and Fundamentals", output2)
    else:
        print("No IV alerts found.")

if __name__ == "__main__":
    job()



