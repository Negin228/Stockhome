import os
import datetime
import json
import yfinance as yf
import finnhub
from textblob import TextBlob
from newspaper import Article


API_KEY = os.getenv("API_KEY")
finnhub_client = finnhub.Client(api_key=API_KEY)

def fetch_news_ticker(ticker):
        summaries = []
        # Use yfinance's news fetching
        #from_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        #to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        #news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        try:
                ticker_obj = yf.Ticker(ticker)
                news_items = ticker_obj.news  # List of dicts with real news links!
                for item in news_items[:5]:
                    print(item.keys())
                    print(json.dumps(item, indent=2))  # show full available fields
                    meta = item.get("content", {})
                    headline = item.get("title") or meta.get("title", "")
                    summary = item.get("summary") or meta.get("summary", "")
                    url = (
                        item.get("url") or
                        (meta.get("canonicalUrl") or {}).get("url")
                        or (meta.get("clickThroughUrl") or {}).get("url")
                        or "")
                    blob = TextBlob(headline)
                    sentiment = blob.sentiment.polarity
                    text = ""
            
                    summaries.append({
                        "headline": headline,
                        "url": url,
                        "sentiment": sentiment,
                        "summary": summary if summary else headline,
                        "article_text": text[:500]})
                print("Fetched news for", ticker, ":", news_items)
                return summaries
        except Exception as e:
                return [{"error": str(e)}]
