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
    try:
        #from_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        #to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        #news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        ticker_obj = yf.Ticker(ticker)
        news = ticker_obj.news  # List of dicts with real news links!
        for article in news[:5]:
            print(article.keys())
            print(json.dumps(article, indent=2))  # show full available fields
            headline = article.get("title", "No Title")
            url = article.get("link", "#")
            blob = TextBlob(headline)
            sentiment = blob.sentiment.polarity
            try:
                art = Article(url)
                art.download()
                art.parse()
                text = art.text
            except Exception as e:
                text = ""


            
            summaries.append({
                "headline": headline,
                "url": url,
                "sentiment": sentiment,
                "summary": text[:500]  # Optionally, summarize with LLM here
            })
        return summaries
    except Exception as e:
        return [{"error": str(e)}]
    print("Fetched news for", ticker, ":", news)

# To use: fetch_news("AAPL")
