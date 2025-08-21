import config
import yfinance as yf
import ta
import pandas as pd

def calculate_rsi(series, window=14):
    return ta.momentum.RSIIndicator(series, window=window).rsi().iloc[-1]

def filter_tickers(pe_threshold=30, rsi_threshold=30):
    filtered = []
    for symbol in config.tickers:
        try:
            ticker = yf.Ticker(symbol)
            pe = ticker.info.get("trailingPE", None)
            hist = ticker.history(period="1mo", interval="1d")
            if hist.empty:
                continue
            rsi = calculate_rsi(hist["Close"])
        except Exception:
            continue
        if pe is not None and pe < pe_threshold and rsi is not None and rsi < rsi_threshold:
            filtered.append(symbol)
    return filtered

if __name__ == "__main__":
    filtered_list = filter_tickers()
    with open("filtered_tickers.txt", "w") as f:
        f.write("\n".join(filtered_list))
