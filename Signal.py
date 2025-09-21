import os
import datetime
import json
import yfinance as yf
import finnhub
import pandas as pd
import ta
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
import argparse
import time
import numpy as np
from dateutil.parser import parse
import config
from news_fetcher import fetch_news_ticker
from newspaper import Article
#import openai
#from transformers import pipeline
import re


puts_dir = "puts_data"
os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)
os.makedirs(puts_dir, exist_ok=True)

log_path = os.path.join(config.LOG_DIR, config.LOG_FILE)
logger = logging.getLogger("StockHome")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(log_path, maxBytes=config.LOG_MAX_BYTES, backupCount=config.LOG_BACKUP_COUNT, encoding='utf-8')
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

API_KEY = os.getenv("API_KEY")
tickers = config.tickers
finnhub_client = finnhub.Client(api_key=API_KEY)

MAX_API_RETRIES = 5
API_RETRY_INITIAL_WAIT = 60
MAX_TICKER_RETRIES = 100
TICKER_RETRY_WAIT = 60


def retry_on_rate_limit(func):
    def wrapper(*args, **kwargs):
        wait = API_RETRY_INITIAL_WAIT
        for attempt in range(MAX_API_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                e_str = str(e).lower()
                if any(term in e_str for term in ["rate limit", "too many requests", "429"]):
                    logger.warning(f"Rate limit hit on {func.__name__}, attempt {attempt + 1}/{MAX_API_RETRIES}: {e}")
                    logger.info(f"Sleeping for {wait} seconds before retry")
                    time.sleep(wait)
                    wait *= 2
                    continue
                raise
        logger.error(f"Exceeded max retries for {func.__name__} with args {args}, kwargs {kwargs}")
        raise
    return wrapper




def force_float(val):
    if isinstance(val, (pd.Series, np.ndarray)):
        return float(val.iloc[-1]) if hasattr(val, "iloc") and not val.empty else None
    if isinstance(val, pd.DataFrame):
        return float(val.values[-1][0])
    return float(val) if val is not None else None


def extend_to_next_period(text):
    if not text or not text.strip():
        return ""
    # If already ends in period, no change needed
    if text.strip().endswith('.'):
        return text.strip()
    # Find position of next period after the last character
    idx = text.find('.')
    # If no period, just return the whole string
    if idx == -1:
        return text.strip()
    # If summary doesn't start at the beginning, append up to next period after its current length
    # meaning, the summary is possibly a truncated portion of a full sentence or paragraph
    # So we want: everything from beginning up to first period after existing summary
    match = re.search(r'^(.*?\\.)', text)
    if match:
        return match.group(1).strip()
    return text.strip()




@retry_on_rate_limit
def fetch_cached_history(symbol, period="2y", interval="1d"):
    path = os.path.join(config.DATA_DIR, f"{symbol}.csv")
    df = None
    force_full = False
    if os.path.exists(path):
        age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age_days > config.MAX_CACHE_DAYS:
            force_full = True
            logger.info(f"Cache for {symbol} is stale ({age_days} days), refreshing")
        else:
            try:
                cols = ['Date', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
                #cols = ['Date', 'Price', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
                df = pd.read_csv(path, skiprows=3, names=cols)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df.set_index('Date', inplace=True)
                if df.index.hasnans:
                    logger.warning(f"Cache date parsing failed for {symbol}, refreshing cache")
                    force_full = True
            except Exception as e:
                logger.warning(f"Failed reading cache for {symbol}: {e}")
                df = None
    if df is None or df.empty or force_full:
        logger.info(f"Downloading full history for {symbol}")
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df.to_csv(path)
    else:
        try:
            last = df.index[-1]
            if not isinstance(last, pd.Timestamp):
                last = pd.to_datetime(last)
            start_date = (last - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            logger.info(f"Updating {symbol} from {start_date}")
            new_df = yf.download(symbol, start=start_date, interval=interval, auto_adjust=False)
            if not new_df.empty:
                df = pd.concat([df, new_df]).groupby(level=0).last().sort_index()
                df.to_csv(path)
        except Exception as e:
            logger.warning(f"Incremental update failed for {symbol}: {e}")
    return df
@retry_on_rate_limit
def fetch_quote(symbol):
    quote = finnhub_client.quote(symbol)
    price = quote.get("c", None)
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return None
    return price

def calculate_indicators(df):
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["dma200"] = close.rolling(200).mean()
    return df

def generate_signal(df):
    if df.empty or "rsi" not in df.columns:
        return None, ""
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None, ""
    price = df["Close"].iloc[-1] if "Close" in df.columns else np.nan
    if rsi < config.RSI_OVERSOLD:
        return "BUY", f"RSI={rsi:.1f} < {config.RSI_OVERSOLD}"
    if rsi > config.RSI_OVERBOUGHT:
        return "SELL", f"RSI={rsi:.1f} > {config.RSI_OVERBOUGHT}"
    return None, ""

def fetch_fundamentals_safe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("trailingPE", None), info.get("marketCap", None)
    except Exception as e:
        logger.warning(f"Failed to fetch fundamentals for {symbol}: {e}")
        return None, None

def fetch_puts(symbol):
    puts_data = []
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.datetime.now()
        valid_dates = [d for d in getattr(ticker, 'options', []) if (parse(d) - today).days <= 49]
        for exp in valid_dates:
            chain = ticker.option_chain(exp)
            if chain.puts.empty:
                continue
            under_price = ticker.history(period="1d")["Close"].iloc[-1]
            chain.puts["distance"] = abs(chain.puts["strike"] - under_price)
            for _, put in chain.puts.iterrows():
                strike = put["strike"]
                premium = put.get("lastPrice") or ((put.get("bid") + put.get("ask")) / 2 if (put.get("bid") is not None and put.get("ask") is not None) else None)
                puts_data.append({
                    "expiration": exp,
                    "strike": strike,
                    "premium": premium,
                    "stock_price": under_price
                })
    except Exception as e:
        logger.warning(f"Failed to fetch puts for {symbol}: {e}")
    return puts_data

def format_buy_alert_line(ticker, price, rsi, pe, mcap, strike, expiration, premium, delta_percent, premium_percent):
    price_str = f"{price:.2f}" if price is not None else "N/A"
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    pe_str = f"{pe:.1f}" if pe is not None else "N/A"
    strike_str = f"{strike:.1f}" if strike is not None else "N/A"
    premium_str = f"{premium:.2f}" if premium is not None else "N/A"
    dp = f"{delta_percent:.1f}%" if delta_percent is not None else "N/A"
    pp = f"{premium_percent:.1f}%" if premium_percent is not None else "N/A"
    metric_sum = None
    if (delta_percent is not None) and (premium_percent is not None):
        metric_sum = delta_percent + premium_percent
    metric_sum_str = f"{metric_sum:.1f}%" if metric_sum is not None else "N/A"
    return (
        #f"{ticker} (${price_str}) | "
        f"RSI={rsi_str} "
        f"P/E={pe_str} "
        f"Market Cap=${mcap}\n"
        f"${strike_str} strike & "
        f"${premium_str} premium on {expiration}, "
        f"[𝚫 {dp} + 💎 {pp}] = {metric_sum_str}"
    )

def format_sell_alert_line(ticker, price, rsi, pe, mcap):
    #price_str = f"{price:.2f}" if price is not None else "N/A"
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    pe_str = f"{pe:.1f}" if pe is not None else "N/A"
    #return f"{ticker} (${price_str}) | RSI={rsi_str}, P/E={pe_str}, Market Cap=${mcap}"
    return f"RSI={rsi_str}, P/E={pe_str}, Market Cap=${mcap}"

def calculate_custom_metrics(puts, price):
    if price is None or price <= 0 or np.isnan(price):
        return puts
    for p in puts:
        strike = p.get("strike")
        premium = p.get("premium") or 0.0
        try:
            premium_val = float(premium)
            p["custom_metric"] = ((price - strike) + premium_val / 100) / price * 100 if strike else None
            p["delta_percent"] = ((price - strike) / price) * 100 if strike else None
            p["premium_percent"] = premium_val / price * 100 if premium_val else None
        except Exception as e:
            logger.warning(f"Error computing metrics for put {p}: {e}")
            p["custom_metric"] = p["delta_percent"] = p["premium_percent"] = None
    return puts

def format_market_cap(mcap):
    if not mcap:
        return "N/A"
    if mcap >= 1e9:
        return f"{mcap / 1e9:.1f}B"
    if mcap >= 1e6:
        return f"{mcap / 1e6:.1f}M"
    return str(mcap)


def log_alert(alert):
    csv_path = config.ALERTS_CSV
    exists = os.path.exists(csv_path)
    df_new = pd.DataFrame([alert])
    df_new.to_csv(csv_path, mode='a', header=not exists, index=False)



def job(tickers):
    sell_alerts = []
    all_sell_alerts = []
    buy_symbols = []
    buy_alerts_web = []
    prices = {}
    rsi_vals = {}
    failed = []
    total = skipped = 0
    for symbol in tickers:
        total += 1
        try:
            hist = fetch_cached_history(symbol)
            if hist.empty or "Close" not in hist.columns:
                logger.info(f"No historical data for {symbol}, skipping.")
                skipped += 1
                continue
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limited on fetching history for {symbol}, retry delayed.")
                failed.append(symbol)
                continue
            if any(k in msg for k in ["delisted", "no data", "not found"]):
                logger.info(f"{symbol} delisted or no data, skipping.")
                skipped += 1
                continue
            logger.error(f"Error fetching history for {symbol}: {e}")
            skipped += 1
            continue
        hist = calculate_indicators(hist)
        sig, reason = generate_signal(hist)
        if not sig:
            continue
        try:
            rt_price = fetch_quote(symbol)
            rt_price = force_float(rt_price)


        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limit on price for {symbol}, waiting then retrying.")
                time.sleep(TICKER_RETRY_WAIT)
                try:
                    rt_price = fetch_quote(symbol)
                    rt_price = force_float(rt_price)


                except Exception as e2:
                    logger.error(f"Failed second price fetch for {symbol}: {e2}")
                    rt_price = None
            else:
                logger.error(f"Error fetching price for {symbol}: {e}")
                rt_price = None
         
        if rt_price is None or (isinstance(rt_price, float) and (np.isnan(rt_price) or rt_price <= 0)):
            rt_price = force_float(hist["Close"].iloc[-1] if not hist.empty else None)
        if rt_price is None or (isinstance(rt_price, float) and (np.isnan(rt_price) or rt_price <= 0)):
            logger.warning(f"Invalid price for {symbol}, skipping.")
            skipped += 1
            continue
        pe, mcap = fetch_fundamentals_safe(symbol)
        cap_str = format_market_cap(mcap)
        rsi_val = hist["rsi"].iloc[-1] if "rsi" in hist.columns else None
        pe_str = f"{pe:.1f}" if pe else "N/A"
        parts = [
            f"{symbol}: {sig} at ${rt_price:.2f}",
            reason,
            f"PE={pe_str}",
            f"Market Cap={cap_str}",
        ]
        alert_line = ", ".join(parts)
        alert_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": symbol,
            "signal": sig,
            "price": rt_price,
            "rsi": rsi_val,
            "pe_ratio": pe,
            "market_cap": mcap,
        }
        log_alert(alert_data)
        if sig == "BUY":
            buy_symbols.append(symbol)
            prices[symbol] = rt_price
            rsi_vals[symbol] = rsi_val
        else:
            sell_alert_line = format_sell_alert_line(
                ticker=symbol,
                price=rt_price,
                rsi=rsi_val,
                pe=pe,
                mcap=cap_str)
            #sell_alerts.append(sell_alert_line)
            sell_alert_html = f"""
                <div class="main-info">
                    <div>
                        <span class="ticker-alert">{symbol}</span>
                    </div>
                    <div class="price-details">
                        <div class="current-price price-down">{rt_price:.2f}</div>
                    </div>
                </div>
                <p class="news-summary">
                    {sell_alert_line}
                </p>
            """
            all_sell_alerts.append(sell_alert_html)
            
    # Options section (only for BUY signals)
    for sym in buy_symbols:
        price = prices.get(sym)
        pe, mcap = fetch_fundamentals_safe(sym)
        cap_str = format_market_cap(mcap)
        #hist = fetch_cached_history(sym)
        #rsi_val = hist["rsi"].iloc[-1] if "rsi" in hist.columns else None
        rsi_val = rsi_vals.get(sym, None)
        puts_list = fetch_puts(sym)
        puts_list = calculate_custom_metrics(puts_list, price)
        filtered_puts = [
            p for p in puts_list
            if p.get("strike") is not None and price
            and p["strike"] < price
            and p.get("custom_metric") and p["custom_metric"] >= 10
        ]
        if not filtered_puts:
            continue
        best_put = max(filtered_puts, key=lambda x: x.get('premium_percent', 0) or x.get('premium', 0))
        expiration_fmt = datetime.datetime.strptime(best_put['expiration'], "%Y-%m-%d").strftime("%b %d, %Y") if best_put.get('expiration') else "N/A"
        buy_alert_line = format_buy_alert_line(
            ticker=sym,
            price=price if price is not None else 0.0,
            rsi=rsi_val if rsi_val is not None else 0.0,
            pe=pe if pe is not None else 0.0,
            mcap=cap_str if cap_str is not None else "N/A",
            strike=float(best_put['strike']) if best_put.get('strike') is not None else 0.0,
            expiration=expiration_fmt if expiration_fmt else "N/A",
            premium=float(best_put['premium']) if best_put.get('premium') is not None else 0.0,
            delta_percent=float(best_put['delta_percent']) if best_put.get('delta_percent') is not None else 0.0,
            premium_percent=float(best_put['premium_percent']) if best_put.get('premium_percent') is not None else 0.0
        )
        
        news_items = fetch_news_ticker(sym)
        summary_sentence = f"No recent reason found for {sym}."
        if (news_items and isinstance(news_items[0], dict) and 'error' in news_items[0]):
            # Optionally include error: summary_sentence = f"No news available for {sym} ({news_items[0]['error']})"
            pass  # Keep default summary_sentence, do not use below logic
        elif news_items:
            negative_news = [news for news in news_items if float(news.get('sentiment', 0)) < 0]
            use_news = None
            if negative_news:
                use_news = negative_news[0]
            else:
                use_news = news_items[0]
            if use_news is not None:
                article_text = use_news.get('article_text')
                reason_sentence = use_news.get('summary') or use_news.get('headline') or use_news.get('title')
                if not reason_sentence and article_text:
                    try:
                        summary = summarizer(article_text)
                    except Exception as e:
                        logger.error(f"Error during summarization: {e}")
                        summary = "No summary available."
                    reason_sentence = summary
                if reason_sentence:
                        summary_sentence = extend_to_next_period(reason_sentence)
        print(f"news_items for {sym}:", news_items)

        


        
        filtered_news = [
            news for news in news_items 
            if 'sentiment' in news 
            and news['sentiment'] is not None
            and (float(news['sentiment']) > 0.2 or float(news['sentiment']) < -0.2)
        ]
        sorted_news = sorted(filtered_news, key=lambda n: -float(n['sentiment']))
        top_news = sorted_news[:4]

        def sentiment_emoji(sent):
            s = float(sent)
            if s > 0.2:
                return "🟢"
            elif s < -0.2:
                return "🔴"
            else:
                return "⚪"
        news_html = '<ul class="news-list">'
        for news in top_news:
            emoji = sentiment_emoji(news['sentiment'])
            fval = f"{float(news['sentiment']):.1f}"
            news_html += f"<li><a href='{news['url']}'>{news['headline']}</a> - {emoji} {fval}</li>"
        news_html += '</ul>'

        price_str = f"{price:.2f}" if price is not None else "N/A"
        rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
        pe_str = f"{pe:.1f}" if pe is not None else "N/A"
        mcap_str = cap_str  # Already formatted above
        strike_str = f"{best_put['strike']:.1f}" if best_put.get('strike') is not None else "N/A"
        premium_str = f"{best_put['premium']:.2f}" if best_put.get('premium') is not None else "N/A"
        dp = f"{best_put['delta_percent']:.1f}%" if best_put.get('delta_percent') is not None else "N/A"
        pp = f"{best_put['premium_percent']:.1f}%" if best_put.get('premium_percent') is not None else "N/A"
        metric_sum = (best_put.get('delta_percent', 0) or 0) + (best_put.get('premium_percent', 0) or 0)
        metric_sum_str = f"{metric_sum:.1f}%" if (best_put.get('delta_percent') is not None and best_put.get('premium_percent') is not None) else "N/A"
        
        

        
        buy_alert_html = f"""
            <div class="main-info">
                <div>
                    <span class="ticker-alert">{sym}</span>
                </div>
                <div class="price-details">
                        <div class="current-price price-up">{price:.2f}</div>
                </div>                    
            </div>
            <p class="news-summary">
                    {buy_alert_line}
            </p>
            <p class="news-summary">{summary_sentence}</p>
                {news_html}
        """
        buy_alerts_web.append(buy_alert_html)




        
        puts_json_path = os.path.join(puts_dir, f"{sym}_puts_7weeks.json")
        try:
            with open(puts_json_path, "w") as fp:
                json.dump([best_put], fp, indent=2)
            logger.info(f"Saved puts data for {sym}")
        except Exception as e:
            logger.error(f"Failed to save puts json for {sym}: {e}")
    return buy_symbols, buy_alerts_web, all_sell_alerts, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    args = parser.parse_args()
    selected = [t.strip() for t in args.tickers.split(",")] if args.tickers else tickers
    retry_counts = defaultdict(int)
    to_process = selected[:]
    all_buy_symbols = []
    all_buy_alerts_web = []
    all_sell_alerts = []

    while to_process and any(retry_counts[t] < MAX_TICKER_RETRIES for t in to_process):
        logger.info(f"Processing {len(to_process)} tickers...")
        buys, buy_alerts_web, sells, fails = job(to_process)
        all_buy_alerts_web.extend(buy_alerts_web)
        all_sell_alerts.extend(sells)
        all_buy_symbols.extend(buys)
        for f in fails:
            retry_counts[f] += 1
        to_process = [f for f in fails if retry_counts[f] < MAX_TICKER_RETRIES]
        if to_process:
            logger.info(f"Rate limited. Waiting {TICKER_RETRY_WAIT} seconds before retrying {len(to_process)} tickers...")
            time.sleep(TICKER_RETRY_WAIT)

    seen = set()
    unique_buy_alerts_web = []
    for alert in all_buy_alerts_web:
        if alert not in seen:
            unique_buy_alerts_web.append(alert)
            seen.add(alert)
    all_buy_alerts_web = unique_buy_alerts_web

    seen = set()
    unique_sell_alerts = []
    for alert in all_sell_alerts:
        if alert not in seen:
            unique_sell_alerts.append(alert)
            seen.add(alert)
    all_sell_alerts = unique_sell_alerts

    
    logger.info("Writing HTML to index.html")
    with open("index.html", "w", encoding="utf-8") as f:
        f.write("<html><head><title>StockHome Trading Signals</title></head><body>\n")
        f.write("    <link rel='stylesheet' href='styles/style.css'>\n")  # Link to your stylesheet
        f.write("</head><body>\n")
        f.write("    <div class='header'>\n")
        
        f.write(f"<h1>StockHome Trading Signals</h1>\n")
        f.write(f"        <p>Generated at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Pacific Time</p>\n")
        f.write("    </div>\n")
        
        f.write("    <h2>Buy Signals</h2>\n")
        f.write("    <ul class='signals-container'>\n")
        
        for alert_html in buy_alerts_web:   # Use allbuyalerts or buyalerts as appropriate
            f.write(f"<li class='signal-card buy-card'>\n{alert_html}</li>\n")
        f.write("</ul>\n")
        
        f.write("    <h2>Sell Signals</h2>\n")
        f.write("    <ul class='signals-container'>\n")
        for alert_html in all_sell_alerts:
                        f.write(f"<li class='signal-card sell-card'>\n{alert_html}</li>\n")
        f.write("    </ul>\n")
        f.write("</body></html>\n")
    logger.info("Written index.html")

if __name__ == "__main__":
    main()
