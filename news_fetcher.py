import yfinance as yf
from textblob import TextBlob

def fetch_news(ticker):
    # Use yfinance's news fetching
    try:
        stock = yf.Ticker(ticker)
        news = stock.news           # Returns dict of news articles (title, link etc.)
        summaries = []
        for article in news[:5]:
            headline = article["title"]
            url = article["link"]
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

# To use: fetch_news("AAPL")
