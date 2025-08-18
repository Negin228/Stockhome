import os
import yfinance as yf
import finnhub
import pandas as pd
import ta
import smtplib
import config
from flask import Flask, render_template
from ta.volatility import AverageTrueRange
import datetime
from zoneinfo import ZoneInfo

# Initialize Flask app
app = Flask(__name__)

tickers = config.tickers
RSI_OVERSOLD = config.RSI_OVERSOLD
RSI_OVERBOUGHT = config.RSI_OVERBOUGHT

API_KEY = os.getenv("API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

finnhub_client = finnhub.Client(api_key=API_KEY)

# Your existing functions here (fetch_historical_data_yfinance, fetch_fundamentals, etc.)
# ... (use the full rewritten code you have for your job and helpers)

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

@app.route("/")
def index():
    alerts = []

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
            alerts.append({
                "symbol": symbol,
                "signal": signal,
                "price": rt_price,
                "reason": reason,
                "pe": pe if pe is not None else "N/A",
                "mcap": f"{market_cap/1_000_000_000:.2f}B" if market_cap else "N/A",
                "iv_rank": iv_rank,
                "iv_pct": iv_pct,
            })

    return render_template("index.html", alerts=alerts)

if __name__ == "__main__":
    # Run Flask app on localhost port 5000
    app.run(debug=True, host="0.0.0.0", port=5000)
