import os
import datetime
import json
import yfinance as yf
import finnhub
from textblob import TextBlob

API_KEY = os.getenv("API_KEY")
finnhub_client = finnhub.Client(api_key=API_KEY)

def fetch_news_ticker(ticker):
    # Use yfinance's news fetching
    try:
        from_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        summaries = []
        for article in news[:5]:
            print(article.keys())
            print(json.dumps(article, indent=2))  # show full available fields
            headline = article.get("headline", "No Title")
            url = article.get("url", "#")
            blob = TextBlob(headline)
            sentiment = blob.sentiment.polarity
            summaries.append({
                "headline": headline,
                "url": url,
                "sentiment": sentiment
            })
        return summaries
    except Exception as e:
        return [{"error": str(e)}]
    print("Fetched news for", ticker, ":", news)

# To use: fetch_news("AAPL")
