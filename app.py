import os
import yfinance as yf
import finnhub
import pandas as pd
import ta
from flask import Flask, render_template
from flask_caching import Cache
from ta.volatility import AverageTrueRange
import concurrent.futures
import config

app = Flask(__name__)

# Configure cache
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 3600})

tickers = config.tickers
RSI_OVERSOLD = config.RSI_OVERSOLD
RSI_OVERBOUGHT = config.RSI_OVERBOUGHT
API_KEY = os.getenv("API_KEY")
finnhub_client = finnhub.Client(api_key=API_KEY)

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
    if dma50 > dma200:
        reason += " (Bullish Trend)"
    else:
        reason += " (Bearish Trend)"
    atr_pct = 100 * atr / price if price > 0 else 0
    reason += f", ATR%={atr_pct:.2f}"
    return signal, reason, rsi, price

def process_ticker(symbol):
    hist_data = fetch_historical_data_yfinance(symbol)
    if hist_data.empty:
        return None
    
    hist_data['rsi'] = ta.momentum.RSIIndicator(hist_data['Close'], window=14).rsi()
    last_rsi = hist_data['rsi'].iloc[-1]
    
    if pd.isna(last_rsi) or not (last_rsi < 30 or last_rsi > 70):
        return None
    
    hist_data['dma200'] = hist_data['Close'].rolling(window=200).mean()
    hist_data['dma50'] = hist_data['Close'].rolling(window=50).mean()
    hist_data['atr'] = AverageTrueRange(hist_data['High'], hist_data['Low'], hist_data['Close'], window=14).average_true_range()
    
    signal, reason, rsi, price = generate_trade_signal(hist_data)
    if signal is None:
        return None
    
    quote = fetch_real_time_quote(symbol)
    rt_price = quote.get("c", price) if quote else price
    
    pe, market_cap = fetch_fundamentals(symbol)
    iv_hist = fetch_option_iv_history(symbol, lookback_days=52)
    iv_rank, iv_pct = (None, None)
    if not iv_hist.empty:
        iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist['IV'])
    
    return {
        "symbol": symbol,
        "signal": signal,
        "price": rt_price,
        "reason": reason,
        "pe": pe if pe is not None else "N/A",
        "mcap": f"{market_cap/1_000_000_000:.2f}B" if market_cap else "N/A",
        "iv_rank": iv_rank,
        "iv_pct": iv_pct,
    }

@cache.cached(timeout=3600, key_prefix='all_tickers_data')
@app.route("/")
def index():
    alerts = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = list(executor.map(process_ticker, tickers))
    alerts = [result for result in results if result is not None]
    return render_template("index.html", alerts=alerts)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
